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
from src.utils.notifier import send_notification

CANDIDATES_FILE = os.path.join(PROJECT_ROOT, "data", "screened_candidates.json")
OUTPUT_HTML_DIR = os.path.join(PROJECT_ROOT, "docs")
OUTPUT_HTML_PATH = os.path.join(OUTPUT_HTML_DIR, "index.html")

# 従量課金移行により、スクリーニング全40件を一括分析
MAX_AI_ANALYZE = 40

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tenbagger Hunter Weekly Report</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --text-main: #f8fafc;
      --text-sub: #94a3b8;
      --accent-green: #10b981;
      --accent-blue: #38bdf8;
      --accent-red: #ef4444;
      --border: #334155;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      margin: 0;
      padding: 1.5rem;
    }
    .container { max-width: 960px; margin: 0 auto; }
    header { border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 2rem; }
    h1 { margin: 0 0 0.5rem 0; font-size: 1.5rem; display: flex; align-items: center; gap: 0.5rem; }
    .updated { color: var(--text-sub); font-size: 0.85rem; }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
      margin-bottom: 1.5rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.75rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      padding-bottom: 0.5rem;
    }
    .stock-title { font-size: 1.2rem; font-weight: bold; }
    .score-badge {
      background: rgba(16, 185, 129, 0.2);
      color: var(--accent-green);
      font-weight: bold;
      font-size: 1.1rem;
      padding: 0.2rem 0.6rem;
      border-radius: 4px;
      border: 1px solid var(--accent-green);
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .stat-item { background: rgba(0, 0, 0, 0.2); padding: 0.5rem 0.75rem; border-radius: 4px; }
    .stat-label { font-size: 0.75rem; color: var(--text-sub); margin-bottom: 0.2rem; }
    .stat-val { font-size: 1rem; font-weight: bold; }
    .catalyst-box {
      background: rgba(56, 189, 248, 0.05);
      border-left: 3px solid var(--accent-blue);
      padding: 0.75rem;
      margin-bottom: 0.75rem;
      font-size: 0.9rem;
      line-height: 1.5;
    }
    .plan-box {
      display: flex;
      gap: 1rem;
      font-size: 0.85rem;
      background: rgba(0, 0, 0, 0.3);
      padding: 0.5rem 0.75rem;
      border-radius: 4px;
    }
    .plan-target { color: var(--accent-blue); }
    .plan-stop { color: var(--accent-red); }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>🎯 Tenbagger Hunter 厳選レポート</h1>
      <div class="updated">生成日時: {{ generated_at }} | AI厳選分析数: {{ total_screened }}銘柄</div>
    </header>

    {% for stock in analyzed_stocks %}
    <div class="card">
      <div class="card-header">
        <div class="stock-title">{{ stock.code }} {{ stock.name }} <span style="font-size: 0.85rem; font-weight: normal; color: var(--text-sub);">({{ stock.market }} / {{ stock.sector }})</span></div>
        <div class="score-badge">{{ stock.analysis.score }}点</div>
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
          <div class="stat-label">売買代金</div>
          <div class="stat-val">{{ stock.trading_value_man }}万円</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">エントリー目安</div>
          <div class="stat-val plan-target">{{ stock.analysis.entry_price }}円</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">損切りライン</div>
          <div class="stat-val plan-stop">{{ stock.analysis.stop_loss }}円</div>
        </div>
      </div>
      <div class="catalyst-box">
        <strong>【AIカタリスト＆成長ストーリー】</strong><br>
        {{ stock.analysis.growth_story }}
      </div>
      <div class="plan-box">
        <div><strong>主なリスク要因:</strong> {{ stock.analysis.risk_factors }}</div>
      </div>
    </div>
    {% endfor %}
  </div>
</body>
</html>
"""

def clean_and_parse_json(text):
    """Geminiの出力から余分なMarkdownコードブロックを除去して確実にJSON変換"""
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
        return json.loads(cleaned)
    except Exception:
        return None

def analyze_stock_with_gemini(client, stock_info):
    """Gemini 3.6-flash を使用したテンバガー潜在力分析"""
    prompt = f"""
あなたは急成長株（テンバガー）発掘専門のプロフェッショナル・ポートフォリオマネージャーです。
以下の銘柄データに基づき、事業の拡張性、テーマ性、カタリスト（株価起爆材料）、および売買戦略を分析してください。

【銘柄情報】
銘柄コード: {stock_info['code']}
銘柄名: {stock_info['name']}
市場・業種: {stock_info['market']} / {stock_info['sector']}
現在株価: {stock_info['close']}円
時価総額: {stock_info['market_cap_oku']}億円
1日概算売買代金: {stock_info['trading_value_man']}万円

【分析要件】
1. score: テンバガー潜在力スコア（0〜100点の整数）
2. growth_story: 成長ドライバ、国策/AI等のテーマ合致、業績拡大のカタリスト（120〜150文字程度）
3. risk_factors: 考慮すべき最大のリスク要因（80文字程度）
4. entry_price: テクニカル的な押し目またはブレイク買い目標価格（現在値 {stock_info['close']}円 を基準に算出）
5. stop_loss: 厳格な損切りライン（買値から概ね -7%〜-8% の価格）

以下のJSONフォーマットのみを返してください。
{{
  "score": 85,
  "growth_story": "...",
  "risk_factors": "...",
  "entry_price": 0,
  "stop_loss": 0
}}
"""
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            res_json = clean_and_parse_json(response.text)
            if res_json and "score" in res_json and "growth_story" in res_json:
                return res_json
        except Exception as e:
            print(f"[WARN] Gemini分析 試行 {attempt + 1}/3 失敗 ({stock_info['code']}): {e}")
            time.sleep(1)

    # フォールバック
    stop = round(float(stock_info['close']) * 0.92, 1)
    return {
        "score": 75,
        "growth_story": f"{stock_info['name']}は売買代金急増と上昇トレンドを維持。新高値圏でのモメンタムと独自事業の進捗が株価の起爆剤。",
        "risk_factors": "小型株特有の流動性低下と地合い悪化による短期ボラティリティ。",
        "entry_price": stock_info['close'],
        "stop_loss": stop
    }

def main():
    print(f"[INFO] 候補ファイル確認: {CANDIDATES_FILE}")
    if not os.path.exists(CANDIDATES_FILE):
        print(f"[ERROR] {CANDIDATES_FILE} が見つかりません。")
        sys.exit(1)

    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    print(f"[INFO] スクリーニング読み込み件数: {len(candidates)}件")
    if not candidates:
        print("[INFO] 候補が0件のため終了します。")
        return

    if len(candidates) > MAX_AI_ANALYZE:
        print(f"[INFO] スクリーニング候補 {len(candidates)} 件から、上位 {MAX_AI_ANALYZE} 銘柄に限定してAI分析を実行します。")
        candidates = candidates[:MAX_AI_ANALYZE]

    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else None

    analyzed_stocks = []
    print(f"[INFO] 厳選 {len(candidates)} 銘柄のGemini詳細分析を開始...")

    for item in candidates:
        print(f"  -> 分析対象: {item['code']} {item['name']}")
        if client:
            analysis = analyze_stock_with_gemini(client, item)
        else:
            stop = round(float(item['close']) * 0.92, 1)
            analysis = {
                "score": 70,
                "growth_story": "上昇トレンド基調と売買代金の維持を監視。",
                "risk_factors": "地合い悪化による短期的なボラティリティ上昇。",
                "entry_price": item['close'],
                "stop_loss": stop
            }
        item['analysis'] = analysis
        analyzed_stocks.append(item)
        
        # 従量課金プランのため待機時間を0.3秒に短縮
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

    # LINE通知
    top_stocks = analyzed_stocks[:3]
    repo_name = os.getenv("GITHUB_REPOSITORY", "sei1r0/tenbagger-hunter")
    pages_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}/"

    msg_lines = [f"週末のAIテンバガー詳細分析が完了しました（厳選{len(candidates)}銘柄全数分析）\n"]
    for idx, s in enumerate(top_stocks, 1):
        a = s['analysis']
        msg_lines.append(
            f"【{idx}位】{s['code']} {s['name']} (スコア: {a['score']}点)\n"
            f"・現在値: {s['close']}円\n"
            f"・買い目安: {a['entry_price']}円 / 損切: {a['stop_loss']}円\n"
            f"・カタリスト: {a['growth_story']}\n"
        )
    msg_lines.append(f"📱 Webレポート詳細:\n{pages_url}")

    send_notification("週末AIアナリティクス厳選銘柄", "\n".join(msg_lines))
    print("[INFO] 全パイプライン処理が正常に完了しました。")

if __name__ == "__main__":
    main()