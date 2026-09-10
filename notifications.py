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

async def _get(path, params=None):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{API_URL}{path}", headers=HEADERS,
                params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("data", [])
                return []
    except Exception:
        return []

async def get_threads():
    return await _get("/threads")

async def get_my_projects():
    """Мої активні проекти як фрілансера"""
    return await _get("/my/projects/freelancer")

async def get_my_bids():
    """Мої ставки"""
    return await _get("/my/bids")

async def get_profile():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{API_URL}/my/profile", headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("data", {})
                return {}
    except Exception:
        return {}

def format_thread(thread):
    attrs = thread.get("attributes", {})
    tid   = str(thread.get("id", ""))
    subj  = attrs.get("subject") or "Без теми"
    unread = attrs.get("unread_count", 0) or 0
    participants = attrs.get("participants") or []
    other = next((p for p in participants if not p.get("is_me")), {})
    name  = other.get("login", "Невідомо")
    last  = attrs.get("last_message") or {}
    body  = (last.get("body") or last.get("text") or "немає тексту")[:300]
    badge = "🔴 НЕПРОЧИТАНО\n" if unread else ""
    url   = f"https://freelancehunt.com/mailbox/thread/{tid}"
    return (
        f"{badge}"
        f"📨 <b>{subj}</b>\n"
        f"👤 {name}\n"
        f"💬 <i>{body}</i>\n"
        f"🔗 <a href='{url}'>Відкрити листування</a>"
    ), bool(unread)

def format_bid(bid):
    attrs = bid.get("attributes", {})
    project = attrs.get("project") or {}
    title   = project.get("name") or "Без назви"
    pid     = project.get("id") or ""
    amount  = attrs.get("amount") or 0
    currency = attrs.get("currency") or "UAH"
    days    = attrs.get("days") or 0
    status  = attrs.get("status") or "pending"
    url     = f"https://freelancehunt.com/project/{pid}.html"

    status_icon = {
        "pending":  "⏳ Очікує",
        "accepted": "✅ Прийнято",
        "rejected": "❌ Відхилено",
        "winner":   "🏆 Виграно!",
    }.get(status, status)

    return (
        f"📤 <b>{title}</b>\n"
        f"💰 {amount} {currency} · 📅 {days} днів\n"
        f"Статус: {status_icon}\n"
        f"🔗 <a href='{url}'>Проект</a>"
    )
