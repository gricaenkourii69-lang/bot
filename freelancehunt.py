import aiohttp
import os
from currency import format_budget

FREELANCEHUNT_TOKEN = os.getenv("FREELANCEHUNT_TOKEN")
API_URL = "https://api.freelancehunt.com/v2"

HEADERS = {
    "Authorization": f"Bearer {FREELANCEHUNT_TOKEN}",
    "Content-Type": "application/json",
}

async def get_latest_projects():
    """Отримати останні відкриті проекти"""
    params = {"page[limit]": 25, "filter[status]": "open"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/projects",
                headers=HEADERS,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("data", [])
    except Exception:
        return []

async def format_project(project):
    """Форматувати проект для Telegram"""
    attrs = project.get("attributes", {})
    pid   = project.get("id", "")

    title       = attrs.get("name", "Без назви")
    description = attrs.get("description", "Опис відсутній")
    bid_count   = attrs.get("bid_count", 0)
    url         = f"https://freelancehunt.com/project/{pid}.html"

    # Бюджет з конвертацією
    budget_obj  = attrs.get("budget") or {}
    amount      = budget_obj.get("amount") or 0
    currency    = budget_obj.get("currency", "UAH")
    budget_str  = await format_budget(amount, currency)

    # Навички
    skills = [sk.get("name", "") for sk in attrs.get("skills", [])]
    skills_str = ", ".join(skills) if skills else "Не вказано"

    # Замовник
    employer    = attrs.get("employer") or {}
    emp_name    = employer.get("login", "Невідомо")
    emp_rating  = employer.get("rating", 0)
    emp_icon    = "⭐" if emp_rating and emp_rating >= 4 else ""

    text = (
        f"🆕 <b>{title}</b>\n\n"
        f"💰 Бюджет: <b>{budget_str}</b>\n"
        f"🛠 Навички: {skills_str}\n"
        f"👤 Замовник: {emp_name} {emp_icon}\n"
        f"📊 Ставок: {bid_count}\n\n"
        f"📋 <i>{description[:400]}{'...' if len(description) > 400 else ''}</i>\n\n"
        f"🔗 <a href='{url}'>Відкрити проект</a>"
    )

    return text, title, description, skills_str, url, budget_str
