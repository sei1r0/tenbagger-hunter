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
MAX_MARKET_CAP_OKU = 300       # 時価総額 300億円以下
MIN_TRADING_VALUE_MAN = 5000   # 1日売買代金 5,000万円以上
BATCH_SIZE = 80                # yfinance API安定化バッチサイズ
TARGET_POOL_LIMIT = 40         # スクリーニング結果として残す目標上限数

def get_prev_screened_codes():
    """前回のスクリーニング結果から銘柄コード一覧を取得"""
    if os.path.exists(OUTPUT_JSON):
        try:
            with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
                return set([item["code"] for item in prev_data])
        except Exception:
            return set()
    return set()

def run_batch_screener():
    start_time = time.time()
    if not os.path.exists(STOCKS_CSV):
        print(f"[ERROR] {STOCKS_CSV} が見つかりません。")
        sys.exit(1)

    prev_codes = get_prev_screened_codes()

    df_stocks = pd.read_csv(STOCKS_CSV, dtype={"code": str})
    # グロース・スタンダード市場に限定
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
            # 1年分の日足データ取得
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

                if len(df) < 60:
                    continue

                closes = df["Close"]
                volumes = df["Volume"]

                curr_close = float(closes.iloc[-1])
                curr_vol = float(volumes.iloc[-1])
                trading_value_man = round((curr_close * curr_vol) / 10000, 1)

                # フィルター1: 売買代金 5,000万円以上
                if trading_value_man < MIN_TRADING_VALUE_MAN:
                    continue

                # テクニカル指標計算
                sma25 = float(closes.rolling(window=25).mean().iloc[-1])
                sma75 = float(closes.rolling(window=75).mean().iloc[-1])
                
                # フィルター2: パーフェクトオーダー（現在値 > 25MA > 75MA）
                if not (curr_close > sma25 and sma25 > sma75):
                    continue

                # フィルター3: 52週高値から15%以内（高値モメンタム）
                high_52w = float(closes.max())
                if curr_close < (high_52w * 0.85):
                    continue

                # 詳細スペック・ファンダメンタルズ取得
                t = yf.Ticker(ticker_symbol)
                info = t.info or {}
                market_cap = info.get("marketCap", 0)
                if not market_cap:
                    shares = info.get("sharesOutstanding", 0)
                    market_cap = curr_close * shares if shares else 0

                market_cap_oku = round(market_cap / 100000000, 1)

                # フィルター4: 時価総額 300億円以下
                if 0 < market_cap_oku <= MAX_MARKET_CAP_OKU:
                    vol5 = float(volumes.iloc[-5:].mean())
                    vol25 = float(volumes.iloc[-25:].mean())
                    vol_surge = round(vol5 / max(vol25, 1), 2)

                    # 売上成長率（直近YoY）の取得（存在しない場合は0%）
                    rev_growth = info.get("revenueGrowth", None)
                    rev_growth_pct = round(rev_growth * 100, 1) if rev_growth is not None else 0.0

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
                        "badge": "STAY" if is_stay else "NEW",
                        "momentum_score": round((trading_value_man / max(market_cap_oku, 1)) * vol_surge, 2)
                    })
                    print(f"  ★ 合格: {code_str} {row_meta['name']} ({market_cap_oku}億 / 売上成長:{rev_growth_pct}% / 出来高比:{vol_surge}倍)")

            except Exception:
                continue

        time.sleep(0.3)

    # モメンタムスコア順にソート
    candidates.sort(key=lambda x: x["momentum_score"], reverse=True)

    if len(candidates) > TARGET_POOL_LIMIT:
        print(f"[INFO] 候補 {len(candidates)} 件から初動上位 {TARGET_POOL_LIMIT} 銘柄を最終プールに設定しました。")
        candidates = candidates[:TARGET_POOL_LIMIT]

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    elapsed = round(time.time() - start_time, 1)
    print(f"[INFO] スクリーニング完了: {len(candidates)} 件抽出 (所要時間: {elapsed}秒)")

    # 概要通知
    msg = f"東証厳選スクリーニング完了（所要時間: {elapsed}秒）\n合格銘柄数: {len(candidates)} 件\n\n"
    if candidates:
        top_samples = candidates[:5]
        msg += "【厳選モメンタム上位】\n"
        for c in top_samples:
            badge_icon = "🔁" if c["badge"] == "STAY" else "🆕"
            msg += f"{badge_icon} {c['code']} {c['name']} ({c['market_cap_oku']}億 / 売上+{c['rev_growth_pct']}%)\n"
        if len(candidates) > 5:
            msg += f"...他 {len(candidates) - 5} 銘柄\n"
        msg += f"\n※GeminiによるリアルタイムGoogle検索グラウンディング分析へ進みます。"

    send_notification("週末厳選スクリーニング完了", msg)

if __name__ == "__main__":
    run_batch_screener()