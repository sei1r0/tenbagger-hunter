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

# テンバガー初動厳選基準（約40件前後に絞り込むプロ基準）
MAX_MARKET_CAP_OKU = 300       # 時価総額 300億円以下（急成長ポテンシャル重視）
MIN_TRADING_VALUE_MAN = 5000   # 1日売買代金 5,000万円以上（流動性と大口流入）
BATCH_SIZE = 80                # yfinance API安定化バッチサイズ
TARGET_POOL_LIMIT = 40         # スクリーニング結果として残す目標上限数

def run_batch_screener():
    start_time = time.time()
    if not os.path.exists(STOCKS_CSV):
        print(f"[ERROR] {STOCKS_CSV} が見つかりません。")
        sys.exit(1)

    df_stocks = pd.read_csv(STOCKS_CSV, dtype={"code": str})
    
    # フィルター1: 市場区分を「グロース」および「スタンダード」に限定（低成長プライムを除外）
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
            # 過去1年分（52週高値計算用）の日足を一括取得
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

                # フィルター2: 売買代金 5,000万円以上
                if trading_value_man < MIN_TRADING_VALUE_MAN:
                    continue

                # テクニカル指標計算
                sma25 = float(closes.rolling(window=25).mean().iloc[-1])
                sma75 = float(closes.rolling(window=75).mean().iloc[-1])
                
                # フィルター3: パーフェクトオーダー基調（現在値 > 25MA かつ 25MA > 75MA）
                if not (curr_close > sma25 and sma25 > sma75):
                    continue

                # フィルター4: 52週高値から15%以内のブレイク初動水準（オニール型モメンタム）
                high_52w = float(closes.max())
                if curr_close < (high_52w * 0.85):
                    continue

                # 時価総額チェック
                t = yf.Ticker(ticker_symbol)
                info = t.info or {}
                market_cap = info.get("marketCap", 0)
                if not market_cap:
                    shares = info.get("sharesOutstanding", 0)
                    market_cap = curr_close * shares if shares else 0

                market_cap_oku = round(market_cap / 100000000, 1)

                # フィルター5: 時価総額 300億円以下
                if 0 < market_cap_oku <= MAX_MARKET_CAP_OKU:
                    # 出来高急増率（直近5日平均 vs 25日平均）
                    vol5 = float(volumes.iloc[-5:].mean())
                    vol25 = float(volumes.iloc[-25:].mean())
                    vol_surge = round(vol5 / max(vol25, 1), 2)

                    candidates.append({
                        "code": row_meta["code"],
                        "name": row_meta["name"],
                        "market": row_meta["market"],
                        "sector": row_meta["sector"],
                        "close": curr_close,
                        "market_cap_oku": market_cap_oku,
                        "trading_value_man": trading_value_man,
                        "high_52w": high_52w,
                        "vol_surge": vol_surge,
                        "momentum_score": round((trading_value_man / max(market_cap_oku, 1)) * vol_surge, 2)
                    })
                    print(f"  ★ 厳選合格: {row_meta['code']} {row_meta['name']} ({market_cap_oku}億 / 代金:{trading_value_man}万 / 出来高比:{vol_surge}倍)")

            except Exception:
                continue

        time.sleep(0.5)

    # モメンタムスコア順（売買回転率 × 出来高急増率）にソート
    candidates.sort(key=lambda x: x["momentum_score"], reverse=True)

    # 40件前後に厳選
    if len(candidates) > TARGET_POOL_LIMIT:
        print(f"[INFO] 抽出 {len(candidates)} 件から初動上位 {TARGET_POOL_LIMIT} 銘柄を最終プールに設定しました。")
        candidates = candidates[:TARGET_POOL_LIMIT]

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    elapsed = round(time.time() - start_time, 1)
    print(f"[INFO] スクリーニング完了: {len(candidates)} 件抽出 (所要時間: {elapsed}秒)")

    # LINE通知
    msg = f"東証厳選スクリーニング完了（所要時間: {elapsed}秒）\n合格銘柄数: {len(candidates)} 件\n\n"
    if candidates:
        top_samples = candidates[:5]
        msg += "【厳選モメンタム上位】\n"
        for c in top_samples:
            msg += f"・{c['code']} {c['name']} ({c['market_cap_oku']}億 / 出来高急増:{c['vol_surge']}倍)\n"
        if len(candidates) > 5:
            msg += f"...他 {len(candidates) - 5} 銘柄\n"
        msg += "\n※AIアナリストが上位15銘柄を深掘り分析します。"
    else:
        msg += "今週は高精度ブレイク条件に合致する銘柄がありませんでした。"

    send_notification("週末厳選スクリーニング結果", msg)

if __name__ == "__main__":
    run_batch_screener()