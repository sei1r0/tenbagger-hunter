import os
import sys
import json
import time
import pandas as pd
import yfinance as yf
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.notifier import send_notification

STOCKS_CSV = os.path.join(PROJECT_ROOT, "data", "jpx_stocks.csv")
OUTPUT_JSON = os.path.join(PROJECT_ROOT, "data", "screened_candidates.json")

# 厳選スクリーニング基準
MIN_PRICE = 200                # 最低株価 200円以上（超低位株・ボロ株トラップ排除）
MAX_MARKET_CAP_OKU = 300       # 時価総額 300億円以下（テンバガーポテンシャル）
MIN_TRADING_VALUE_MAN = 5000   # 1日売買代金 5,000万円以上
MAX_SMA25_DEVIATION = 0.25     # 25日線上方乖離率 25%以内（高値掴み・過熱イナゴ排除）
MIN_SMA25_DEVIATION = 0.00     # 25日線上方乖離率 0%以上（25MAタッチ押し目〜初動を完全網羅）
BATCH_SIZE = 50                # yfinance API安定化バッチサイズ
TARGET_POOL_LIMIT = 20         # 厳選上位20銘柄に絞り込み
BENCHMARK_TICKER = "2516.T"    # 東証グロース250 ETF（RS相対力ベンチマーク）

def get_prev_screened_codes():
    if os.path.exists(OUTPUT_JSON):
        try:
            with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
                return set([item["code"] for item in prev_data])
        except Exception:
            return set()
    return set()

def calculate_up_down_volume_ratio(df_window):
    """直近20日間の上昇日出来高と下落日出来高の比率（大口買い集め度）を算出"""
    try:
        price_diff = df_window["Close"].diff()
        up_vols = df_window["Volume"][price_diff > 0].sum()
        down_vols = df_window["Volume"][price_diff < 0].sum()
        if down_vols == 0:
            return 2.0
        return round(float(up_vols / down_vols), 2)
    except Exception:
        return 1.0

def fetch_benchmark_return_60d():
    """グロース250指数の直近60営業日リターンを算出"""
    try:
        t = yf.Ticker(BENCHMARK_TICKER)
        hist = t.history(period="6mo")
        if len(hist) >= 60:
            start_p = float(hist["Close"].iloc[-60])
            curr_p = float(hist["Close"].iloc[-1])
            return ((curr_p - start_p) / start_p) * 100
        elif len(hist) >= 2:
            start_p = float(hist["Close"].iloc[0])
            curr_p = float(hist["Close"].iloc[-1])
            return ((curr_p - start_p) / start_p) * 100
    except Exception as e:
        print(f"[WARN] ベンチマーク取得失敗 ({BENCHMARK_TICKER}): {e}")
    return 0.0

