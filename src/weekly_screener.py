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
MIN_SMA25_DEVIATION = 0.02     # 25日線上方乖離率 2%以上（初動確認）
BATCH_SIZE = 50                # yfinance API安定化バッチサイズ
TARGET_POOL_LIMIT = 20         # 厳選上位20銘柄に絞り込み

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

def run_batch_screener():
    start_time = time.time()
    if not os.path.exists(STOCKS_CSV):
        print(f"[ERROR] {STOCKS_CSV} が見つかりません。")
        sys.exit(1)

    prev_codes = get_prev_screened_codes()

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

                # フィルター4: 25日線乖離率（高値掴みイナゴ排除 & 初動判定）
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
                try:
                    t = yf.Ticker(ticker_symbol)
                    fast = getattr(t, "fast_info", None)
                    if fast and hasattr(fast, "market_cap") and fast.market_cap:
                        market_cap = fast.market_cap

                    # 売上成長率および時価総額フォールバックの取得
                    info = t.info or {}
                    if not market_cap:
                        market_cap = info.get("marketCap", 0)

                    rev_growth = info.get("revenueGrowth", None)
                    if rev_growth is not None:
                        rev_growth_pct = round(rev_growth * 100, 1)
                except Exception:
                    pass

                if not market_cap:
                    continue

                market_cap_oku = round(market_cap / 100000000, 1)

                # フィルター6: 時価総額 300億円以下
                if 0 < market_cap_oku <= MAX_MARKET_CAP_OKU:
                    vol5 = float(volumes.iloc[-5:].mean())
                    vol25 = float(volumes.iloc[-25:].mean())
                    vol_surge = round(vol5 / max(vol25, 1), 2)

                    # 直近20営業日の大口買い集め比率（Up/Down Volume比）
                    up_down_ratio = calculate_up_down_volume_ratio(df.iloc[-20:])

                    # 新高値接近度（1.0に近いほど新高値直下）
                    high_proximity = round(curr_close / high_52w, 3)

                    # 複合モメンタムスコア算出
                    # [売買代金回転率] + [出来高急増比] + [売上成長ボーナス] + [大口資金流入比] + [新高値接近度]
                    turnover_score = min(trading_value_man / max(market_cap_oku, 1), 50.0)
                    surge_score = min(vol_surge * 10, 50.0)
                    growth_bonus = min(max(rev_growth_pct, 0), 40.0)
                    accumulation_score = min(up_down_ratio * 15, 30.0)
                    proximity_bonus = high_proximity * 20.0

                    total_momentum_score = round(
                        turnover_score + surge_score + growth_bonus + accumulation_score + proximity_bonus, 2
                    )

                    code_str = str(row_meta["code"])
                    is_stay = code_str in prev_codes

                    candidates.append({
                        "code": code_str,
                        "name": row_meta["name"],
                        "market": row_meta["market"],
                        "sector": row_meta["sector"],
                        "close": curr_close,
                        "market_cap_oku": market_cap_oku,
                        "trading_value_man": trading_value_man,
                        "high_52w": high_52w,
                        "vol_surge": vol_surge,
                        "rev_growth_pct": rev_growth_pct,
                        "up_down_ratio": up_down_ratio,
                        "deviation_25_pct": round(deviation_25 * 100, 1),
                        "badge": "STAY" if is_stay else "NEW",
                        "momentum_score": total_momentum_score
                    })
                    print(f"  ★ 合格: {code_str} {row_meta['name']} (株価:{curr_close}円 / {market_cap_oku}億 / 乖離:+{round(deviation_25*100,1)}% / 大口比:{up_down_ratio}倍 / スコア:{total_momentum_score})")

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
            msg += f"{badge_icon} {c['code']} {c['name']} (値:{c['close']}円 / {c['market_cap_oku']}億 / 大口比:{c['up_down_ratio']}倍)\n"
        if len(candidates) > 5:
            msg += f"...他 {len(candidates) - 5} 銘柄\n"
        msg += f"\n※Gemini AIアナリストが上位{len(candidates)}銘柄の定性分析を開始します。"

    send_notification("週末厳選スクリーニング完了", msg)

if __name__ == "__main__":
    run_batch_screener()