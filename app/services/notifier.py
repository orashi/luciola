import httpx

from app.settings import settings


def notify(text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    httpx.post(url, json={"chat_id": settings.telegram_chat_id, "text": text}, timeout=15)
