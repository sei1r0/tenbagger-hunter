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