import os
import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

def send_notification(title, message):
    """テキスト形式による通知（フォールバック用）"""
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
            print("[INFO] LINE通知（テキスト）が正常に送信されました。")
        else:
            print(f"[WARN] LINE通知送信失敗 (Status: {res.status_code}): {res.text}")
    except Exception as e:
        print(f"[ERROR] LINE通知送信例外: {e}")

def send_flex_carousel(title, top_stocks, pages_url):
    """上位銘柄をカード型カルーセル（Flex Message）で配信"""
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")

    if not token or not user_id:
        print("[WARN] LINE通知用の環境変数が設定されていません。通知をスキップします。")
        return

    # 候補が0件の場合はテキスト通知で安全に案内
    if not top_stocks:
        print("[INFO] 候補銘柄が0件のため、通常テキスト通知に切り替えます。")
        send_notification(
            title,
            f"今週は抽出条件に合致する銘柄がありませんでした。\n\nWebダッシュボード:\n{pages_url}"
        )
        return

    bubbles = []
    for idx, s in enumerate(top_stocks, 1):
        a = s.get("analysis", {})
        tags = " / ".join(a.get("theme_tags", [s.get("sector", "注目株")]))
        growth_story = a.get("growth_story", "最新チャートと売買代金の動向を確認してください。")

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
                        "text": f"第{idx}位  ★スコア {a.get('score', '-')}点",
                        "color": "#10b981",
                        "weight": "bold",
                        "size": "sm"
                    },
                    {
                        "type": "text",
                        "text": f"{s.get('code', '')} {s.get('name', '')}",
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
                            {"type": "text", "text": f"{s.get('close', '-')}円", "size": "xs", "weight": "bold", "align": "end"}
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
                    {
                        "type": "separator",
                        "margin": "md"
                    },
                    {
                        "type": "text",
                        "text": growth_story,
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

    # LINEカルーセル形式（最大5枚まで）
    flex_contents = {
        "type": "carousel",
        "contents": bubbles[:5]
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
                "text": f"🎯【{title}】\n今週の厳選候補カードです。\n全銘柄はダッシュボードへ:\n{pages_url}"
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
            print(f"[WARN] Flex送信失敗 (Status: {res.status_code}): {res.text}。テキスト通知へフォールバックします。")
            send_notification(title, f"詳細レポートはこちら:\n{pages_url}")
    except Exception as e:
        print(f"[ERROR] Flex Message 送信例外: {e}。テキスト通知へフォールバックします。")
        send_notification(title, f"詳細レポートはこちら:\n{pages_url}")