import datetime
import yfinance as yf

TARGET_INDICES = [
    {
        "name": "日経平均",
        "desc": "東証主力 (^N225)",
        "ticker": "^N225",
        "unit": "円",
        "prefix": "",
        "format": "{:,.1f}",
        "icon": "🇯🇵"
    },
    {
        "name": "グロース250",
        "desc": "東証新興250 (ETF:2516)",
        "ticker": "2516.T",
        "unit": "円",
        "prefix": "",
        "format": "{:,.1f}",
        "icon": "🌱"
    },
    {
        "name": "S&P500",
        "desc": "米国主要500社株価指数",
        "ticker": "^GSPC",
        "unit": "pt",
        "prefix": "",
        "format": "{:,.1f}",
        "icon": "🇺🇸"
    },
    {
        "name": "ナスダック100",
        "desc": "米ハイテク主要100社 (^NDX)",
        "ticker": "^NDX",
        "unit": "pt",
        "prefix": "",
        "format": "{:,.1f}",
        "icon": "💻"
    },
    {
        "name": "FANG+",
        "desc": "米メガテック10社 (ETF:FNGS)",
        "ticker": "FNGS",
        "unit": "",
        "prefix": "$",
        "format": "{:,.2f}",
        "icon": "🚀"
    },
    {
        "name": "オルカン",
        "desc": "全世界株式 (ETF:ACWI)",
        "ticker": "ACWI",
        "unit": "",
        "prefix": "$",
        "format": "{:,.2f}",
        "icon": "🌍"
    },
    {
        "name": "金先物",
        "desc": "ゴールド/安全資産 (COMEX)",
        "ticker": "GC=F",
        "unit": "",
        "prefix": "$",
        "format": "{:,.1f}",
        "icon": "🥇"
    },
    {
        "name": "ドル円",
        "desc": "為替レート (USD/JPY)",
        "ticker": "USDJPY=X",
        "unit": "円",
        "prefix": "",
        "format": "{:,.2f}",
        "icon": "💴"
    }
]

def format_val_with_unit(val: float, fmt: str, prefix: str, unit: str, sign: bool = False) -> str:
    s = fmt.format(abs(val))
    prefix_str = f"{prefix}{s}" if prefix else (f"{s} {unit}" if unit else s)
    if sign:
        sign_char = "+" if val > 0 else ("-" if val < 0 else "")
        return f"{sign_char}{prefix_str}"
    return prefix_str

def fetch_market_indices():
    """主要5指数の終値・週差・年初来差を算出"""
    current_year = datetime.date.today().year
    start_of_year = f"{current_year}-01-01"

    results = []

    for item in TARGET_INDICES:
        name = item["name"]
        desc = item["desc"]
        ticker = item["ticker"]
        fmt = item["format"]
        unit = item.get("unit", "")
        prefix = item.get("prefix", "")
        icon = item.get("icon", "📌")

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

            display_val = format_val_with_unit(curr_val, fmt, prefix, unit)
            display_week_diff = format_val_with_unit(week_diff, fmt, prefix, unit, sign=True)
            display_ytd_diff = format_val_with_unit(ytd_diff, fmt, prefix, unit, sign=True)

            results.append({
                "name": name,
                "desc": desc,
                "icon": icon,
                "unit": unit,
                "prefix": prefix,
                "current": curr_val,
                "current_str": fmt.format(curr_val),
                "display_val": display_val,
                "week_diff": week_diff,
                "week_diff_str": fmt.format(week_diff),
                "display_week_diff": display_week_diff,
                "week_pct": round(week_pct, 2),
                "ytd_diff": ytd_diff,
                "ytd_diff_str": fmt.format(ytd_diff),
                "display_ytd_diff": display_ytd_diff,
                "ytd_pct": round(ytd_pct, 2)
            })
        except Exception as e:
            print(f"[WARN] 指数取得失敗 ({name}): {e}")
            continue

    return results