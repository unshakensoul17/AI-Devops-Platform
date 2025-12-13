import os
import httpx
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

async def send_telegram_alert(message: str):
    """
    Send alert to Telegram
    """
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Telegram credentials not set")
        return False

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(TELEGRAM_API, json=payload)
        return True
    except Exception as e:
        logger.error(f"Telegram alert failed: {e}")
        return False
