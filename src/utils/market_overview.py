import datetime
import yfinance as yf

TARGET_INDICES = [
    {"name": "S&P500", "ticker": "^GSPC", "format": "{:,.1f}"},
    {"name": "FANG+", "ticker": "FNGS", "format": "{:,.2f}"},
    {"name": "オルカン", "ticker": "ACWI", "format": "{:,.2f}"},
    {"name": "金先物", "ticker": "GC=F", "format": "{:,.1f}"},
    {"name": "ドル円", "ticker": "USDJPY=X", "format": "{:,.2f}"}
]

def fetch_market_indices():
    """主要5指数の終値・週差・年初来差を算出"""
    current_year = datetime.date.today().year
    start_of_year = f"{current_year}-01-01"

    results = []

    for item in TARGET_INDICES:
        name = item["name"]
        ticker = item["ticker"]
        fmt = item["format"]

        try:
            t = yf.Ticker(ticker)
            # 年初からの日足を取得
            df = t.history(start=start_of_year)
            if df.empty or len(df) < 2:
                continue

            closes = df["Close"]
            curr_val = float(closes.iloc[-1])

            # 週差（前週の同じ曜日＝約5営業日前、足りない場合は最古データ）
            prev_week_val = float(closes.iloc[-6]) if len(closes) >= 6 else float(closes.iloc[0])
            week_diff = curr_val - prev_week_val
            week_pct = (week_diff / prev_week_val) * 100

            # 年初差（年初第1営業日の終値）
            ytd_start_val = float(closes.iloc[0])
            ytd_diff = curr_val - ytd_start_val
            ytd_pct = (ytd_diff / ytd_start_val) * 100

            results.append({
                "name": name,
                "current": curr_val,
                "current_str": fmt.format(curr_val),
                "week_diff": week_diff,
                "week_diff_str": fmt.format(week_diff),
                "week_pct": round(week_pct, 2),
                "ytd_diff": ytd_diff,
                "ytd_diff_str": fmt.format(ytd_diff),
                "ytd_pct": round(ytd_pct, 2)
            })
        except Exception as e:
            print(f"[WARN] 指数取得失敗 ({name}): {e}")
            continue

    return results