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
from jinja2 import Template
from src.utils.notifier import send_flex_carousel

CANDIDATES_FILE = os.path.join(PROJECT_ROOT, "data", "screened_candidates.json")
OUTPUT_HTML_DIR = os.path.join(PROJECT_ROOT, "docs")
OUTPUT_HTML_PATH = os.path.join(OUTPUT_HTML_DIR, "index.html")

MAX_AI_ANALYZE = 40

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tenbagger Hunter Pro - 週末厳選レポート</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151d30;
      --text-main: #f8fafc;
      --text-sub: #94a3b8;
      --accent-green: #10b981;
      --accent-blue: #38bdf8;
      --accent-red: #ef4444;
      --border: #243049;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      margin: 0;
      padding: 1.25rem;
    }
    .container { max-width: 1000px; margin: 0 auto; }
    header { border-bottom: 1px solid var(--border); padding-bottom: 1.2rem; margin-bottom: 1.5rem; }
    h1 { margin: 0 0 0.4rem 0; font-size: 1.6rem; display: flex; align-items: center; gap: 0.5rem; }
    .updated { color: var(--text-sub); font-size: 0.85rem; }
    
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
    .badge-stay { background: #3b82f6; color: white; font-size: 0.7rem; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
    .badge-new { background: #f59e0b; color: white; font-size: 0.7rem; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
    .tags { display: flex; gap: 0.35rem; margin-top: 0.25rem; }
    .tag { background: rgba(56, 189, 248, 0.15); color: var(--accent-blue); font-size: 0.75rem; padding: 2px 6px; border-radius: 4px; }
    
    .score-badge {
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-green);
      font-weight: bold;
      font-size: 1.2rem;
      padding: 0.25rem 0.75rem;
      border-radius: 6px;
      border: 1px solid var(--accent-green);
      text-align: center;
    }
    
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .stat-item { background: rgba(0, 0, 0, 0.25); padding: 0.5rem 0.75rem; border-radius: 6px; }
    .stat-label { font-size: 0.75rem; color: var(--text-sub); margin-bottom: 0.2rem; }
    .stat-val { font-size: 1rem; font-weight: bold; }
    
    .catalyst-box {
      background: rgba(56, 189, 248, 0.05);
      border-left: 3px solid var(--accent-blue);
      padding: 0.85rem;
      margin-bottom: 0.75rem;
      font-size: 0.92rem;
      line-height: 1.6;
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
    .action-links { display: flex; gap: 0.5rem; margin-top: 0.5rem; }
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
      <h1>🎯 Tenbagger Hunter Pro 厳選レポート</h1>
      <div class="updated">生成日時: {{ generated_at }} | 分析銘柄数: {{ total_screened }}件</div>
    </header>

    <div class="controls">
      <div>
        <label style="font-size: 0.85rem; color: var(--text-sub);">並び替え:</label>
        <select id="sortSelect" onchange="sortCards()">
          <option value="score">AIスコア順</option>
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
           data-market-cap="{{ stock.market_cap_oku }}"
           data-surge="{{ stock.vol_surge }}"
           data-growth="{{ stock.rev_growth_pct }}"
           data-text="{{ stock.code }} {{ stock.name }} {{ stock.sector }} {{ ' '.join(stock.analysis.theme_tags) }}">
        <div class="card-header">
          <div>
            <div class="stock-title-wrap">
              <span class="stock-title">{{ stock.code }} {{ stock.name }}</span>
              <span style="font-size: 0.85rem; color: var(--text-sub);">({{ stock.market }} / {{ stock.sector }})</span>
              {% if stock.badge == 'STAY' %}
                <span class="badge-stay">2週連続</span>
              {% else %}
                <span class="badge-new">今週初</span>
              {% endif %}
            </div>
            <div class="tags">
              {% for tag in stock.analysis.theme_tags %}
                <span class="tag">#{{ tag }}</span>
              {% endfor %}
            </div>
          </div>
          <div class="score-badge">
            <div style="font-size: 0.75rem; color: var(--text-sub); font-weight: normal;">潜在スコア</div>
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
            <div class="stat-label">直近売上高YoY</div>
            <div class="stat-val" style="color: {% if stock.rev_growth_pct > 15 %}var(--accent-green){% else %}inherit{% endif %}">+{{ stock.rev_growth_pct }}%</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">出来高急増度</div>
            <div class="stat-val" style="color: var(--accent-blue);">{{ stock.vol_surge }}倍</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">買い目安 / 損切り</div>
            <div class="stat-val" style="font-size: 0.9rem;">{{ stock.analysis.entry_price }} / <span style="color: var(--accent-red);">{{ stock.analysis.stop_loss }}</span></div>
          </div>
          <div class="stat-item">
            <div class="stat-label">リスクリワード比</div>
            <div class="stat-val" style="color: var(--accent-green);">1 : {{ stock.analysis.risk_reward_ratio }}</div>
          </div>
        </div>

        <div class="catalyst-box">
          <strong>【成長ストーリー＆カタリスト】</strong><br>
          {{ stock.analysis.growth_story }}
        </div>

        <div class="plan-box">
          <div><strong>警戒リスク:</strong> {{ stock.analysis.risk_factors }}</div>
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

      cards.sort((a, b) => {
        if (criteria === "score") return Number(b.dataset.score) - Number(a.dataset.score);
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
    """Geminiの出力から余分なMarkdownを除去して安全にJSON変換"""
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
        return json.loads(cleaned)
    except Exception:
        return None

def analyze_stock_with_gemini(client, stock_info):
    """Gemini 3.6-flash を使用したテンバガー潜在力分析（安定・高速版）"""
    prompt = f"""
あなたは急成長小型株（テンバガー）投資のスペシャリストです。
以下の企業スペックとモメンタム指標に基づき、この銘柄の成長性、テーマ合致度、および売買プランを策定してください。

【対象銘柄】
銘柄コード: {stock_info['code']}
銘柄名: {stock_info['name']}
市場・業種: {stock_info['market']} / {stock_info['sector']}
現在株価: {stock_info['close']}円
時価総額: {stock_info['market_cap_oku']}億円
直近売上高成長率: +{stock_info.get('rev_growth_pct', 0)}%
出来高急増比: {stock_info.get('vol_surge', 1.0)}倍

【出力要件】
1. score: テンバガー潜在力スコア（0〜100）
2. theme_tags: 合致する市場テーマ（例: ["AI", "DX", "半導体"] など最大3つ）
3. growth_story: 業績モメンタムや市場テーマを踏まえた株価起爆カタリスト（130〜150字程度）
4. risk_factors: 最大の警戒リスク要因（80字程度）
5. entry_price: 押し目またはブレイク買いの目安価格（現在値 {stock_info['close']}円 基準）
6. stop_loss: 厳格な損切りライン（買値から約 -7%〜-8%）
7. risk_reward_ratio: 目標株価と損切り幅から算出するリスクリワード比（数値のみ。例: 3.2）

以下のJSONフォーマットのみを返してください。
{{
  "score": 85,
  "theme_tags": ["テーマ1", "テーマ2"],
  "growth_story": "...",
  "risk_factors": "...",
  "entry_price": 0,
  "stop_loss": 0,
  "risk_reward_ratio": 3.2
}}
"""
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config={
                    "response_mime_type": "application/json"
                }
            )
            res_json = clean_and_parse_json(response.text)
            if res_json and "score" in res_json and "growth_story" in res_json:
                if "theme_tags" not in res_json or not res_json["theme_tags"]:
                    res_json["theme_tags"] = [stock_info["sector"]]
                if "risk_reward_ratio" not in res_json:
                    res_json["risk_reward_ratio"] = 3.0
                return res_json
        except Exception as e:
            print(f"[WARN] Gemini分析 試行 {attempt + 1}/2 失敗 ({stock_info['code']}): {e}")
            time.sleep(1)

    # 万一失敗した場合のフォールバック
    stop = round(float(stock_info['close']) * 0.92, 1)
    return {
        "score": 75,
        "theme_tags": [stock_info["sector"]],
        "growth_story": f"{stock_info['name']}は直近売上高成長率+{stock_info.get('rev_growth_pct', 0)}%、出来高急増比{stock_info.get('vol_surge', 1.0)}倍と強いモメンタムを維持。独自事業の進捗が注目点。",
        "risk_factors": "新興小型株特有の流動性低下および相場地合いの調整リスク。",
        "entry_price": stock_info['close'],
        "stop_loss": stop,
        "risk_reward_ratio": 3.0
    }

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

    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else None

    analyzed_stocks = []
    print(f"[INFO] 厳選 {len(candidates)} 銘柄のGemini詳細分析を開始...")

    for item in candidates:
        print(f"  -> 分析中: {item['code']} {item['name']}")
        if client:
            analysis = analyze_stock_with_gemini(client, item)
        else:
            stop = round(float(item['close']) * 0.92, 1)
            analysis = {
                "score": 70,
                "theme_tags": [item["sector"]],
                "growth_story": "上昇トレンド基調と売買代金の維持を監視。",
                "risk_factors": "地合い悪化による短期的なボラティリティ上昇。",
                "entry_price": item['close'],
                "stop_loss": stop,
                "risk_reward_ratio": 3.0
            }
        item['analysis'] = analysis
        analyzed_stocks.append(item)
        time.sleep(0.3)

    analyzed_stocks.sort(key=lambda x: x['analysis']['score'], reverse=True)

    # HTML出力
    os.makedirs(OUTPUT_HTML_DIR, exist_ok=True)
    template = Template(HTML_TEMPLATE)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html_output = template.render(
        generated_at=now_str,
        total_screened=len(candidates),
        analyzed_stocks=analyzed_stocks
    )

    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_output)

    file_size = os.path.getsize(OUTPUT_HTML_PATH)
    print(f"[INFO] レポート出力完了: {OUTPUT_HTML_PATH} ({file_size} bytes)")

    # LINE Flex Message 送信
    repo_name = os.getenv("GITHUB_REPOSITORY", "sei1r0/tenbagger-hunter")
    pages_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}/"

    send_flex_carousel("週末テンバガー厳選TOP銘柄", analyzed_stocks[:5], pages_url)
    print("[INFO] 全パイプライン処理が正常に完了しました。")

if __name__ == "__main__":
    main()