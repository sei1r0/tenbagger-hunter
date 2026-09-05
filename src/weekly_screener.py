import os
import sys
import json
import time
import datetime
import requests
import io
import pandas as pd
import yfinance as yf
from utils.notifier import send_notification

# JPX 東証上場銘柄一覧 (毎月更新される公式Excel)
JPX_URL = "https://www.jpx.co.jp/markets/statistics-quotes/stocks/tvdivq0000003000-att/data_j.xls"

def fetch_jpx_stock_list():
    """JPX公式から東証上場銘柄の一覧を取得"""
    print("[INFO] JPXから東証上場銘柄一覧をダウンロード中...")
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(JPX_URL, headers=headers, timeout=30)
    res.raise_for_status()
    
    df = pd.read_excel(io.BytesIO(res.content))
    # 対象市場（プライム、スタンダード、グロース）のみ抽出
    target_markets = ['プライム（内国株式）', 'スタンダード（内国株式）', 'グロース（内国株式）']
    df_filtered = df[df['市場・商品区分'].isin(target_markets)].copy()
    df_filtered = df_filtered.rename(columns={'コード': 'code', '銘柄名': 'name', '市場・商品区分': 'market', '33業種区分': 'sector'})
    print(f"[INFO] 対象銘柄数: {len(df_filtered)} 件")
    return df_filtered[['code', 'name', 'market', 'sector']]

def is_blackout_period(ticker_obj, blackout_days=14):
    """直近指定日数以内に決算発表を控えているかを判定"""
    try:
        calendar = ticker_obj.calendar
        if calendar is not None and not calendar.empty:
            # yfinanceのcalendar形式に柔軟に対応
            earnings_dates = []
            if isinstance(calendar, dict) and 'Earnings Date' in calendar:
                earnings_dates = calendar['Earnings Date']
            elif hasattr(calendar, 'T') and 'Earnings Date' in calendar.T.columns:
                earnings_dates = calendar.T['Earnings Date'].dropna().tolist()

            today = datetime.date.today()
            for d in earnings_dates:
                if isinstance(d, datetime.datetime) or isinstance(d, datetime.date):
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

        # 時価総額: 50億円以上 〜 1000億円以下（テンバガーゾーン）
        if not (5_000_000_000 <= market_cap <= 100_000_000_000):
            return None

        # 4. 決算直前ブラックアウトガード（決算ギャンブル防止）
        is_bo, bo_detail = is_blackout_period(t, blackout_days=14)
        if is_bo:
            print(f"[SKIP] {row['name']} ({row['code']}) は決算間近のため除外: {bo_detail}")
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
    except Exception:
        return None

def main():
    start_time = time.time()
    os.makedirs("data", exist_ok=True)
    
    # 全銘柄リスト取得
    df_stocks = fetch_jpx_stock_list()
    
    candidates = []
    print("[INFO] 定量・テクニカルスクリーニングを開始します...")

    # レート制限を考慮しつつ順次走査（最大上位から順にテスト、または全件）
    for idx, row in df_stocks.iterrows():
        result = screen_stock(row)
        if result:
            candidates.append(result)
            print(f"[HIT] {result['code']} {result['name']} (時価総額: {result['market_cap_oku']}億円)")

        # APIレート制限対策（0.2秒待機）
        time.sleep(0.2)

        # 週末バッチで50〜60件程度集まったら次工程のエージェント分析用としては十分
        if len(candidates) >= 50:
            print("[INFO] 候補が規定数（50銘柄）に達したためスクリーニングを完了します。")
            break

    # 結果をJSONファイルへ保存
    output_path = "data/screened_candidates.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    elapsed = round(time.time() - start_time, 1)
    msg = f"週末スクリーニング完了（所要時間: {elapsed}秒）\n通過銘柄数: {len(candidates)}件\nデータを {output_path} に保存しました。"
    print(msg)

    if candidates:
        top_names = "\n".join([f"・{c['code']} {c['name']} ({c['market_cap_oku']}億)" for c in candidates[:5]])
        send_notification("週末スクリーニング（足切り完了）", f"{msg}\n\n【代表候補抜粋】\n{top_names}\n\n※この後Step 3のAIエージェント詳細分析に引き継がれます。")
    else:
        send_notification("週末スクリーニング", f"{msg}\n該当銘柄がありませんでした。")

if __name__ == "__main__":
    main()