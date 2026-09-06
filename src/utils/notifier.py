import os
import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

def send_notification(title, message, color_level=None):
    """テキスト通知（フォールバック用）"""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")

    if not token or not user_id:
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": f"【{title}】\n\n{message}"}]
    }

    try:
        requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=15)
    except Exception as e:
        print(f"[ERROR] LINE通知送信例外: {e}")

def create_market_bubble(market_data):
    """主要5指数の一覧を表示する専用Flexバブルを作成"""
    rows = []
    for idx, item in enumerate(market_data):
        w_sign = "+" if item["week_diff"] > 0 else ""
        y_sign = "+" if item["ytd_diff"] > 0 else ""
        w_color = "#10b981" if item["week_diff"] >= 0 else "#ef4444"
        y_color = "#10b981" if item["ytd_diff"] >= 0 else "#ef4444"

        icon = item.get("icon", "📌")
        name = item.get("name", "")
        desc = item.get("desc", "")
        display_val = item.get("display_val", item.get("current_str", ""))
        display_week = item.get("display_week_diff", f"{w_sign}{item.get('week_diff_str', '')}")
        display_ytd = item.get("display_ytd_diff", f"{y_sign}{item.get('ytd_diff_str', '')}")

        row_contents = [
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": f"{icon} {name}", "weight": "bold", "size": "xs", "color": "#f8fafc", "flex": 5},
                    {"type": "text", "text": display_val, "weight": "bold", "size": "xs", "color": "#ffffff", "align": "end", "flex": 5}
                ]
            },
            {
                "type": "text",
                "text": desc,
                "size": "xxs",
                "color": "#94a3b8",
                "margin": "none"
            },
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "xs",
                "contents": [
                    {"type": "text", "text": f"前週比: {w_sign}{item['week_pct']}% ({display_week})", "size": "xxs", "color": w_color, "flex": 1},
                    {"type": "text", "text": f"年初来: {y_sign}{item['ytd_pct']}% ({display_ytd})", "size": "xxs", "color": y_color, "align": "end", "flex": 1}
                ]
            }
        ]

        if idx < len(market_data) - 1:
            row_contents.append({"type": "separator", "margin": "sm", "color": "#334155"})

        row = {
            "type": "box",
            "layout": "vertical",
            "margin": "sm",
            "contents": row_contents
        }
        rows.append(row)

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": "📊 主要マクロ指標サマリー", "color": "#38bdf8", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "世界株・米ハイテク・金・為替動向", "color": "#94a3b8", "size": "xxs", "margin": "xs"}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "12px",
            "contents": rows
        }
    }

