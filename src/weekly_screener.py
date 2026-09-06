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

def fetch_benchmark_returns():
    """グロース250指数の直近60営業日および120営業日リターンを算出"""
    ret_60d, ret_120d = 0.0, 0.0
    try:
        t = yf.Ticker(BENCHMARK_TICKER)
        hist = t.history(period="1y")
        if len(hist) >= 60:
            curr_p = float(hist["Close"].iloc[-1])
            p_60 = float(hist["Close"].iloc[-60])
            ret_60d = ((curr_p - p_60) / p_60) * 100
        if len(hist) >= 120:
            curr_p = float(hist["Close"].iloc[-1])
            p_120 = float(hist["Close"].iloc[-120])
            ret_120d = ((curr_p - p_120) / p_120) * 100
    except Exception as e:
        print(f"[WARN] ベンチマーク取得失敗 ({BENCHMARK_TICKER}): {e}")
    return ret_60d, ret_120d

def run_batch_screener():
    start_time = time.time()
    if not os.path.exists(STOCKS_CSV):
        print(f"[ERROR] {STOCKS_CSV} が見つかりません。")
        sys.exit(1)

    prev_codes = get_prev_screened_codes()

    # RS（Relative Strength）の基準となるグロース市場マルチタイムリターンを取得
    bench_ret_60d, bench_ret_120d = fetch_benchmark_returns()
    print(f"[INFO] グロース市場ベンチマークリターン (60日: {round(bench_ret_60d, 2)}% / 120日: {round(bench_ret_120d, 2)}%)")

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

        if data is None or data.empty:
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

                sma5_series = closes.rolling(window=5).mean()
                sma25_series = closes.rolling(window=25).mean()
                sma75_series = closes.rolling(window=75).mean()
                sma200_series = closes.rolling(window=min(200, len(closes))).mean()

                sma5 = float(sma5_series.iloc[-1])
                sma25 = float(sma25_series.iloc[-1])
                sma75 = float(sma75_series.iloc[-1])
                sma200 = float(sma200_series.iloc[-1])
                sma200_20d_ago = float(sma200_series.iloc[-min(20, len(sma200_series))])

                # フィルター3: パーフェクトオーダー（株価 > 25MA > 75MA かつ 株価 > 200MA）
                if not (curr_close > sma25 and sma25 > sma75 and curr_close > sma200):
                    continue

                # フィルター4: 25日線乖離率（高値掴みイナゴ排除 & 25MAタッチ押し目を許容）
                deviation_25 = (curr_close - sma25) / sma25
                if not (MIN_SMA25_DEVIATION <= deviation_25 <= MAX_SMA25_DEVIATION):
                    continue

                # フィルター5: 52週高値から15%以内（高値ブレイクアウト圏）
                high_52w = float(closes.max())
                low_52w = float(closes.min())
                if curr_close < (high_52w * 0.85):
                    continue

                # --- 総合トレンド分析エンジン（5大トレンド要素） ---
                # 1. 200日線上昇 ＆ ミネルヴィニ式 Stage 2 トレンド判定
                is_200ma_rising = bool(sma200 >= sma200_20d_ago)
                is_stage2 = bool(curr_close > sma25 > sma75 > sma200 and is_200ma_rising)

                # 2. ゴールデンクロス初動判定 (直近15日以内に25MAが75MA上抜け、または直近5日以内に5MAが25MA上抜け)
                diff_25_75 = sma25_series - sma75_series
                is_gc_25_75 = False
                if len(diff_25_75) >= 16:
                    rec_diffs = diff_25_75.iloc[-15:]
                    if rec_diffs.iloc[-1] > 0 and (rec_diffs <= 0).any():
                        is_gc_25_75 = True

                diff_5_25 = sma5_series - sma25_series
                is_gc_5_25 = False
                if len(diff_5_25) >= 6:
                    rec_5_25 = diff_5_25.iloc[-5:]
                    if rec_5_25.iloc[-1] > 0 and (rec_5_25 <= 0).any():
                        is_gc_5_25 = True

                is_golden_cross = bool(is_gc_25_75 or is_gc_5_25)

                # 3. 52週安値比リバウンド (+30%以上の上昇本命株)
                low_rebound_pct = round(((curr_close - low_52w) / max(low_52w, 1)) * 100, 1)
                is_52w_rebound = bool(low_rebound_pct >= 30.0)

                # 4. 健全ベース形成 (高値からの調整が15%以内の浅いカップ/フラッグ)
                pullback_from_high_pct = round(((high_52w - curr_close) / max(high_52w, 1)) * 100, 1)
                is_sound_base = bool(pullback_from_high_pct <= 15.0)

                # 5. MACD モメンタム好転 (MACD > Signal)
                ema12 = closes.ewm(span=12, adjust=False).mean()
                ema26 = closes.ewm(span=26, adjust=False).mean()
                macd_line = ema12 - ema26
                macd_signal = macd_line.ewm(span=9, adjust=False).mean()
                is_macd_bullish = bool(macd_line.iloc[-1] > macd_signal.iloc[-1])

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

                    # ネットキャッシュ（実質無借金判定: 現預金 > 有利子負債）
                    total_cash = info.get("totalCash", 0) or 0
                    total_debt = info.get("totalDebt", 0) or 0
                    is_net_cash = bool(total_cash > total_debt and total_cash > 0)

                    # 浮動株時価総額の推定
                    float_shares = info.get("floatShares", None)

                    # ① 上場後1〜5年「黄金期」判定
                    first_trade_epoch = info.get("firstTradeDateEpochUtc", None)
                    is_fresh_ipo = False
                    if first_trade_epoch:
                        days_since_ipo = (time.time() - float(first_trade_epoch)) / 86400
                        is_fresh_ipo = bool(300 <= days_since_ipo <= 1825) # 約1年〜5年

                    # ② 成長加速度（売上成長 +25%以上 または 利益成長 +30%以上）
                    earnings_growth = info.get("earningsGrowth", None)
                    earnings_growth_pct = round(float(earnings_growth) * 100, 1) if earnings_growth is not None else None
                    is_accelerating = bool(rev_growth_pct >= 25.0 or (earnings_growth_pct and earnings_growth_pct >= 30.0))

                    # ④ 機関投資家保有比率（初期青田買い段階: 3%〜25%）
                    inst_held = info.get("heldPercentInstitutions", None)
                    inst_held_pct = round(float(inst_held) * 100, 1) if inst_held is not None else 0.0
                    is_early_inst = bool(3.0 <= inst_held_pct <= 25.0)

                except Exception:
                    pass

                if not market_cap:
                    continue

                market_cap_oku = round(market_cap / 100000000, 1)

                # フィルター6: 時価総額 300億円以下
                if 0 < market_cap_oku <= MAX_MARKET_CAP_OKU:
                    if float_shares and float(float_shares) > 0:
                        float_mcap_oku = round((float(float_shares) * curr_close) / 100000000, 1)
                    elif insider_held_pct > 0:
                        float_mcap_oku = round(market_cap_oku * (1 - (insider_held_pct / 100)), 1)
                    else:
                        float_mcap_oku = market_cap_oku

                    # 需給の軽さ（浮動株時価総額80億円以下の超軽量株）
                    is_ultra_light = bool(0 < float_mcap_oku <= 80.0)

                    # 営業利益黒字転換・高成長モメンタム（売上成長+15%以上かつ営業利益黒字）
                    is_turnaround = bool(rev_growth_pct >= 15.0 and op_margin_pct > 0)

                    vol3 = float(volumes.iloc[-3:].mean())
                    vol5 = float(volumes.iloc[-5:].mean())
                    vol25 = float(volumes.iloc[-25:].mean())
                    vol_surge = round(vol5 / max(vol25, 1), 2)

                    # VCP（出来高枯渇・売り枯れ）検知: 52週高値10%圏内で直近3日出来高が25日平均の75%未満
                    is_vcp = (curr_close >= high_52w * 0.90) and (vol3 < max(vol25, 1) * 0.75)

                    # ③ マルチタイムRS（相対力指数）: 60日RS (60%) ＋ 120日RS (40%) の加重相対力
                    p_60d_ago = float(closes.iloc[-min(60, len(closes))])
                    p_120d_ago = float(closes.iloc[-min(120, len(closes))])
                    stock_return_60d = ((curr_close - p_60d_ago) / p_60d_ago) * 100
                    stock_return_120d = ((curr_close - p_120d_ago) / p_120d_ago) * 100
                    rs_60d = stock_return_60d - bench_ret_60d
                    rs_120d = stock_return_120d - bench_ret_120d
                    rs_rating = round(rs_60d * 0.6 + rs_120d * 0.4, 1)

                    # 直近20営業日の大口買い集め比率（Up/Down Volume比）
                    up_down_ratio = calculate_up_down_volume_ratio(df.iloc[-21:] if len(df) >= 21 else df)

                    # 新高値接近度（1.0に近いほど新高値直下）
                    high_proximity = round(curr_close / high_52w, 3)

                    # テンバガー・プロフェッショナル複合スコア算出
                    # [回転率] + [急増比] + [売上成長] + [利益率] + [大口買い集め] + [RS超過] + [VCP初動] + [創業者比率] + [新高値近接] + [浮動株軽量] + [ネットキャッシュ] + [黒字成長] + [上場黄金期] + [成長加速] + [機関初期] + [Stage2] + [GC初動] + [健全ベース] + [安値リバウンド] + [MACD好転]
                    turnover_score = min(trading_value_man / max(market_cap_oku, 1), 25.0)
                    surge_score = min(vol_surge * 5, 20.0)
                    growth_bonus = min(max(rev_growth_pct, 0) * 0.6, 20.0)
                    profit_bonus = min(max(op_margin_pct, 0) * 0.4, 10.0)
                    accumulation_score = min(up_down_ratio * 8, 15.0)
                    rs_bonus = min(max(rs_rating, 0) * 0.25, 15.0)
                    vcp_bonus = 10.0 if is_vcp else 0.0
                    founder_bonus = 10.0 if insider_held_pct >= 30 else (5.0 if insider_held_pct >= 15 else 0.0)
                    proximity_bonus = high_proximity * 10.0
                    float_bonus = 8.0 if is_ultra_light else 0.0
                    net_cash_bonus = 5.0 if is_net_cash else 0.0
                    turnaround_bonus = 5.0 if is_turnaround else 0.0
                    ipo_bonus = 6.0 if is_fresh_ipo else 0.0
                    accel_bonus = 6.0 if is_accelerating else 0.0
                    inst_bonus = 5.0 if is_early_inst else 0.0

                    # トレンド総合加点
                    stage2_bonus = 8.0 if is_stage2 else 0.0
                    gc_bonus = 7.0 if is_golden_cross else 0.0
                    base_bonus = 5.0 if is_sound_base else 0.0
                    rebound_bonus = 4.0 if is_52w_rebound else 0.0
                    macd_bonus = 4.0 if is_macd_bullish else 0.0

                    total_momentum_score = round(
                        turnover_score + surge_score + growth_bonus + profit_bonus + accumulation_score + rs_bonus + vcp_bonus + founder_bonus + proximity_bonus + float_bonus + net_cash_bonus + turnaround_bonus + ipo_bonus + accel_bonus + inst_bonus + stage2_bonus + gc_bonus + base_bonus + rebound_bonus + macd_bonus, 2
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
                        "low_52w": round(low_52w, 1),
                        "low_rebound_pct": low_rebound_pct,
                        "market_cap_oku": market_cap_oku,
                        "float_mcap_oku": float_mcap_oku,
                        "trading_value_man": trading_value_man,
                        "vol_surge": vol_surge,
                        "rev_growth_pct": rev_growth_pct,
                        "op_margin_pct": op_margin_pct,
                        "insider_held_pct": insider_held_pct,
                        "inst_held_pct": inst_held_pct,
                        "trailing_pe": trailing_pe,
                        "psr": psr,
                        "business_summary": business_summary,
                        "rs_rating": rs_rating,
                        "is_vcp": is_vcp,
                        "is_ultra_light": is_ultra_light,
                        "is_net_cash": is_net_cash,
                        "is_turnaround": is_turnaround,
                        "is_fresh_ipo": is_fresh_ipo,
                        "is_accelerating": is_accelerating,
                        "is_early_inst": is_early_inst,
                        "is_stage2": is_stage2,
                        "is_golden_cross": is_golden_cross,
                        "is_sound_base": is_sound_base,
                        "is_macd_bullish": is_macd_bullish,
                        "up_down_ratio": up_down_ratio,
                        "deviation_25_pct": round(deviation_25 * 100, 1),
                        "badge": "STAY" if is_stay else "NEW",
                        "momentum_score": total_momentum_score
                    })
                    vcp_str = " 🔥VCP" if is_vcp else ""
                    founder_str = f" / 創業者:{insider_held_pct}%" if insider_held_pct > 0 else ""
                    float_str = f" / 浮動株:{float_mcap_oku}億" if is_ultra_light else ""
                    ipo_str = " 🌱IPO黄金期" if is_fresh_ipo else ""
                    gc_str = " ✨GC初動" if is_golden_cross else ""
                    stage2_str = " 🌊Stage2" if is_stage2 else ""
                    print(f"  ★ 合格: {code_str} {row_meta['name']} (株価:{curr_close}円 / {market_cap_oku}億{float_str} / RS:+{rs_rating}%{stage2_str}{gc_str}{vcp_str}{ipo_str} / スコア:{total_momentum_score})")

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