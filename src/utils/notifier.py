import os
import requests

def send_notification(title: str, message: str, color_level: str = "INFO"):
    """
    LINE Messaging API を利用した個人宛プッシュ通知
    """
    channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")

    if not channel_access_token or not user_id:
        print("[WARN] LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が未設定のため、通知をスキップします。")
        return

    # ステータスに応じたアイコン絵文字
    status_icons = {
        "GREEN": "🟢",
        "YELLOW": "🟡",
        "RED": "🔴",
        "INFO": "ℹ️"
    }
    icon = status_icons.get(color_level, "📌")

    endpoint = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_access_token}"
    }

    text_content = f"{icon} 【{title}】\n\n{message}"

    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": text_content
            }
        ]
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            print("[INFO] LINEへのプッシュ通知が正常に送信されました。")
        else:
            print(f"[ERROR] LINE通知送信失敗: HTTP {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[ERROR] LINE通知例外エラー: {type(e).__name__}")