def send_flex_carousel(title, top_stocks, pages_url, market_data=None):
    """指数カード ＋ 上位銘柄カードのカルーセルを配信"""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")

    if not token or not user_id:
        print("[WARN] LINE通知用の環境変数が設定されていません。通知をスキップします。")
        return

    bubbles = []

    # 1枚目: マーケット指数サマリーカード（データが存在する場合）
    if market_data:
        bubbles.append(create_market_bubble(market_data))

    # 2枚目以降: 厳選個別株カード（最大4銘柄）
    for idx, s in enumerate(top_stocks[:4], 1):
        a = s.get("analysis", {})
        tier = a.get("conviction_tier", "A")
        tier_label = {"S": "👑 Sランク超本命", "A": "⭐ Aランク有力", "B": "📌 Bランク監視"}.get(tier, "⭐ Aランク")
        moat = a.get("moat_rating", "MEDIUM")
        rs_str = f"RS:+{s.get('rs_rating', 0)}%"
        edge_tags = []
        if s.get("is_stage2"):
            edge_tags.append("🌊Stage2")
        if s.get("is_golden_cross"):
            edge_tags.append("✨GC初動")
        if s.get("is_sound_base"):
            edge_tags.append("📐ベース")
        if s.get("is_clean_margin"):
            edge_tags.append("💎需給クリーン")
        if s.get("is_earnings_imminent"):
            edge_tags.append("⚠️決算直前")
        elif s.get("is_post_earnings"):
            edge_tags.append("⚡決算通過")
        if s.get("is_ultra_light"):
            edge_tags.append(f"🎈浮動{s.get('float_mcap_oku')}億")
        if s.get("is_fresh_ipo"):
            edge_tags.append("🌱IPO黄金期")
        if s.get("is_vcp"):
            edge_tags.append("🔥VCP")
        if s.get("is_accelerating"):
            edge_tags.append("🚀成長加速")
        if s.get("is_early_inst"):
            edge_tags.append("💎機関初期")
        if s.get("is_net_cash"):
            edge_tags.append("💰無借金")
        if s.get("is_turnaround"):
            edge_tags.append("⚡黒字成長")
        edge_str = " ".join(edge_tags)
        sub_info = f"Moat:{moat} | {rs_str}" + (f" | {edge_str}" if edge_str else "")

        growth_story = a.get("growth_story", "チャート動向をチェックしてください。")
        if len(growth_story) > 115:
            growth_story = growth_story[:112] + "..."

        bubble = {
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#0f172a",
                "paddingAll": "12px",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": f"第{idx}位 {tier_label}", "color": "#10b981", "weight": "bold", "size": "sm", "flex": 7},
                            {"type": "text", "text": f"{a.get('score', '-')}点", "color": "#f59e0b", "weight": "bold", "size": "sm", "align": "end", "flex": 3}
                        ]
                    },
                    {"type": "text", "text": f"{s.get('code', '')} {s.get('name', '')}", "color": "#ffffff", "weight": "bold", "size": "md", "wrap": True, "margin": "xs"},
                    {"type": "text", "text": sub_info, "color": "#38bdf8", "size": "xxs", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "12px",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "現在値 / 時価", "size": "xs", "color": "#888888"},
                            {"type": "text", "text": f"{s.get('close', '-')}円 ({s.get('market_cap_oku', '-')}億)", "size": "xs", "weight": "bold", "align": "end"}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "xs",
                        "contents": [
                            {"type": "text", "text": "買値目安", "size": "xs", "color": "#888888"},
                            {"type": "text", "text": f"{a.get('entry_price', '-')}円", "size": "xs", "color": "#0284c7", "weight": "bold", "align": "end"}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "xs",
                        "contents": [
                            {"type": "text", "text": "損切ライン", "size": "xs", "color": "#888888"},
                            {"type": "text", "text": f"{a.get('stop_loss', '-')}円", "size": "xs", "color": "#ef4444", "weight": "bold", "align": "end"}
                        ]
                    },
                    {"type": "separator", "margin": "md"},
                    {
                        "type": "text",
                        "text": f"🚀 {growth_story}",
                        "size": "xxs",
                        "color": "#333333",
                        "wrap": True,
                        "margin": "md",
                        "maxLines": 4
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "株探チャート",
                            "uri": f"https://kabutan.jp/stock/chart?code={s.get('code', '')}"
                        },
                        "style": "secondary",
                        "height": "sm"
                    }
                ]
            }
        }
        bubbles.append(bubble)

    flex_contents = {
        "type": "carousel",
        "contents": bubbles
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": f"🎯【{title}】\n主要指数サマリーおよび今週の厳選候補カードです。\n全20銘柄はWebダッシュボードへ:\n{pages_url}"
            },
            {
                "type": "flex",
                "altText": "今週のマーケット指数＆厳選候補カード",
                "contents": flex_contents
            }
        ]
    }

    try:
        res = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            print("[INFO] LINE Flex Message（指数＋銘柄）送信成功。")
        else:
            print(f"[WARN] Flex送信失敗 (Status: {res.status_code}): {res.text}")
            send_notification(title, f"詳細レポートはこちら:\n{pages_url}")
    except Exception as e:
        print(f"[ERROR] Flex送信例外: {e}")
        send_notification(title, f"詳細レポートはこちら:\n{pages_url}")

