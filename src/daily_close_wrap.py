import os
import sys
import json
import yfinance as yf
import pandas as pd
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.utils.market_calendar import guard_tokyo_market, get_jst_now
from src.utils.notifier import send_notification, send_close_wrap_flex
from src.utils.track_record import calculate_track_record

CANDIDATES_FILE = os.path.join(PROJECT_ROOT, "data", "screened_candidates.json")

def run_daily_close_wrap():
    # 1. 日本市場の開場判定（祝日・休日は即終了）
    guard_tokyo_market()

    print("[INFO] 本日の東証大引け（15:00）レビューを開始します...")
    if not os.path.exists(CANDIDATES_FILE):
        print(f"[WARN] 監視銘柄ファイル ({CANDIDATES_FILE}) が存在しません。終了します。")
        return

    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        watchlist = json.load(f)

    if not watchlist:
        print("[INFO] 監視銘柄が0件のため終了します。")
        return

    codes = [s["code"] for s in watchlist]
    tickers = [f"{c}.T" for c in codes]

    print(f"[INFO] 監視 {len(codes)} 銘柄の当日大引けデータを取得中...")
    stock_results = []

    try:
        data = yf.download(
            tickers=tickers,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True
        )
    except Exception as e:
        print(f"[ERROR] 当日株価取得エラー: {e}")
        return

    breakout_alerts = []
    stop_alerts = []
    rebound_alerts = []

    for s in watchlist:
        code = s["code"]
        name = s["name"]
        sym = f"{code}.T"
        analysis = s.get("analysis", {})
        tier = analysis.get("conviction_tier", "A")
        tier_icon = "👑" if tier == "S" else ("⭐" if tier == "A" else "📌")

        entry_price = float(analysis.get("entry_price", 0))
        stop_loss = float(analysis.get("stop_loss", 0))
        sma25 = float(s.get("sma25", 0))

        try:
            if len(tickers) == 1:
                df = data.dropna()
            else:
                if sym not in data.columns.levels[0]:
                    continue
                df = data[sym].dropna()

            if len(df) < 2:
                continue

            curr_close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            day_high = float(df["High"].iloc[-1])
            day_low = float(df["Low"].iloc[-1])
            day_pct = round(((curr_close - prev_close) / max(prev_close, 1)) * 100, 2)

            stock_results.append({
                "code": code,
                "name": name,
                "tier_icon": tier_icon,
                "close": curr_close,
                "day_pct": day_pct,
                "day_high": day_high,
                "day_low": day_low
            })

            # 1. 損切り確定
            if stop_loss > 0 and curr_close <= stop_loss:
                stop_alerts.append(f"🚨 損切確定: {code} {name} (終値:{curr_close}円 <= 損切:{stop_loss}円 即手仕舞い)")
            elif stop_loss > 0 and curr_close <= (stop_loss * 1.02):
                stop_alerts.append(f"⚠️ 損切寸前: {code} {name} (終値:{curr_close}円 / 損切:{stop_loss}円に接近)")

            # 2. 買値目安到達・ブレイクアウト達成
            if entry_price > 0 and curr_close >= entry_price and prev_close < entry_price:
                breakout_alerts.append(f"🎯 目安上抜け: {tier_icon}{code} {name} (終値:{curr_close}円 >= 目安:{entry_price}円)")
            elif entry_price > 0 and abs(curr_close - entry_price) / entry_price <= 0.015:
                breakout_alerts.append(f"🎯 買値圏引け: {tier_icon}{code} {name} (終値:{curr_close}円 / 目安:{entry_price}円)")

            # 3. 25MA反発確認
            if sma25 > 0 and day_low <= sma25 and curr_close > sma25:
                rebound_alerts.append(f"📈 25MA反発: {tier_icon}{code} {name} (安値:{day_low}円 -> 終値:{curr_close}円 / 25MA:{sma25}円)")

        except Exception as e:
            print(f"[WARN] 銘柄処理エラー ({code}): {e}")

    # 騰落率順にソート
    stock_results.sort(key=lambda x: x["day_pct"], reverse=True)

    # メッセージ構築
    now_str = get_jst_now().strftime("%m/%d %H:%M")
    lines = [
        f"🌆【東証大引けレビュー ({now_str} JST)】",
        "本日の監視銘柄の値動きと手仕舞い・ブレイク判定です。\n"
    ]

    if stop_alerts:
        lines.append("【🚨 手仕舞い・損切確定アラート】")
        lines.extend(stop_alerts)
        lines.append("")

    if breakout_alerts:
        lines.append("【🎯 買値目安・ブレイク達成】")
        lines.extend(breakout_alerts)
        lines.append("")

    if rebound_alerts:
        lines.append("【📈 25MA押し目反発確認】")
        lines.extend(rebound_alerts)
        lines.append("")

    lines.append("【📊 本日の監視銘柄 騰落ランキング】")
    for r in stock_results[:8]: # 上位8件
        sign = "+" if r["day_pct"] > 0 else ""
        lines.append(f"・{r['tier_icon']}{r['code']} {r['name']}: {sign}{r['day_pct']}% ({r['close']}円)")

    # LINE通知（Flex Message ＋ テキストフォールバック）
    repo_name = os.getenv("GITHUB_REPOSITORY", "sei1r0/tenbagger-hunter")
    pages_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}/"

    send_close_wrap_flex(now_str, stock_results, stop_alerts, breakout_alerts, rebound_alerts, pages_url)
    
    # トラックレコード最新値（勝率・最高値更新・損益ステータス）の日次更新 ＆ ダッシュボードHTML再描画
    try:
        updated_tr = calculate_track_record()
        from src.agent_analyst import render_report_html
        render_report_html(track_record=updated_tr)
        print("[INFO] トラックレコード日次自動集計 & index.html 再描画完了。")
    except Exception as e:
        print(f"[WARN] トラックレコード/HTML更新エラー: {e}")

    print("[INFO] 大引けレビュー配信完了。")

if __name__ == "__main__":
    run_daily_close_wrap()
