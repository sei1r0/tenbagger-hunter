import os
import sys
import json
import time
import yfinance as yf
from google import genai
from utils.market_calendar import guard_tokyo_market, is_us_market_open_prev_day
from utils.notifier import send_notification

def fetch_market_data(ticker_symbol: str, retries=3):
    """レート制限回避のリトライ機構付きデータ取得"""
    for i in range(retries):
        try:
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="5d")
            if len(hist) >= 2:
                latest = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2]
                pct_change = ((latest - prev) / prev) * 100
                return {"close": round(latest, 2), "pct_change": round(pct_change, 2)}
            time.sleep(1)
        except Exception:
            time.sleep(2 ** i)
    return {"close": None, "pct_change": 0.0}

def main():
    # 1. 日本市場の開場判定（★テストのため一時的にコメントアウト）
    # guard_tokyo_market()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY が設定されていません。")
        sys.exit(1)

    # 新SDK Clientの初期化
    client = genai.Client(api_key=api_key)

    # 2. 米国市場休場フラグの確認
    us_open = is_us_market_open_prev_day()

    # 3. 主要マクロデータの取得
    symbols = {
        "Nasdaq": "^IXIC",
        "S&P500": "^GSPC",
        "Russell2000": "^RUT",
        "US_10Y_Yield": "^TNX",
        "USD_JPY": "JPY=X"
    }
    
    market_snapshot = {}
    for name, sym in symbols.items():
        market_snapshot[name] = fetch_market_data(sym)

    # 4. Gemini プロンプト構築
    us_status_text = "前夜の米国市場は通常取引でした。" if us_open else "【注】前夜の米国市場は祝日休場でした。為替や先物動向を重視してください。"

    prompt = f"""
あなたは中小型成長株（テンバガー）投資の「リスクゲートキーパー」です。
以下の直近マクロ指標と米国市場ステータスに基づき、本日の東京市場（グロース・新興株）における「買いエントリー可否」を判定してください。

【米国市場状況】: {us_status_text}
【指標データ】:
{json.dumps(market_snapshot, indent=2, ensure_ascii=False)}

【判定基準】
- GREEN（🟢）: リスクオン。新規買いエントリーを積極的に許可。
- YELLOW（🟡）: 警戒局面。米金利急騰または為替急変動。エントリーは通常ロットの50%以下に制限。
- RED（🔴）: リスクオフ。ナスダック・中小型株指数急落、ショック相場。新規買いは全面禁止。

以下のJSONフォーマットのみを返してください。
{{
  "status": "GREEN" または "YELLOW" または "RED",
  "reason": "120文字以内で理由を明瞭に説明",
  "action_guideline": "本日の具体的な行動方針（指値の扱い等）"
}}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        res_json = json.loads(response.text)
    except Exception as e:
        res_json = {
            "status": "YELLOW",
            "reason": f"AI判定モジュール異常のため警戒モードへフォールバック: {type(e).__name__}",
            "action_guideline": "新規指値は控えめに設定してください。"
        }

    # 5. 結果の通知送信
    status = res_json.get("status", "YELLOW")
    status_emoji = {"GREEN": "🟢 リスクオン（買付可）", "YELLOW": "🟡 警戒（ロット半減）", "RED": "🔴 リスクオフ（新規買停止）"}
    
    body = (
        f"判定: {status_emoji.get(status, status)}\n"
        f"理由: {res_json.get('reason')}\n"
        f"方針: {res_json.get('action_guideline')}\n\n"
        f"主要データ:\n"
        f"・Nasdaq: {market_snapshot['Nasdaq']['pct_change']}%\n"
        f"・ラッセル2000: {market_snapshot['Russell2000']['pct_change']}%\n"
        f"・米10年金利: {market_snapshot['US_10Y_Yield']['close']}%\n"
        f"・ドル円: {market_snapshot['USD_JPY']['close']}円"
    )

    send_notification(title="朝の地合いゲート判定", message=body, color_level=status)
    print("日次地合い判定が正常に完了し、通知処理を実行しました。")

if __name__ == "__main__":
    main()