import os
import sys
import json
import time
import datetime
import pandas as pd
import yfinance as yf
from utils.notifier import send_notification

CSV_PATH = "data/jpx_stocks.csv"

def load_stock_list():
    """管理マスターCSVから銘柄一覧を安定読み込み"""
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"{CSV_PATH} が見つかりません。")
    df = pd.read_csv(CSV_PATH, dtype={'code': str})
    print(f"[INFO] 監視対象銘柄数: {len(df)} 件")
    return df

def is_blackout_period(ticker_obj, blackout_days=14):
    """直近指定日数以内に決算発表を控えているかを判定"""
    try:
        calendar = ticker_obj.calendar
        if calendar is not None and not calendar.empty:
            earnings_dates = []
            if isinstance(calendar, dict) and 'Earnings Date' in calendar:
                earnings_dates = calendar['Earnings Date']
            elif hasattr(calendar, 'T') and 'Earnings Date' in calendar.T.columns:
                earnings_dates = calendar.T['Earnings Date'].dropna().tolist()

            today = datetime.date.today()
            for d in earnings_dates:
                if isinstance(d, (datetime.datetime, datetime.date)):
                    target_date = d.date() if isinstance(d, datetime.datetime) else d
                    diff = (target_date - today).days
                    if 0 <= diff <= blackout_days:
                        return True, f"{target_date.strftime('%Y-%m-%d')} (直近{diff}日後)"
    except Exception:
        pass
    return False, ""

def screen_stock(row):
    """個別銘柄のテクニカル・定量・ブラックアウト判定"""
    code_str = f"{row['code']}.T"
    try:
        t = yf.Ticker(code_str)
        hist = t.history(period="1y")
        if len(hist) < 150:
            return None

        # テクニカル指標算出
        hist['SMA50'] = hist['Close'].rolling(window=50).mean()
        hist['SMA150'] = hist['Close'].rolling(window=150).mean()
        
        latest_close = hist['Close'].iloc[-1]
        latest_vol = hist['Volume'].iloc[-1]
        sma50 = hist['SMA50'].iloc[-1]
        sma150 = hist['SMA150'].iloc[-1]

        # 1. テクニカルトレンド判定（株価 > SMA50 > SMA150）
        if not (latest_close > sma50 > sma150):
            return None

        # 2. 流動性判定（1日の概算売買代金が 5,000万円以上）
        trading_val = latest_close * latest_vol
        if trading_val < 50_000_000:
            return None

        # 3. 会社情報・時価総額チェック
        info = t.info
        market_cap = info.get('marketCap')
        if not market_cap:
            return None

        # 時価総額: 50億円以上 〜 1,000億円以下（テンバガー有望ゾーン）
        # ※テスト時に引っかかりやすくするため上限を緩和する場合はここを調整可能
        if not (5_000_000_000 <= market_cap <= 100_000_000_000):
            return None

        # 4. 決算直前ブラックアウトガード
        is_bo, bo_detail = is_blackout_period(t, blackout_days=14)
        if is_bo:
            print(f"[SKIP] {row['name']} ({row['code']}) は決算直前の除外対象: {bo_detail}")
            return None

        return {
            "code": str(row['code']),
            "name": str(row['name']),
            "market": str(row['market']),
            "sector": str(row['sector']),
            "close": round(latest_close, 1),
            "market_cap_oku": round(market_cap / 100_000_000, 1),
            "trading_value_man": round(trading_val / 10_000, 1),
            "screened_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        }
    except Exception as e:
        return None

def main():
    start_time = time.time()
    os.makedirs("data", exist_ok=True)
    
    df_stocks = load_stock_list()
    candidates = []
    print("[INFO] 定量・テクニカルスクリーニングを開始します...")

    for idx, row in df_stocks.iterrows():
        result = screen_stock(row)
        if result:
            candidates.append(result)
            print(f"[HIT] {result['code']} {result['name']} (時価総額: {result['market_cap_oku']}億円)")

        time.sleep(0.3)

    output_path = "data/screened_candidates.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    elapsed = round(time.time() - start_time, 1)
    msg = f"週末スクリーニング完了（所要時間: {elapsed}秒）\n通過銘柄数: {len(candidates)}件"
    print(msg)

    if candidates:
        top_names = "\n".join([f"・{c['code']} {c['name']} ({c['market_cap_oku']}億)" for c in candidates[:5]])
        send_notification("週末スクリーニング完了", f"{msg}\n\n【抽出銘柄】\n{top_names}\n\n※AI統合アナリティクス分析へ引き継がれます。")
    else:
        send_notification("週末スクリーニング完了", f"{msg}\n基準（上昇トレンド・中小型時価総額・流動性）を満たす銘柄はありませんでした。")

if __name__ == "__main__":
    main()