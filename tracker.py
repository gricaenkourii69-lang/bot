import json
import os

TRACKER_FILE = "tracker.json"

STATUSES = {
    "sent":    "📤 Відклик надіслано",
    "replied": "💬 Відповіли",
    "won":     "🏆 Виграно",
    "lost":    "❌ Програно",
    "working": "🔧 В роботі",
}

def load_tracker():
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_tracker(data):
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def set_status(pid, title, url, status, budget=""):
    data = load_tracker()
    data[str(pid)] = {
        "title": title,
        "url": url,
        "status": status,
        "budget": budget,
        "updated": __import__("datetime").datetime.now().strftime("%d.%m %H:%M")
    }
    save_tracker(data)

def get_all():
    return load_tracker()

def format_tracker():
    data = load_tracker()
    if not data:
        return "📋 Трекер порожній."

    result = "📋 <b>Трекер замовлень:</b>\n\n"
    by_status = {}
    for pid, info in data.items():
        s = info.get("status", "sent")
        by_status.setdefault(s, []).append(info)

    for status, label in STATUSES.items():
        items = by_status.get(status, [])
        if items:
            result += f"\n{label}:\n"
            for item in items:
                result += f"  • <a href='{item['url']}'>{item['title'][:40]}</a>"
                if item.get("budget"):
                    result += f" — {item['budget']}"
                result += f"\n"
    return result
