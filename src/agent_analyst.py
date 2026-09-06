import os
import sys
import json
import re
import time
import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from google import genai
from google.genai import types
from jinja2 import Template
from src.utils.notifier import send_flex_carousel
from src.utils.market_overview import fetch_market_indices
from src.utils.market_calendar import get_jst_now

CANDIDATES_FILE = os.path.join(PROJECT_ROOT, "data", "screened_candidates.json")
OUTPUT_HTML_DIR = os.path.join(PROJECT_ROOT, "docs")
OUTPUT_HTML_PATH = os.path.join(OUTPUT_HTML_DIR, "index.html")

MAX_AI_ANALYZE = 20
MAX_TRANSIENT_ERRORS = 2

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tenbagger Hunter Pro - 週末厳選AIレポート</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151d30;
      --text-main: #f8fafc;
      --text-sub: #94a3b8;
      --accent-green: #10b981;
      --accent-blue: #38bdf8;
      --accent-red: #ef4444;
      --accent-gold: #f59e0b;
      --accent-purple: #a855f7;
      --border: #243049;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      margin: 0;
      padding: 1.25rem;
    }
    .container { max-width: 1040px; margin: 0 auto; }
    header { border-bottom: 1px solid var(--border); padding-bottom: 1.2rem; margin-bottom: 1.5rem; }
    h1 { margin: 0 0 0.4rem 0; font-size: 1.6rem; display: flex; align-items: center; gap: 0.5rem; }
    .updated { color: var(--text-sub); font-size: 0.85rem; }

    /* 主要指数パネル */
    .market-panel {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1.75rem;
    }
    .market-card {
      background: rgba(30, 41, 59, 0.7);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem;
    }
    .market-title { font-size: 0.85rem; font-weight: bold; color: var(--accent-blue); margin-bottom: 0.2rem; }
    .market-val { font-size: 1.1rem; font-weight: bold; margin-bottom: 0.3rem; }
    .market-change { font-size: 0.75rem; }
    .pos { color: var(--accent-green); }
    .neg { color: var(--accent-red); }

    /* コントロールバー */
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1.5rem;
      align-items: center;
      background: rgba(255,255,255,0.03);
      padding: 0.75rem;
      border-radius: 8px;
      border: 1px solid var(--border);
    }
    .controls input, .controls select {
      background: var(--card-bg);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 0.4rem 0.75rem;
      border-radius: 6px;
      font-size: 0.9rem;
    }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.25rem;
      margin-bottom: 1.5rem;
      box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 0.75rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.07);
      padding-bottom: 0.6rem;
    }
    .stock-title-wrap { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
    .stock-title { font-size: 1.25rem; font-weight: bold; }
    
    /* 確信度バッジ */
    .tier-badge { font-size: 0.75rem; font-weight: bold; padding: 3px 8px; border-radius: 4px; display: inline-flex; align-items: center; }
    .tier-badge-s { background: linear-gradient(135deg, #7e22ce, #eab308); color: #ffffff; border: 1px solid #facc15; }
    .tier-badge-a { background: rgba(16, 185, 129, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }
    .tier-badge-b { background: rgba(56, 189, 248, 0.2); color: var(--accent-blue); border: 1px solid var(--accent-blue); }

    .badge-stay { background: #3b82f6; color: white; font-size: 0.7rem; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
    .badge-new { background: #f59e0b; color: white; font-size: 0.7rem; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
    
    /* クオンツ・需給タグ */
    .quant-tags { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.35rem; }
    .pill { font-size: 0.72rem; padding: 2px 6px; border-radius: 4px; font-weight: 500; }
    .pill-theme { background: rgba(56, 189, 248, 0.12); color: var(--accent-blue); }
    .pill-moat { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); }
    .pill-vcp { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.5); font-weight: bold; }
    .pill-rs { background: rgba(16, 185, 129, 0.12); color: var(--accent-green); }
    .pill-founder { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
    .pill-cash { background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
    .pill-turnaround { background: rgba(234, 179, 8, 0.18); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.4); }
    .pill-light { background: rgba(244, 114, 182, 0.18); color: #f472b6; border: 1px solid rgba(244, 114, 182, 0.4); }

    .score-badge {
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-green);
      font-weight: bold;
      font-size: 1.25rem;
      padding: 0.3rem 0.8rem;
      border-radius: 6px;
      border: 1px solid var(--accent-green);
      text-align: center;
      min-width: 70px;
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 0.6rem;
      margin-bottom: 0.85rem;
    }
    .stat-item { background: rgba(0, 0, 0, 0.25); padding: 0.5rem 0.65rem; border-radius: 6px; }
    .stat-label { font-size: 0.72rem; color: var(--text-sub); margin-bottom: 0.2rem; }
    .stat-val { font-size: 0.95rem; font-weight: bold; }

    .tam-bar {
      background: rgba(255, 255, 255, 0.03);
      border: 1px dashed var(--border);
      padding: 0.5rem 0.75rem;
      border-radius: 6px;
      font-size: 0.82rem;
      color: #cbd5e1;
      margin-bottom: 0.75rem;
    }

    .debate-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.75rem;
      margin-bottom: 0.85rem;
    }
    @media (max-width: 700px) {
      .debate-grid { grid-template-columns: 1fr; }
    }
    .bull-box {
      background: rgba(16, 185, 129, 0.05);
      border-left: 3px solid var(--accent-green);
      padding: 0.75rem;
      font-size: 0.86rem;
      line-height: 1.55;
      border-radius: 0 6px 6px 0;
    }
    .bear-box {
      background: rgba(239, 68, 68, 0.05);
      border-left: 3px solid var(--accent-red);
      padding: 0.75rem;
      font-size: 0.86rem;
      line-height: 1.55;
      border-radius: 0 6px 6px 0;
    }

    .plan-box {
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.75rem;
      font-size: 0.85rem;
      background: rgba(0, 0, 0, 0.3);
      padding: 0.6rem 0.85rem;
      border-radius: 6px;
      align-items: center;
    }
    .action-links { display: flex; gap: 0.5rem; margin-top: 0.3rem; }
    .btn-link {
      font-size: 0.75rem;
      color: #94a3b8;
      text-decoration: none;
      background: rgba(255,255,255,0.06);
      padding: 0.3rem 0.6rem;
      border-radius: 4px;
      border: 1px solid var(--border);
    }
    .btn-link:hover { color: #fff; background: rgba(255,255,255,0.12); }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>🎯 Tenbagger Hunter Pro 厳選AIレポート</h1>
      <div class="updated">生成日時: {{ generated_at }} | 厳選プール: {{ total_screened }}件</div>
    </header>

    <!-- 主要指数パネル -->
    <div class="market-panel">
      {% for m in market_indices %}
      <div class="market-card">
        <div class="market-title">{{ m.icon }} {{ m.name }} <span style="font-size: 0.72rem; color: var(--text-sub); font-weight: normal;">({{ m.desc }})</span></div>
        <div class="market-val">{{ m.display_val }}</div>
        <div class="market-change">
          <div>前週比: <span class="{% if m.week_diff >= 0 %}pos{% else %}neg{% endif %}">{% if m.week_diff > 0 %}+{% endif %}{{ m.week_pct }}% ({{ m.display_week_diff }})</span></div>
          <div>年初来: <span class="{% if m.ytd_diff >= 0 %}pos{% else %}neg{% endif %}">{% if m.ytd_diff > 0 %}+{% endif %}{{ m.ytd_pct }}% ({{ m.display_ytd_diff }})</span></div>
        </div>
      </div>
      {% endfor %}
    </div>

    <div class="controls">
      <div>
        <label style="font-size: 0.85rem; color: var(--text-sub);">並び替え:</label>
        <select id="sortSelect" onchange="sortCards()">
          <option value="score">AIスコア順</option>
          <option value="conviction">確信度順 (S > A > B)</option>
          <option value="rs">RS（市場相対力）順</option>
          <option value="market_cap">時価総額が小さい順</option>
          <option value="surge">出来高急増率順</option>
          <option value="growth">売上成長率順</option>
        </select>
      </div>
      <div>
        <input type="text" id="filterInput" onkeyup="filterCards()" placeholder="銘柄名・コード・テーマ検索...">
      </div>
    </div>

    <div id="cardsContainer">
      {% for stock in analyzed_stocks %}
      <div class="card" 
           data-score="{{ stock.analysis.score }}" 
           data-conviction="{{ stock.analysis.conviction_tier }}"
           data-rs="{{ stock.rs_rating or 0 }}"
           data-market-cap="{{ stock.market_cap_oku }}"
           data-surge="{{ stock.vol_surge }}"
           data-growth="{{ stock.rev_growth_pct }}"
           data-text="{{ stock.code }} {{ stock.name }} {{ stock.sector }} {{ stock.analysis.conviction_tier }} {{ ' '.join(stock.analysis.theme_tags) }}">
        
        <div class="card-header">
          <div>
            <div class="stock-title-wrap">
              <span class="stock-title">{{ stock.code }} {{ stock.name }}</span>
              <span style="font-size: 0.85rem; color: var(--text-sub);">({{ stock.market }} / {{ stock.sector }})</span>
              
              <!-- 確信度バッジ -->
              {% if stock.analysis.conviction_tier == 'S' %}
                <span class="tier-badge tier-badge-s">★Sランク超本命</span>
              {% elif stock.analysis.conviction_tier == 'A' %}
                <span class="tier-badge tier-badge-a">Aランク有力</span>
              {% else %}
                <span class="tier-badge tier-badge-b">Bランク監視</span>
              {% endif %}

              {% if stock.badge == 'STAY' %}
                <span class="badge-stay">2週連続</span>
              {% else %}
                <span class="badge-new">今週初</span>
              {% endif %}
            </div>

            <!-- クオンツ・需給・Moatタグ -->
            <div class="quant-tags">
              {% if stock.is_ultra_light %}
                <span class="pill pill-light">🎈 浮動株 {{ stock.float_mcap_oku }}億 (超軽量)</span>
              {% endif %}
              {% if stock.is_vcp %}
                <span class="pill pill-vcp">🔥 VCP売り枯れ点灯</span>
              {% endif %}
              <span class="pill pill-rs">RS: +{{ stock.rs_rating }}%</span>
              <span class="pill pill-moat">🏰 参入障壁: {{ stock.analysis.moat_rating }}</span>
              {% if stock.insider_held_pct and stock.insider_held_pct >= 20 %}
                <span class="pill pill-founder">👑 創業者等: {{ stock.insider_held_pct }}%</span>
              {% endif %}
              {% if stock.is_net_cash %}
                <span class="pill pill-cash">💰 実質無借金 (NetCash)</span>
              {% endif %}
              {% if stock.is_turnaround %}
                <span class="pill pill-turnaround">⚡ 黒字成長モメンタム</span>
              {% endif %}
              {% for tag in stock.analysis.theme_tags %}
                <span class="pill pill-theme">#{{ tag }}</span>
              {% endfor %}
            </div>
          </div>

          <div class="score-badge">
            <div style="font-size: 0.72rem; color: var(--text-sub); font-weight: normal;">潜在スコア</div>
            {{ stock.analysis.score }}点
          </div>
        </div>

        <div class="stats-grid">
          <div class="stat-item">
            <div class="stat-label">現在株価</div>
            <div class="stat-val">{{ stock.close }}円</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">時価総額</div>
            <div class="stat-val">{{ stock.market_cap_oku }}億円</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">売上高YoY</div>
            <div class="stat-val" style="color: {% if stock.rev_growth_pct > 15 %}var(--accent-green){% else %}inherit{% endif %}">+{{ stock.rev_growth_pct }}%</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">営業利益率</div>
            <div class="stat-val" style="color: {% if stock.op_margin_pct > 10 %}var(--accent-green){% else %}inherit{% endif %}">+{{ stock.op_margin_pct }}%</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">創業者保有比率</div>
            <div class="stat-val" style="color: {% if stock.insider_held_pct >= 30 %}var(--accent-gold){% else %}inherit{% endif %}">{% if stock.insider_held_pct %}{{ stock.insider_held_pct }}%{% else %}-{% endif %}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">PER / PSR</div>
            <div class="stat-val" style="font-size: 0.85rem;">{% if stock.trailing_pe %}{{ stock.trailing_pe }}倍{% else %}-{% endif %} / {% if stock.psr %}{{ stock.psr }}倍{% else %}-{% endif %}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">買値目安 / 損切り</div>
            <div class="stat-val" style="font-size: 0.85rem;">{{ stock.analysis.entry_price }} / <span style="color: var(--accent-red);">{{ stock.analysis.stop_loss }}</span></div>
          </div>
          <div class="stat-item">
            <div class="stat-label">リスクリワード比</div>
            <div class="stat-val" style="color: var(--accent-green);">1 : {{ stock.analysis.risk_reward_ratio }}</div>
          </div>
        </div>

        <!-- TAM 市場規模表示 -->
        <div class="tam-bar">
          <strong>🌐 獲得可能市場 (TAM):</strong> {{ stock.analysis.tam_scale }}
        </div>

        <!-- Bull/Bear ディベートボックス -->
        <div class="debate-grid">
          <div class="bull-box">
            <strong style="color: var(--accent-green);">🚀【強気シナリオ＆カタリスト】</strong><br>
            {{ stock.analysis.growth_story }}
          </div>
          <div class="bear-box">
            <strong style="color: var(--accent-red);">🛡️【弱気・落とし穴リスク監査】</strong><br>
            {{ stock.analysis.risk_factors }}
          </div>
        </div>

        <div class="plan-box">
          <div style="font-size: 0.8rem; color: var(--text-sub);">
            25MA: {{ stock.sma25 }}円 (乖離: +{{ stock.deviation_25_pct }}%) | 52週高値: {{ stock.high_52w }}円 | 大口比: {{ stock.up_down_ratio }}倍
          </div>
          <div class="action-links">
            <a class="btn-link" href="https://kabutan.jp/stock/chart?code={{ stock.code }}" target="_blank">📊 株探チャート</a>
            <a class="btn-link" href="https://jp.tradingview.com/symbols/TSE-{{ stock.code }}/" target="_blank">📈 TradingView</a>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <script>
    function sortCards() {
      const criteria = document.getElementById("sortSelect").value;
      const container = document.getElementById("cardsContainer");
      const cards = Array.from(container.getElementsByClassName("card"));

      const tierRank = {"S": 3, "A": 2, "B": 1};

      cards.sort((a, b) => {
        if (criteria === "score") return Number(b.dataset.score) - Number(a.dataset.score);
        if (criteria === "conviction") return (tierRank[b.dataset.conviction] || 0) - (tierRank[a.dataset.conviction] || 0);
        if (criteria === "rs") return Number(b.dataset.rs) - Number(a.dataset.rs);
        if (criteria === "market_cap") return Number(a.dataset.marketCap) - Number(b.dataset.marketCap);
        if (criteria === "surge") return Number(b.dataset.surge) - Number(a.dataset.surge);
        if (criteria === "growth") return Number(b.dataset.growth) - Number(a.dataset.growth);
        return 0;
      });

      cards.forEach(c => container.appendChild(c));
    }

    function filterCards() {
      const q = document.getElementById("filterInput").value.toLowerCase();
      const cards = document.getElementsByClassName("card");
      for (let card of cards) {
        const text = card.dataset.text.toLowerCase();
        card.style.display = text.includes(q) ? "block" : "none";
      }
    }
  </script>
</body>
</html>
"""

def clean_and_parse_json(text):
    try:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
        return json.loads(cleaned)
    except Exception:
        return None

def analyze_stock_with_gemini(client, stock_info):
    vcp_status = "点灯中（売り圧力枯渇・ブレイクアウト直前）" if stock_info.get("is_vcp") else "通常推移"
    psr_str = f"{stock_info.get('psr')}倍" if stock_info.get("psr") else "算出外"
    pe_str = f"{stock_info.get('trailing_pe')}倍" if stock_info.get("trailing_pe") else "算出外"
    insider_str = f"{stock_info.get('insider_held_pct')}%" if stock_info.get("insider_held_pct") else "未開示/微小"
    summary_str = stock_info.get("business_summary") or "新興成長企業"
    float_str = f"{stock_info.get('float_mcap_oku')}億円（超軽量需給）" if stock_info.get("is_ultra_light") else f"{stock_info.get('float_mcap_oku', stock_info['market_cap_oku'])}億円"
    cash_str = "実質無借金（現預金 > 有利子負債、希薄化リスク極小）" if stock_info.get("is_net_cash") else "通常"
    turnaround_str = "高成長・営業黒字定着" if stock_info.get("is_turnaround") else "通常推移"

    prompt = f"""
あなたは急成長小型株（テンバガー）投資のトップクオンツ＆ファンダメンタルズスペシャリストです。
以下の企業スペック、需給指標（RS/VCP/浮動株）、創業者比率、およびチャート重要価格に基づき、厳格なレッドチーム（強気・弱気ディベート）分析を実施し、売買プランを策定してください。

【対象銘柄スペック】
銘柄コード: {stock_info['code']}
銘柄名: {stock_info['name']}
市場・業種: {stock_info['market']} / {stock_info['sector']}
公式事業概要: {summary_str}
現在株価: {stock_info['close']}円
25日移動平均線: {stock_info.get('sma25')}円 (乖離: +{stock_info.get('deviation_25_pct')}%)
52週最高値: {stock_info.get('high_52w')}円
時価総額: {stock_info['market_cap_oku']}億円 (推定浮動株時価: {float_str})
財務健全性（ネットキャッシュ）: {cash_str}
収益モメンタム: {turnaround_str}
直近売上高成長率: +{stock_info.get('rev_growth_pct', 0)}%
直近営業利益率: +{stock_info.get('op_margin_pct', 0)}%
創業者・役員保有比率: {insider_str}
PER: {pe_str} / PSR: {psr_str}
RS（対グロース250超過リターン）: +{stock_info.get('rs_rating', 0)}%
出来高枯渇VCPシグナル: {vcp_status}
出来高急増比: {stock_info.get('vol_surge', 1.0)}倍

【分析・出力要件】
1. score: テンバガー潜在力総合スコア（0〜100）
2. conviction_tier: 確信度ランク（"S": 超本命・条件完全合致, "A": 有力成長株, "B": 監視・短期モメンタム型）
3. theme_tags: 合致する市場テーマ（最大3つ。例: ["AI", "DX", "次世代インフラ"]）
4. tam_scale: 獲得可能市場規模（TAM）の規模感（30字以内。例: 「国内5,000億円超のDX市場」「世界メガトレンド領域」）
5. moat_rating: 参入障壁・競争優位性（"HIGH": 独自特許/強固なスイッチングコスト, "MEDIUM": 先行者優位/高シェア, "LOW": 価格競争リスク）
6. growth_story: 10倍化への起爆シナリオ（強気視点、業績モメンタムやTAM展開を130〜150字程度で明瞭に記述）
7. risk_factors: 最大の警戒リスク・落とし穴（弱気監査視点、競合参入や一過性特需などを80字程度で厳格に記述）
8. entry_price: 押し目(25MA {stock_info.get('sma25')}円 付近)またはブレイク買い(52週高値 {stock_info.get('high_52w')}円 超)の目安価格
9. stop_loss: 厳格な損切りライン（買値または25MA割れ基準で約 -7%〜-8%）
10. risk_reward_ratio: リスクリワード比（数値のみ。例: 3.5）

以下のJSONフォーマットのみを返してください。
{{
  "score": 88,
  "conviction_tier": "S",
  "theme_tags": ["テーマ1", "テーマ2"],
  "tam_scale": "国内3,000億円超の市場",
  "moat_rating": "HIGH",
  "growth_story": "...",
  "risk_factors": "...",
  "entry_price": 0,
  "stop_loss": 0,
  "risk_reward_ratio": 3.5
}}
"""
    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        res_json = clean_and_parse_json(response.text)
        if res_json and "score" in res_json and "growth_story" in res_json:
            if "theme_tags" not in res_json or not res_json["theme_tags"]:
                res_json["theme_tags"] = [stock_info["sector"]]
            if "conviction_tier" not in res_json or res_json["conviction_tier"] not in ("S", "A", "B"):
                res_json["conviction_tier"] = "A" if res_json["score"] >= 80 else "B"
            if "moat_rating" not in res_json:
                res_json["moat_rating"] = "MEDIUM"
            if "tam_scale" not in res_json:
                res_json["tam_scale"] = f"{stock_info['sector']}関連市場"
            if "risk_reward_ratio" not in res_json:
                res_json["risk_reward_ratio"] = 3.0
            return res_json, "SUCCESS"
    except Exception as e:
        err_msg = str(e).upper()
        print(f"[WARN] Gemini分析エラー ({stock_info['code']}): {e}")
        fatal_keywords = ["429", "RESOURCE_EXHAUSTED", "QUOTA", "401", "403", "UNAUTHORIZED", "PERMISSION"]
        if any(kw in err_msg for kw in fatal_keywords):
            return None, "FATAL_ERROR"
        return None, "RETRY_ERROR"

    return None, "RETRY_ERROR"

def main():
    print(f"[INFO] 候補ファイル確認: {CANDIDATES_FILE}")
    if not os.path.exists(CANDIDATES_FILE):
        print(f"[ERROR] {CANDIDATES_FILE} が見つかりません。")
        sys.exit(1)

    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    print(f"[INFO] スクリーニング候補: {len(candidates)}件")
    if not candidates:
        print("[INFO] 候補が0件のため終了します。")
        return

    if len(candidates) > MAX_AI_ANALYZE:
        candidates = candidates[:MAX_AI_ANALYZE]

    # 指数データの取得
    print("[INFO] 主要マクロ指数のパフォーマンスを取得中...")
    market_indices = fetch_market_indices()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[CRITICAL ERROR] GEMINI_API_KEY が設定されていません。")
        sys.exit(1)

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=15000)
    )

    analyzed_stocks = []
    consecutive_transient_errors = 0
    print(f"[INFO] 厳選 {len(candidates)} 銘柄のGemini詳細分析（Red-Teamディベート）を開始...")

    for item in candidates:
        print(f"  -> 分析中: {item['code']} {item['name']}")
        analysis, status = analyze_stock_with_gemini(client, item)
        
        if status == "FATAL_ERROR":
            print("[FATAL] クォータ枯渇または認証エラーを検知。緊急遮断します。")
            sys.exit(1)

        if status == "RETRY_ERROR":
            consecutive_transient_errors += 1
            print(f"[WARN] 一時的APIエラー (連続 {consecutive_transient_errors}/{MAX_TRANSIENT_ERRORS})")
            if consecutive_transient_errors >= MAX_TRANSIENT_ERRORS:
                print("[FATAL] 連続API障害のため緊急遮断します。")
                sys.exit(1)
            
            stop = round(float(item['close']) * 0.92, 1)
            analysis = {
                "score": 75,
                "conviction_tier": "B",
                "theme_tags": [item["sector"]],
                "tam_scale": f"{item['sector']}関連領域",
                "moat_rating": "MEDIUM",
                "growth_story": f"{item['name']}はモメンタムと出来高水準を維持。独自事業の進捗が注目点。",
                "risk_factors": "一時的な通信エラーのためテクニカル算定値を暫定表示。",
                "entry_price": item['close'],
                "stop_loss": stop,
                "risk_reward_ratio": 3.0
            }
        else:
            consecutive_transient_errors = 0

        item['analysis'] = analysis
        analyzed_stocks.append(item)
        time.sleep(0.3)

    analyzed_stocks.sort(key=lambda x: x['analysis']['score'], reverse=True)

    # HTML出力
    os.makedirs(OUTPUT_HTML_DIR, exist_ok=True)
    template = Template(HTML_TEMPLATE, autoescape=True)
    now_str = get_jst_now().strftime("%Y-%m-%d %H:%M JST")
    html_output = template.render(
        generated_at=now_str,
        total_screened=len(candidates),
        analyzed_stocks=analyzed_stocks,
        market_indices=market_indices
    )

    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_output)

    file_size = os.path.getsize(OUTPUT_HTML_PATH)
    print(f"[INFO] レポート出力完了: {OUTPUT_HTML_PATH} ({file_size} bytes)")

    # LINE Flex Message 送信（指数カード ＋ 厳選個別株）
    repo_name = os.getenv("GITHUB_REPOSITORY", "sei1r0/tenbagger-hunter")
    pages_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}/"

    send_flex_carousel("週末マーケット＆テンバガー厳選TOP", analyzed_stocks, pages_url, market_data=market_indices)
    print("[INFO] 全パイプライン処理が正常に完了しました。")

if __name__ == "__main__":
    main()