import os
import json
import glob
import yfinance as yf
import pandas as pd
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
HISTORY_DIR = os.path.join(PROJECT_ROOT, "data", "history")
TRACK_RECORD_JSON = os.path.join(PROJECT_ROOT, "data", "track_record.json")

def archive_weekly_results(analyzed_stocks, date_str=None):
    """週次の厳選AI分析結果を history ディレクトリにアーカイブ保存"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    os.makedirs(HISTORY_DIR, exist_ok=True)
    archive_path = os.path.join(HISTORY_DIR, f"{date_str}.json")
    
    records = []
    for s in analyzed_stocks:
        rec = dict(s)
        rec["date"] = date_str
        a = s.get("analysis", {})
        rec["recommend_price"] = float(s.get("close", 0))
        rec["entry_price"] = float(a.get("entry_price", s.get("close", 0)))
        rec["stop_loss"] = float(a.get("stop_loss", 0))
        rec["conviction_tier"] = a.get("conviction_tier", "A")
        rec["score"] = a.get("score", 80)
        rec["theme_tags"] = a.get("theme_tags", [])
        records.append(rec)
    
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 週次アーカイブ保存完了: {archive_path} ({len(records)}銘柄)")

def calculate_track_record():
    """過去の全アーカイブ銘柄のパフォーマンスおよび勝率を自動集計"""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    history_files = glob.glob(os.path.join(HISTORY_DIR, "*.json"))
    
    if not history_files:
        # アーカイブがまだない場合のデフォルトサマリー
        default_summary = {
            "total_recommended": 0,
            "win_count": 0,
            "win_rate_pct": 0.0,
            "avg_max_gain_pct": 0.0,
            "tenbagger_candidates": 0,
            "records": []
        }
        return default_summary

    all_recommendations = {}
    for fpath in sorted(history_files):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                items = json.load(f)
                for item in items:
                    key = f"{item['code']}_{item['date']}"
                    all_recommendations[key] = item
        except Exception as e:
            print(f"[WARN] アーカイブ読み込みエラー ({fpath}): {e}")

    if not all_recommendations:
        return {
            "total_recommended": 0,
            "win_count": 0,
            "win_rate_pct": 0.0,
            "avg_max_gain_pct": 0.0,
            "tenbagger_candidates": 0,
            "records": []
        }

    # 各銘柄の日足ヒストリカルデータを取得
    unique_codes = list(set([item["code"] for item in all_recommendations.values()]))
    tickers = [f"{c}.T" for c in unique_codes]

    stock_dfs = {}
    try:
        data = yf.download(
            tickers=tickers,
            period="6mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True
        )
        for c in unique_codes:
            sym = f"{c}.T"
            if len(tickers) == 1:
                df = data.dropna()
            else:
                if sym not in data.columns.levels[0]:
                    continue
                df = data[sym].dropna()
            
            if not df.empty:
                stock_dfs[c] = df
    except Exception as e:
        print(f"[WARN] トラックレコード株価取得エラー: {e}")

    evaluated_records = []
    win_count = 0
    total_max_gain = 0.0
    tenbagger_candidates = 0

    for key, item in all_recommendations.items():
        code = item["code"]
        rec_p = float(item["recommend_price"])
        stop_loss = float(item.get("stop_loss", 0))
        rec_date = item.get("date", "2020-01-01")

        df = stock_dfs.get(code)
        if df is None or df.empty:
            curr_p, high_p, max_gain_pct, curr_gain_pct, status_label = rec_p, rec_p, 0.0, 0.0, "推移中"
            is_win = False
        else:
            try:
                rec_dt = pd.to_datetime(rec_date).tz_localize(df.index.tz) if df.index.tz else pd.to_datetime(rec_date)
                df_sub = df[df.index >= rec_dt]
                if df_sub.empty:
                    df_sub = df.iloc[-5:]
            except Exception:
                df_sub = df

            curr_p = float(df_sub["Close"].iloc[-1])
            high_p = float(df_sub["High"].max())
            max_gain_pct = round(((high_p - rec_p) / max(rec_p, 1)) * 100, 1)
            curr_gain_pct = round(((curr_p - rec_p) / max(rec_p, 1)) * 100, 1)

            # 時系列損切り・利確シミュレーション（Execution-Aware Backtest）
            status_label = "推移中"
            is_win = False

            for _, row_bar in df_sub.iterrows():
                bar_low = float(row_bar["Low"])
                bar_high = float(row_bar["High"])

                # A. 損切りライン到達が先か？
                if stop_loss > 0 and bar_low <= stop_loss:
                    status_label = "損切執行"
                    is_win = False
                    break

                # B. +10%利確ターゲット到達が先か？
                if bar_high >= (rec_p * 1.10):
                    status_label = "利確達成 (+10%超)"
                    is_win = True
                    break

            if status_label == "推移中":
                if curr_gain_pct >= 5.0:
                    status_label = "含み益堅調"
                    is_win = True
                elif curr_gain_pct <= -5.0:
                    status_label = "調整中"

        if is_win:
            win_count += 1
        
        if max_gain_pct >= 50.0:
            tenbagger_candidates += 1

        total_max_gain += max_gain_pct

        evaluated_records.append({
            "date": item["date"],
            "code": code,
            "name": item["name"],
            "market": item.get("market", "グロース"),
            "sector": item.get("sector", ""),
            "conviction_tier": item.get("conviction_tier", "A"),
            "recommend_price": rec_p,
            "curr_price": curr_p,
            "high_price": high_p,
            "max_gain_pct": max_gain_pct,
            "curr_gain_pct": curr_gain_pct,
            "status": status_label
        })

    total_count = len(evaluated_records)
    win_rate = round((win_count / max(total_count, 1)) * 100, 1)
    avg_max_gain = round(total_max_gain / max(total_count, 1), 1)

    # 上昇率順にソート
    evaluated_records.sort(key=lambda x: x["max_gain_pct"], reverse=True)

    summary = {
        "total_recommended": total_count,
        "win_count": win_count,
        "win_rate_pct": win_rate,
        "avg_max_gain_pct": avg_max_gain,
        "tenbagger_candidates": tenbagger_candidates,
        "records": evaluated_records[:15] # 上位15件
    }

    try:
        with open(TRACK_RECORD_JSON, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return summary

if __name__ == "__main__":
    res = calculate_track_record()
    print("[INFO] トラックレコード集計結果:")
    print(f"  累計推奨数: {res['total_recommended']}件 / 勝率: {res['win_rate_pct']}% / 平均最高上昇率: +{res['avg_max_gain_pct']}%")
