import os
import sys
import json
import time
import yfinance as yf
from google import genai

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from src.utils.market_calendar import guard_tokyo_market, is_us_market_open_prev_day
    from src.utils.notifier import send_notification
except ModuleNotFoundError:
    from utils.market_calendar import guard_tokyo_market, is_us_market_open_prev_day
    from utils.notifier import send_notification

CANDIDATES_FILE = os.path.join(PROJECT_ROOT, "data", "screened_candidates.json")

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

def check_watchlist_action_triggers():
    """週末厳選20銘柄の価格動向をチェックし、本日のエントリー・警戒シグナルを抽出"""
    if not os.path.exists(CANDIDATES_FILE):
        return []

    try:
        with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
            candidates = json.load(f)
    except Exception:
        return []

    if not candidates:
        return []

    action_alerts = []

    for s in candidates[:10]:
        code = s.get("code")
        name = s.get("name")
        curr_price = float(s.get("close", 0))
        analysis = s.get("analysis", {})
        tier = analysis.get("conviction_tier", "A")
        tier_icon = "👑" if tier == "S" else ("⭐" if tier == "A" else "📌")

        entry_price = float(analysis.get("entry_price", 0))
        stop_loss = float(analysis.get("stop_loss", 0))
        is_vcp = s.get("is_vcp", False)

        # 1. 買値目安（押し目・ブレイク）接近トリガー (目安価格の ±2.5% 以内)
        if entry_price > 0 and abs(curr_price - entry_price) / entry_price <= 0.025:
            action_alerts.append(
                f"🎯 買値圏: {tier_icon}{code} {name} (値:{curr_price}円 / 目安:{entry_price}円)"
            )
        # 2. VCP売り枯れ初動トリガー
        elif is_vcp:
            action_alerts.append(
                f"🔥 VCP初動: {tier_icon}{code} {name} (RS:+{s.get('rs_rating',0)}% / {curr_price}円)"
            )
        # 3. 損切り警戒トリガー (損切りラインから +2% 未満に接近)
        elif stop_loss > 0 and curr_price <= (stop_loss * 1.02):
            action_alerts.append(
                f"⚠️ 損切警戒: {code} {name} (値:{curr_price}円 / 損切:{stop_loss}円)"
            )

    return action_alerts

def main():
    # 1. 日本市場の開場判定
    guard_tokyo_market()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY が設定されていません。")
        sys.exit(1)

    # Clientの初期化
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

    # 5. ウォッチリストのトリガー判定
    watchlist_alerts = check_watchlist_action_triggers()

    # 6. 結果の通知送信
    status = res_json.get("status", "YELLOW")
    status_emoji = {"GREEN": "🟢 リスクオン（買付可）", "YELLOW": "🟡 警戒（ロット半減）", "RED": "🔴 リスクオフ（新規買停止）"}
    
    nasdaq_pct = market_snapshot['Nasdaq']['pct_change']
    sp500_pct = market_snapshot['S&P500']['pct_change']
    russell_pct = market_snapshot['Russell2000']['pct_change']
    nasdaq_sign = "+" if nasdaq_pct > 0 else ""
    sp500_sign = "+" if sp500_pct > 0 else ""
    russell_sign = "+" if russell_pct > 0 else ""

    body = (
        f"判定: {status_emoji.get(status, status)}\n"
        f"理由: {res_json.get('reason')}\n"
        f"方針: {res_json.get('action_guideline')}\n\n"
        f"主要データ（前日比・水準）:\n"
        f"・🇺🇸 Nasdaq (米ハイテク): {nasdaq_sign}{nasdaq_pct}%\n"
        f"・🇺🇸 S&P500: {sp500_sign}{sp500_pct}%\n"
        f"・🇺🇸 ラッセル2000 (米中小型株): {russell_sign}{russell_pct}%\n"
        f"・🏛️ 米10年国債利回り: {market_snapshot['US_10Y_Yield']['close']}%\n"
        f"・💴 ドル円為替: {market_snapshot['USD_JPY']['close']}円"
    )

    if watchlist_alerts:
        body += "\n\n【🎯 本日の厳選監視アクション】\n" + "\n".join(watchlist_alerts[:5])

    send_notification(title="朝の地合いゲート判定", message=body, color_level=status)
    print("日次地合い判定およびウォッチリスト追跡が正常に完了し、通知処理を実行しました。")

if __name__ == "__main__":
    main()