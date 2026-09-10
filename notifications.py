import aiohttp
import os
import json

FREELANCEHUNT_TOKEN = os.getenv("FREELANCEHUNT_TOKEN")
API_URL = "https://api.freelancehunt.com/v2"
HEADERS = {
    "Authorization": f"Bearer {FREELANCEHUNT_TOKEN}",
    "Content-Type": "application/json",
}

NOTIF_FILE = "last_notif.json"

def load_last_notif():
    if os.path.exists(NOTIF_FILE):
        with open(NOTIF_FILE) as f:
            return json.load(f)
    return {"thread_id": None, "feed_id": None}

def save_last_notif(data):
    with open(NOTIF_FILE, "w") as f:
        json.dump(data, f)

async def get_threads():
    """Получить личные сообщения (треды)"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API_URL}/threads", headers=HEADERS,
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return []
                data = await r.json()
                return data.get("data", [])
    except Exception:
        return []

async def get_feed():
    """Получить ленту уведомлений"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API_URL}/my/feed", headers=HEADERS,
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return []
                data = await r.json()
                return data.get("data", [])
    except Exception:
        return []

async def get_profile():
    """Получить профиль пользователя"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API_URL}/my/profile", headers=HEADERS,
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return {}
                data = await r.json()
                return data.get("data", {})
    except Exception:
        return {}

def format_thread(thread):
    attrs = thread.get("attributes", {})
    tid   = thread.get("id", "")
    subj  = attrs.get("subject") or "Без теми"
    unread = attrs.get("unread_count", 0)
    participants = attrs.get("participants") or []
    other = next((p for p in participants if not p.get("is_me")), {})
    name  = other.get("login", "Невідомо")
    last  = attrs.get("last_message", {}) or {}
    body  = (last.get("body") or "")[:200]
    badge = "🔴 " if unread else ""
    url   = f"https://freelancehunt.com/mailbox/thread/{tid}"
    return (
        f"{badge}<b>{subj}</b>\n"
        f"👤 {name}\n"
        f"💬 <i>{body}</i>\n"
        f"🔗 <a href='{url}'>Відкрити</a>"
    ), bool(unread)

def format_feed_item(item):
    attrs = item.get("attributes", {})
    itype = attrs.get("type", "")
    body  = attrs.get("body") or attrs.get("text") or ""
    url   = attrs.get("url") or ""

    icons = {
        "bid":     "📤 Нова ставка",
        "review":  "⭐ Відгук",
        "project": "📋 Проект",
        "award":   "🏆 Обрано виконавцем",
        "message": "💬 Повідомлення",
    }
    label = icons.get(itype, "🔔 Сповіщення")
    link  = f"\n🔗 <a href='{url}'>Перейти</a>" if url else ""
    return f"{label}\n<i>{body[:200]}</i>{link}"