def run_batch_screener():
    start_time = time.time()
    if not os.path.exists(STOCKS_CSV):
        print(f"[ERROR] {STOCKS_CSV} が見つかりません。")
        sys.exit(1)

    prev_codes = get_prev_screened_codes()

    # RS（Relative Strength）の基準となるグロース市場リターンを取得
    benchmark_return_60d = fetch_benchmark_return_60d()
    print(f"[INFO] グロース市場ベンチマーク60日リターン: {round(benchmark_return_60d, 2)}%")

    df_stocks = pd.read_csv(STOCKS_CSV, dtype={"code": str})
    df_stocks = df_stocks[df_stocks["market"].isin(["グロース", "スタンダード"])].copy()
    
    total_count = len(df_stocks)
    print(f"[INFO] 成長市場（グロース・スタンダード）{total_count} 銘柄の高精度スクリーニングを開始...")

    stock_dict = {f"{row['code']}.T": row for _, row in df_stocks.iterrows()}
    tickers = list(stock_dict.keys())

    candidates = []

    for i in range(0, total_count, BATCH_SIZE):
        batch_tickers = tickers[i : i + BATCH_SIZE]
        print(f"[INFO] 分析中: {i + 1}〜{min(i + BATCH_SIZE, total_count)} / {total_count}")

        try:
            data = yf.download(
                tickers=batch_tickers,
                period="1y",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True
            )
        except Exception as e:
            print(f"[WARN] バッチ取得エラー: {e}")
            continue

        for ticker_symbol in batch_tickers:
            row_meta = stock_dict[ticker_symbol]
            try:
                if len(batch_tickers) == 1:
                    df = data.dropna()
                else:
                    if ticker_symbol not in data.columns.levels[0]:
                        continue
                    df = data[ticker_symbol].dropna()

                # 200日移動平均線計算のため最低150本以上のデータを要求
                if len(df) < 150:
                    continue

                closes = df["Close"]
                volumes = df["Volume"]

                curr_close = float(closes.iloc[-1])
                curr_vol = float(volumes.iloc[-1])

                # フィルター1: 最低株価（低位株排除）
                if curr_close < MIN_PRICE:
                    continue

                # フィルター2: 売買代金 5,000万円以上
                trading_value_man = round((curr_close * curr_vol) / 10000, 1)
                if trading_value_man < MIN_TRADING_VALUE_MAN:
                    continue

                sma25 = float(closes.rolling(window=25).mean().iloc[-1])
                sma75 = float(closes.rolling(window=75).mean().iloc[-1])
                sma200 = float(closes.rolling(window=min(200, len(closes))).mean().iloc[-1])

                # フィルター3: パーフェクトオーダー（株価 > 25MA > 75MA かつ 株価 > 200MA）
                if not (curr_close > sma25 and sma25 > sma75 and curr_close > sma200):
                    continue

                # フィルター4: 25日線乖離率（高値掴みイナゴ排除 & 25MAタッチ押し目を許容）
                deviation_25 = (curr_close - sma25) / sma25
                if not (MIN_SMA25_DEVIATION <= deviation_25 <= MAX_SMA25_DEVIATION):
                    continue

                # フィルター5: 52週高値から15%以内（高値ブレイクアウト圏）
                high_52w = float(closes.max())
                if curr_close < (high_52w * 0.85):
                    continue

                # 時価総額・ファンダメンタルズ取得
                market_cap = 0
                rev_growth_pct = 0.0
                op_margin_pct = 0.0
                insider_held_pct = 0.0
                psr = None
                trailing_pe = None
                business_summary = ""

                try:
                    t = yf.Ticker(ticker_symbol)
                    fast = getattr(t, "fast_info", None)
                    if fast and hasattr(fast, "market_cap") and fast.market_cap:
                        market_cap = fast.market_cap

                    info = t.info or {}
                    if not market_cap:
                        market_cap = info.get("marketCap", 0)

                    # 売上高成長率
                    rev_growth = info.get("revenueGrowth", None)
                    if rev_growth is not None:
                        rev_growth_pct = round(rev_growth * 100, 1)

                    # 営業利益率
                    op_margin = info.get("operatingMargins", None)
                    if op_margin is not None:
                        op_margin_pct = round(op_margin * 100, 1)

                    # 創業者・役員保有比率 (Insiders Ownership)
                    insider_held = info.get("heldPercentInsiders", None)
                    if insider_held is not None:
                        insider_held_pct = round(float(insider_held) * 100, 1)

                    # PER
                    pe_val = info.get("trailingPE", None)
                    if pe_val is not None and float(pe_val) > 0:
                        trailing_pe = round(float(pe_val), 1)

                    # PSR
                    psr_val = info.get("priceToSalesTrailing12Months", None)
                    if psr_val is not None and float(psr_val) > 0:
                        psr = round(float(psr_val), 1)

                    # 企業公式概要
                    raw_summary = info.get("longBusinessSummary") or info.get("businessSummary") or ""
                    business_summary = raw_summary.strip()[:200]

                except Exception:
                    pass

                if not market_cap:
                    continue

                market_cap_oku = round(market_cap / 100000000, 1)

                # フィルター6: 時価総額 300億円以下
                if 0 < market_cap_oku <= MAX_MARKET_CAP_OKU:
                    vol3 = float(volumes.iloc[-3:].mean())
                    vol5 = float(volumes.iloc[-5:].mean())
                    vol25 = float(volumes.iloc[-25:].mean())
                    vol_surge = round(vol5 / max(vol25, 1), 2)

                    # VCP（出来高枯渇・売り枯れ）検知: 52週高値10%圏内で直近3日出来高が25日平均の75%未満
                    is_vcp = (curr_close >= high_52w * 0.90) and (vol3 < max(vol25, 1) * 0.75)

                    # RS（相対力指数）: 個別株60日リターン - ベンチマーク60日リターン
                    p_60d_ago = float(closes.iloc[-min(60, len(closes))])
                    stock_return_60d = ((curr_close - p_60d_ago) / p_60d_ago) * 100
                    rs_rating = round(stock_return_60d - benchmark_return_60d, 1)

                    # 直近20営業日の大口買い集め比率（Up/Down Volume比）
                    up_down_ratio = calculate_up_down_volume_ratio(df.iloc[-21:] if len(df) >= 21 else df)

                    # 新高値接近度（1.0に近いほど新高値直下）
                    high_proximity = round(curr_close / high_52w, 3)

                    # テンバガー・プロフェッショナル複合スコア算出
                    # [回転率] + [急増比] + [売上成長] + [利益率] + [大口買い集め] + [RS超過] + [VCP初動] + [創業者比率] + [新高値近接]
                    turnover_score = min(trading_value_man / max(market_cap_oku, 1), 25.0)
                    surge_score = min(vol_surge * 5, 20.0)
                    growth_bonus = min(max(rev_growth_pct, 0) * 0.6, 20.0)
                    profit_bonus = min(max(op_margin_pct, 0) * 0.4, 10.0)
                    accumulation_score = min(up_down_ratio * 8, 15.0)
                    rs_bonus = min(max(rs_rating, 0) * 0.25, 15.0)
                    vcp_bonus = 10.0 if is_vcp else 0.0
                    founder_bonus = 10.0 if insider_held_pct >= 30 else (5.0 if insider_held_pct >= 15 else 0.0)
                    proximity_bonus = high_proximity * 10.0

                    total_momentum_score = round(
                        turnover_score + surge_score + growth_bonus + profit_bonus + accumulation_score + rs_bonus + vcp_bonus + founder_bonus + proximity_bonus, 2
                    )

                    code_str = str(row_meta["code"])
                    is_stay = code_str in prev_codes

                    candidates.append({
                        "code": code_str,
                        "name": row_meta["name"],
                        "market": row_meta["market"],
                        "sector": row_meta["sector"],
                        "close": curr_close,
                        "sma25": round(sma25, 1),
                        "sma75": round(sma75, 1),
                        "sma200": round(sma200, 1),
                        "high_52w": round(high_52w, 1),
                        "market_cap_oku": market_cap_oku,
                        "trading_value_man": trading_value_man,
                        "vol_surge": vol_surge,
                        "rev_growth_pct": rev_growth_pct,
                        "op_margin_pct": op_margin_pct,
                        "insider_held_pct": insider_held_pct,
                        "trailing_pe": trailing_pe,
                        "psr": psr,
                        "business_summary": business_summary,
                        "rs_rating": rs_rating,
                        "is_vcp": is_vcp,
                        "up_down_ratio": up_down_ratio,
                        "deviation_25_pct": round(deviation_25 * 100, 1),
                        "badge": "STAY" if is_stay else "NEW",
                        "momentum_score": total_momentum_score
                    })
                    vcp_str = " 🔥VCP" if is_vcp else ""
                    founder_str = f" / 創業者:{insider_held_pct}%" if insider_held_pct > 0 else ""
                    print(f"  ★ 合格: {code_str} {row_meta['name']} (株価:{curr_close}円 / {market_cap_oku}億 / RS:+{rs_rating}% / 売上:+{rev_growth_pct}%{founder_str}{vcp_str} / スコア:{total_momentum_score})")

            except Exception:
                continue

        time.sleep(0.5)

    # 複合モメンタムスコア順にソート
    candidates.sort(key=lambda x: x["momentum_score"], reverse=True)

    # 上位20銘柄に厳選
    if len(candidates) > TARGET_POOL_LIMIT:
        print(f"[INFO] 候補 {len(candidates)} 件から厳選上位 {TARGET_POOL_LIMIT} 銘柄を最終選定しました。")
        candidates = candidates[:TARGET_POOL_LIMIT]

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    elapsed = round(time.time() - start_time, 1)
    print(f"[INFO] スクリーニング完了: {len(candidates)} 件抽出 (所要時間: {elapsed}秒)")

    msg = f"東証厳選スクリーニング完了（所要時間: {elapsed}秒）\n厳選合格: {len(candidates)} 件\n\n"
    if candidates:
        top_samples = candidates[:5]
        msg += "【厳選モメンタム上位】\n"
        for c in top_samples:
            badge_icon = "🔁" if c["badge"] == "STAY" else "🆕"
            vcp_tag = " [VCP]" if c.get("is_vcp") else ""
            msg += f"{badge_icon} {c['code']} {c['name']} (値:{c['close']}円 / RS:+{c['rs_rating']}% / 売上:+{c['rev_growth_pct']}%{vcp_tag})\n"
        if len(candidates) > 5:
            msg += f"...他 {len(candidates) - 5} 銘柄\n"
        msg += f"\n※Gemini AIアナリストが上位{len(candidates)}銘柄の定性分析を開始します。"

    send_notification("週末厳選スクリーニング完了", msg)

if __name__ == "__main__":
    run_batch_screener()