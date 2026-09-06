import os
import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

def send_notification(title, message):
    """従来のテキスト通知（フォールバック用）"""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")

    if not token or not user_id:
        print("[WARN] LINE通知用の環境変数が設定されていません。通知をスキップします。")
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": f"【{title}】\n\n{message}"
            }
        ]
    }

    try:
        res = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            print("[INFO] LINEへのプッシュ通知が正常に送信されました。")
        else:
            print(f"[WARN] LINE通知の送信に失敗しました (Status: {res.status_code}): {res.text}")
    except Exception as e:
        print(f"[ERROR] LINE通知送信例外: {e}")

def send_flex_carousel(title, top_stocks, pages_url):
    """上位銘柄をカード型（Flex Message）で美しく配信"""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")

    if not token or not user_id:
        return

    bubbles = []
    for idx, s in enumerate(top_stocks, 1):
        a = s["analysis"]
        tags = " / ".join(a.get("theme_tags", ["注目成長株"]))
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
                        "type": "text",
                        "text": f"第{idx}位  ★スコア {a['score']}点",
                        "color": "#10b981",
                        "weight": "bold",
                        "size": "sm"
                    },
                    {
                        "type": "text",
                        "text": f"{s['code']} {s['name']}",
                        "color": "#ffffff",
                        "weight": "bold",
                        "size": "md",
                        "wrap": True
                    },
                    {
                        "type": "text",
                        "text": tags,
                        "color": "#38bdf8",
                        "size": "xxs",
                        "margin": "xs"
                    }
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
                            {"type": "text", "text": "現在値", "size": "xs", "color": "#888888"},
                            {"type": "text", "text": f"{s['close']}円", "size": "xs", "weight": "bold", "align": "end"}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "xs",
                        "contents": [
                            {"type": "text", "text": "買値目安", "size": "xs", "color": "#888888"},
                            {"type": "text", "text": f"{a['entry_price']}円", "size": "xs", "color": "#0284c7", "weight": "bold", "align": "end"}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "xs",
                        "contents": [
                            {"type": "text", "text": "損切ライン", "size": "xs", "color": "#888888"},
                            {"type": "text", "text": f"{a['stop_loss']}円", "size": "xs", "color": "#ef4444", "weight": "bold", "align": "end"}
                        ]
                    },
                    {
                        "type": "separator",
                        "margin": "md"
                    },
                    {
                        "type": "text",
                        "text": a["growth_story"],
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
                            "uri": f"https://kabutan.jp/stock/chart?code={s['code']}"
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
        "contents": bubbles[:5]  # 最大5枚カルーセル
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
                "text": f"🎯【{title}】\n今週の厳選テンバガー候補上位カードです。\n全銘柄はWebダッシュボードへ:\n{pages_url}"
            },
            {
                "type": "flex",
                "altText": "今週のテンバガー厳選候補カード",
                "contents": flex_contents
            }
        ]
    }

    try:
        res = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            print("[INFO] LINE Flex Message カル―セル送信に成功しました。")
        else:
            print(f"[WARN] Flex送信失敗、テキストフォールバック中: {res.text}")
            # エラー時は従来のテキスト送信にフォールバック
            send_notification(title, f"詳細レポート: {pages_url}")
    except Exception as e:
        print(f"[ERROR] Flex Message 送信例外: {e}")