def send_close_wrap_flex(date_str, stock_results, stop_alerts, breakout_alerts, rebound_alerts, pages_url):
    """東証大引けレビュー（15:40）のLINE Flex Message配信"""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")

    if not token or not user_id:
        return

    bubbles = []

    # 1枚目: アラート・シグナル確定カード
    alert_rows = []
    if stop_alerts:
        for a in stop_alerts[:3]:
            alert_rows.append({
                "type": "text", "text": a, "size": "xs", "color": "#f87171", "weight": "bold", "wrap": True, "margin": "xs"
            })
    if breakout_alerts:
        for a in breakout_alerts[:3]:
            alert_rows.append({
                "type": "text", "text": a, "size": "xs", "color": "#34d399", "weight": "bold", "wrap": True, "margin": "xs"
            })
    if rebound_alerts:
        for a in rebound_alerts[:3]:
            alert_rows.append({
                "type": "text", "text": a, "size": "xs", "color": "#60a5fa", "weight": "bold", "wrap": True, "margin": "xs"
            })
    if not alert_rows:
        alert_rows.append({
            "type": "text", "text": "本日、損切り到達や急変銘柄はありません。健全推移中。", "size": "xs", "color": "#94a3b8", "margin": "sm"
        })

    bubble_alerts = {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": f"🌆 東証大引けレビュー ({date_str})", "color": "#f59e0b", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "本日の損益・手仕舞い・ブレイク判定", "color": "#94a3b8", "size": "xxs", "margin": "xs"}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "12px",
            "contents": alert_rows
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "8px",
            "contents": [
                {
                    "type": "button",
                    "action": {"type": "uri", "label": "Webダッシュボードを開く", "uri": pages_url},
                    "style": "primary",
                    "color": "#38bdf8",
                    "height": "sm"
                }
            ]
        }
    }
    bubbles.append(bubble_alerts)

    # 2枚目: 当日騰落ランキングカード
    rank_rows = []
    for r in stock_results[:6]:
        sign = "+" if r["day_pct"] > 0 else ""
        color = "#10b981" if r["day_pct"] >= 0 else "#ef4444"
        rank_rows.append({
            "type": "box",
            "layout": "horizontal",
            "margin": "xs",
            "contents": [
                {"type": "text", "text": f"{r['tier_icon']}{r['code']} {r['name']}", "size": "xs", "color": "#f8fafc", "flex": 6},
                {"type": "text", "text": f"{sign}{r['day_pct']}%", "size": "xs", "color": color, "weight": "bold", "align": "end", "flex": 4}
            ]
        })

    bubble_ranks = {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": "📊 監視銘柄 騰落ランキング", "color": "#38bdf8", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "本日の値動き上位サマリー", "color": "#94a3b8", "size": "xxs", "margin": "xs"}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "12px",
            "contents": rank_rows
        }
    }
    bubbles.append(bubble_ranks)

    flex_contents = {
        "type": "carousel",
        "contents": bubbles
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "flex",
                "altText": f"🌆 東証大引けレビュー ({date_str})",
                "contents": flex_contents
            }
        ]
    }

    try:
        res = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            print("[INFO] 大引けレビュー LINE Flex Message送信成功。")
        else:
            print(f"[WARN] Flex送信失敗 (Status: {res.status_code}): {res.text}")
    except Exception as e:
        print(f"[ERROR] Flex送信例外: {e}")

