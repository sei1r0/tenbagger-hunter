import os
import sys
import json
import time
import datetime

# パス解決（リポジトリルートを検索パスに追加）
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from google import genai
from jinja2 import Environment, FileSystemLoader
from src.utils.notifier import send_notification

CANDIDATES_FILE = os.path.join(PROJECT_ROOT, "data", "screened_candidates.json")
OUTPUT_HTML_DIR = os.path.join(PROJECT_ROOT, "docs")
OUTPUT_HTML_PATH = os.path.join(OUTPUT_HTML_DIR, "index.html")

def analyze_stock_with_gemini(client, stock_info):
    """Gemini API を使用して成長ストーリーとリスクリワードを多角分析"""
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
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"[WARN] Gemini分析エラー ({stock_info['code']}): {e}")
        stop = round(stock_info['close'] * 0.92, 1)
        return {
            "score": 50,
            "growth_story": "事業データ取得中。業績成長性と売買代金の推移に注目。",
            "risk_factors": "新興市場全体の地合い悪化および流動性低下リスク。",
            "entry_price": stock_info['close'],
            "stop_loss": stop
        }

def main():
    print(f"[INFO] 候補ファイル確認: {CANDIDATES_FILE}")
    if not os.path.exists(CANDIDATES_FILE):
        print(f"[ERROR] {CANDIDATES_FILE} が存在しません。")
        sys.exit(1)

    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    print(f"[INFO] 読み込み件数: {len(candidates)}件")
    if not candidates:
        print("[INFO] スクリーニング済み候補が0件のため終了します。")
        return

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY が未設定です。")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    analyzed_stocks = []

    print(f"[INFO] 候補 {len(candidates)} 銘柄の Gemini 詳細分析を開始...")
    for item in candidates:
        print(f"  -> 分析中: {item['code']} {item['name']}")
        analysis = analyze_stock_with_gemini(client, item)
        item['analysis'] = analysis
        analyzed_stocks.append(item)
        time.sleep(1.0)

    analyzed_stocks.sort(key=lambda x: x['analysis']['score'], reverse=True)

    # HTMLレポート生成
    os.makedirs(OUTPUT_HTML_DIR, exist_ok=True)
    template_dir = os.path.join(CURRENT_DIR, "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("report.html")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html_output = template.render(
        generated_at=now_str,
        total_screened=len(candidates),
        analyzed_stocks=analyzed_stocks
    )

    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_output)
    print(f"[INFO] レポートを出力しました: {OUTPUT_HTML_PATH}")

    # LINE通知送信
    top_stocks = analyzed_stocks[:3]
    repo_name = os.getenv("GITHUB_REPOSITORY", "")
    pages_url = ""
    if repo_name:
        user_name, repo = repo_name.split("/")
        pages_url = f"https://{user_name}.github.io/{repo}/"

    msg_lines = ["週末のAIテンバガー詳細分析が完了しました（上位厳選銘柄）\n"]
    for idx, s in enumerate(top_stocks, 1):
        a = s['analysis']
        msg_lines.append(
            f"【{idx}位】{s['code']} {s['name']} (スコア: {a['score']}点)\n"
            f"・現在値: {s['close']}円\n"
            f"・買い目安: {a['entry_price']}円 / 損切: {a['stop_loss']}円\n"
            f"・カタリスト: {a['growth_story']}\n"
        )

    if pages_url:
        msg_lines.append(f"📱 Webレポート詳細:\n{pages_url}")

    send_notification("週末AIアナリティクス厳選銘柄", "\n".join(msg_lines))
    print("[INFO] LINE通知処理が完了しました。")

if __name__ == "__main__":
    main()