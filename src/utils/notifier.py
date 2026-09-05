import os
import requests

def send_notification(title: str, message: str, color_level: str = "INFO"):
    """
    Webhookへの通知配信（平文ログ露出防止策付き）
    """
    webhook_url = os.getenv("NOTIFICATION_WEBHOOK")
    if not webhook_url:
        print("[WARN] NOTIFICATION_WEBHOOK が未設定のため、通知をスキップします。")
        return

    # Discord Webhook向け形式のペイロード（汎用的なJSON構造）
    color_map = {
        "GREEN": 0x2ECC71,
        "YELLOW": 0xF1C40F,
        "RED": 0xE74C3C,
        "INFO": 0x3498DB
    }
    
    payload = {
        "content": f"**【{title}】**\n{message}",
        "embeds": [
            {
                "title": title,
                "description": message,
                "color": color_map.get(color_level, 0x3498DB)
            }
        ]
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        if response.status_code not in (200, 204):
            # 万が一のSlack等フォーマット対応（text単一送信フォールバック）
            requests.post(webhook_url, json={"text": f"*{title}*\n{message}"}, timeout=10)
    except Exception as e:
        print(f"[ERROR] 通知送信失敗（URLは秘匿）: {type(e).__name__}")