def send_daily_gate_flex(status, reason, action_guideline, market_snapshot, risk_alerts, entry_alerts, pages_url="https://sei1r0.github.io/tenbagger-hunter/"):
    """朝08:35 地合いゲート ＆ 最注目アクション銘柄のLINE Flex Message配信"""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")

    if not token or not user_id:
        return

    status_theme = {
        "GREEN": {"label": "🟢 リスクオン（買付許可）", "color": "#10b981", "bg": "#064e3b", "cash": "10〜30% (積極投資)"},
        "YELLOW": {"label": "🟡 警戒局面（ロット半減）", "color": "#f59e0b", "bg": "#78350f", "cash": "50〜70% (現金温存)"},
        "RED": {"label": "🔴 リスクオフ（新規買停止）", "color": "#ef4444", "bg": "#7f1d1d", "cash": "80〜100% (全面待機)"}
    }.get(status, {"label": "🟡 警戒局面", "color": "#f59e0b", "bg": "#78350f", "cash": "50〜70% (現金温存)"})

    bubbles = []

    # 1枚目: 地合いゲート判定 ＆ 米国市場指標
    nasdaq_pct = market_snapshot.get('Nasdaq', {}).get('pct_change', 0.0)
    sp500_pct = market_snapshot.get('S&P500', {}).get('pct_change', 0.0)
    russell_pct = market_snapshot.get('Russell2000', {}).get('pct_change', 0.0)
    tnx_val = market_snapshot.get('US_10Y_Yield', {}).get('close', '-')
    usdjpy_val = market_snapshot.get('USD_JPY', {}).get('close', '-')

    n_sign = "+" if nasdaq_pct > 0 else ""
    s_sign = "+" if sp500_pct > 0 else ""
    r_sign = "+" if russell_pct > 0 else ""

    bubble_gate = {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": status_theme["bg"],
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": "🚦 朝の地合いゲート判定 (08:35)", "color": "#ffffff", "weight": "bold", "size": "xs"},
                {"type": "text", "text": status_theme["label"], "color": "#ffffff", "weight": "bold", "size": "md", "margin": "xs"}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "📋 判定理由:", "size": "xs", "color": "#94a3b8", "weight": "bold"},
                        {"type": "text", "text": reason or "マクロ指標に基づき算出", "size": "xs", "color": "#f8fafc", "wrap": True, "margin": "xs"}
                    ]
                },
                {"type": "separator", "margin": "sm", "color": "#334155"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "sm",
                    "contents": [
                        {"type": "text", "text": "🎯 行動方針:", "size": "xs", "color": status_theme["color"], "weight": "bold"},
                        {"type": "text", "text": action_guideline or "指値位置を確認してください", "size": "xs", "color": "#f8fafc", "wrap": True, "margin": "xs"},
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "xs",
                            "contents": [
                                {"type": "text", "text": "🛡️ 推奨Cash比率:", "size": "xxs", "color": "#94a3b8", "flex": 5},
                                {"type": "text", "text": status_theme["cash"], "size": "xxs", "color": status_theme["color"], "weight": "bold", "align": "end", "flex": 7}
                            ]
                        }
                    ]
                },
                {"type": "separator", "margin": "sm", "color": "#334155"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "sm",
                    "contents": [
                        {"type": "text", "text": "🇺🇸 前夜の主要マクロ指標", "size": "xxs", "color": "#64748b", "weight": "bold"},
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "xs",
                            "contents": [
                                {"type": "text", "text": "Nasdaq", "size": "xxs", "color": "#94a3b8", "flex": 5},
                                {"type": "text", "text": f"{n_sign}{nasdaq_pct}%", "size": "xxs", "color": "#10b981" if nasdaq_pct >= 0 else "#ef4444", "weight": "bold", "align": "end", "flex": 5}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "xs",
                            "contents": [
                                {"type": "text", "text": "ラッセル2000(米中小型)", "size": "xxs", "color": "#94a3b8", "flex": 6},
                                {"type": "text", "text": f"{r_sign}{russell_pct}%", "size": "xxs", "color": "#10b981" if russell_pct >= 0 else "#ef4444", "weight": "bold", "align": "end", "flex": 4}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "xs",
                            "contents": [
                                {"type": "text", "text": "米10年金利 / ドル円", "size": "xxs", "color": "#94a3b8", "flex": 6},
                                {"type": "text", "text": f"{tnx_val}% / {usdjpy_val}円", "size": "xxs", "color": "#38bdf8", "weight": "bold", "align": "end", "flex": 6}
                            ]
                        }
                    ]
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "8px",
            "contents": [
                {
                    "type": "button",
                    "action": {"type": "uri", "label": "ダッシュボードを開く", "uri": pages_url},
                    "style": "primary",
                    "color": "#0284c7",
                    "height": "sm"
                }
            ]
        }
    }
    bubbles.append(bubble_gate)

    # 2枚目: 本日の最注目アクション銘柄
    action_items = []
    if entry_alerts:
        action_items.append({"type": "text", "text": "🎯 買値圏・押し目エントリー機会", "size": "xs", "color": "#38bdf8", "weight": "bold", "margin": "xs"})
        for e in entry_alerts[:3]:
            action_items.append({"type": "text", "text": e, "size": "xxs", "color": "#34d399", "wrap": True, "margin": "xs"})
    if risk_alerts:
        action_items.append({"type": "text", "text": "⚠️ 損切り・警戒シグナル", "size": "xs", "color": "#f87171", "weight": "bold", "margin": "sm"})
        for r in risk_alerts[:3]:
            action_items.append({"type": "text", "text": r, "size": "xxs", "color": "#f87171", "wrap": True, "margin": "xs"})

    if not action_items:
        action_items.append({
            "type": "text",
            "text": "本日、急変や損切り到達銘柄はありません。全候補が健全ベースを維持しています。",
            "size": "xs",
            "color": "#94a3b8",
            "wrap": True,
            "margin": "sm"
        })

    bubble_actions = {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0f172a",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": "🔥 本日の注目アクション銘柄", "color": "#f59e0b", "weight": "bold", "size": "sm"},
                {"type": "text", "text": "ブレイク接近・25MA押し目トリガー", "color": "#94a3b8", "size": "xxs", "margin": "xs"}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e293b",
            "paddingAll": "12px",
            "contents": action_items
        }
    }
    bubbles.append(bubble_actions)

    flex_contents = {
        "type": "carousel",
        "contents": bubbles
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "flex",
                "altText": f"🚦 朝の地合いゲート判定: {status_theme['label']}",
                "contents": flex_contents
            }
        ]
    }

    try:
        res = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            print("[INFO] 朝の地合いゲート LINE Flex Message送信成功。")
            return True
        else:
            print(f"[WARN] Flex送信失敗 (Status: {res.status_code}): {res.text}")
            return False
    except Exception as e:
        print(f"[ERROR] Flex送信例外: {e}")
        return False