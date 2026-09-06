import os
import sys
import json
import re
import time
import yfinance as yf
from google import genai

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from src.utils.market_calendar import guard_tokyo_market, is_us_market_open_prev_day
    from src.utils.notifier import send_notification, send_daily_gate_flex
except ModuleNotFoundError:
    from utils.market_calendar import guard_tokyo_market, is_us_market_open_prev_day
    from utils.notifier import send_notification, send_daily_gate_flex

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
    """週末厳選20銘柄の最新株価・移動平均をリアルタイム取得し、エントリー機会および下降トレンド・手仕舞い警告を抽出"""
    if not os.path.exists(CANDIDATES_FILE):
        return [], []

    try:
        with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
            candidates = json.load(f)
    except Exception:
        return [], []

    if not candidates:
        return [], []

    top_candidates = candidates[:10]
    tickers = [f"{s['code']}.T" for s in top_candidates if "code" in s]

    # 直近1ヶ月の日足株価を取得（最新終値、5MA、25MA、デッドクロス判定用）
    latest_data = {}
    try:
        data = yf.download(tickers=tickers, period="1mo", interval="1d", group_by="ticker", auto_adjust=True, progress=False)
        for s in top_candidates:
            sym = f"{s['code']}.T"
            try:
                if len(tickers) == 1:
                    df = data.dropna()
                else:
                    df = data[sym].dropna()
                if not df.empty and len(df) >= 5:
                    closes = df["Close"]
                    sma5_series = closes.rolling(window=5).mean()
                    sma25_series = closes.rolling(window=min(25, len(closes))).mean()

                    curr_p = float(closes.iloc[-1])
                    sma5_val = float(sma5_series.iloc[-1])
                    sma25_val = float(sma25_series.iloc[-1])

                    # デッドクロス検知 (直近3日以内に 5MA が 25MA を下抜け)
                    is_dc = False
                    if len(closes) >= 10:
                        diff = sma5_series - sma25_series
                        if diff.iloc[-1] < 0 and (diff.iloc[-4:] >= 0).any():
                            is_dc = True

                    latest_data[s['code']] = {
                        "price": curr_p,
                        "sma5": sma5_val,
                        "sma25": sma25_val,
                        "is_dc": is_dc
                    }
            except Exception:
                pass
    except Exception as e:
        print(f"[WARN] リアルタイム監視株価の取得スキップ: {e}")

    risk_alerts = []
    entry_alerts = []

    for s in top_candidates:
        code = s.get("code")
        name = s.get("name")
        stock_item = latest_data.get(code, {})
        curr_price = stock_item.get("price", float(s.get("close", 0)))
        sma25 = stock_item.get("sma25", float(s.get("sma25", 0)))
        is_dc = stock_item.get("is_dc", False)

        analysis = s.get("analysis", {})
        tier = analysis.get("conviction_tier", "A")
        tier_icon = "👑" if tier == "S" else ("⭐" if tier == "A" else "📌")

        entry_price = float(analysis.get("entry_price", 0))
        stop_loss = float(analysis.get("stop_loss", 0))
        is_vcp = s.get("is_vcp", False)

        # --- 1. 下降トレンド転落・手仕舞い・リスク警戒 ---
        # 決算直前トラップ警戒（発表まで10日以内）
        is_earnings_imminent = s.get("is_earnings_imminent", False)
        days_to_earnings = s.get("days_to_earnings")
        if is_earnings_imminent:
            days_str = f"あと{days_to_earnings}日" if days_to_earnings is not None else "直前"
            risk_alerts.append(
                f"⚠️ 決算直前: {code} {name} (発表{days_str}・ガチャ回避・通過後エントリー推奨)"
            )

        # A. 損切りライン到達（即時撤退）
        if stop_loss > 0 and curr_price <= stop_loss:
            risk_alerts.append(
                f"🚨 損切執行: {code} {name} (現在:{curr_price}円 <= 損切:{stop_loss}円 即時撤退)"
            )
        # B. 損切りライン接近 (+2%以内)
        elif stop_loss > 0 and curr_price <= (stop_loss * 1.02):
            risk_alerts.append(
                f"⚠️ 損切警戒: {code} {name} (現在:{curr_price}円 / 損切:{stop_loss}円に接近)"
            )
        # C. 25日線サポート割れ (明確な下降転落)
        elif sma25 > 0 and curr_price < (sma25 * 0.985):
            risk_alerts.append(
                f"📉 25MA割れ: {code} {name} (現在:{curr_price}円 < 25MA:{sma25}円 下降転落)"
            )
        # D. デッドクロス点灯 (5MA x 25MA)
        elif is_dc:
            risk_alerts.append(
                f"💀 デッドクロス: {code} {name} (5MA×25MA下抜け・短期利確推奨)"
            )

        # --- 2. 買い・押し目エントリー機会 ---
        # A. 買値目安（押し目・ブレイク）接近 (目安価格の ±2.5% 以内)
        if entry_price > 0 and abs(curr_price - entry_price) / entry_price <= 0.025:
            entry_alerts.append(
                f"🎯 買値圏: {tier_icon}{code} {name} (現在:{curr_price}円 / 目安:{entry_price}円)"
            )
        # B. 25日線タッチ・押し目反発ゾーン (25MAの +0.5%〜+2.5%)
        elif sma25 > 0 and 0.005 <= (curr_price - sma25) / sma25 <= 0.025:
            entry_alerts.append(
                f"📈 25MA押し目: {tier_icon}{code} {name} (現在:{curr_price}円 / 25MA:{sma25}円)"
            )
        # C. VCP売り枯れ初動トリガー
        elif is_vcp:
            entry_alerts.append(
                f"🔥 VCP初動: {tier_icon}{code} {name} (RS:+{s.get('rs_rating',0)}% / {curr_price}円)"
            )

    return risk_alerts, entry_alerts

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
            model="gemini-3.6-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        match = re.search(r"\{.*\}", response.text, flags=re.DOTALL)
        if match:
            res_json = json.loads(match.group(0))
        else:
            cleaned = re.sub(r"^```(?:json)?\s*", "", response.text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
            res_json = json.loads(cleaned)
    except Exception as e:
        res_json = {
            "status": "YELLOW",
            "reason": f"AI判定モジュール異常のため警戒モードへフォールバック: {type(e).__name__}",
            "action_guideline": "新規指値は控えめに設定してください。"
        }

    # 5. ウォッチリストのトリガー判定（買い機会 ＆ 下降・手仕舞い警告）
    risk_alerts, entry_alerts = check_watchlist_action_triggers()

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

    action_sections = []
    if risk_alerts:
        action_sections.append("【⚠️ 厳重警戒・手仕舞いシグナル】\n" + "\n".join(risk_alerts[:4]))
    if entry_alerts:
        action_sections.append("【🎯 買値圏・押し目エントリー機会】\n" + "\n".join(entry_alerts[:4]))

    if action_sections:
        body += "\n\n" + "\n\n".join(action_sections)

    # Flex メッセージ送信（失敗時はテキスト通知へフォールバック）
    pages_url = os.getenv("PAGES_URL", "https://sei1r0.github.io/tenbagger-hunter/")
    sent_flex = send_daily_gate_flex(
        status=status,
        reason=res_json.get("reason", ""),
        action_guideline=res_json.get("action_guideline", ""),
        market_snapshot=market_snapshot,
        risk_alerts=risk_alerts,
        entry_alerts=entry_alerts,
        pages_url=pages_url
    )
    if not sent_flex:
        send_notification(title="朝の地合いゲート判定", message=body, color_level=status)
    print("日次地合い判定およびウォッチリスト追跡が正常に完了し、通知処理を実行しました。")

if __name__ == "__main__":
    main()