import aiohttp
import json
import os

FREELANCEHUNT_TOKEN = os.getenv("FREELANCEHUNT_TOKEN")
API_URL = "https://api.freelancehunt.com/v2"

HEADERS = {
    "Authorization": f"Bearer {FREELANCEHUNT_TOKEN}",
    "Content-Type": "application/json",
}

# Навыки по которым ищем заказы
SKILLS = [
    "HTML/CSS",
    "JavaScript",
    "Python",
    "Telegram Bot",
    "Website Development",
    "PHP",
    "React",
    "Node.js",
]

async def get_latest_projects(skill_filter=None):
    """Получить последние открытые проекты с фильтром по навыкам"""
    params = {
        "page[limit]": 20,
        "filter[status]": "open",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{API_URL}/projects",
            headers=HEADERS,
            params=params
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            projects = data.get("data", [])
            return projects

async def get_project_details(project_id):
    """Получить детали конкретного проекта"""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{API_URL}/projects/{project_id}",
            headers=HEADERS,
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return data.get("data", {})

def format_project(project):
    """Форматировать проект для отображения в Telegram"""
    attrs = project.get("attributes", {})
    pid = project.get("id", "")

    title = attrs.get("name", "Без назви")
    description = attrs.get("description", "Опис відсутній")
    budget_min = attrs.get("budget", {}).get("amount", None) if attrs.get("budget") else None
    currency = attrs.get("budget", {}).get("currency", "UAH") if attrs.get("budget") else "UAH"
    bid_count = attrs.get("bid_count", 0)
    url = f"https://freelancehunt.com/project/{pid}.html"

    skills = []
    for skill in attrs.get("skills", []):
        skills.append(skill.get("name", ""))

    skills_str = ", ".join(skills) if skills else "Не вказано"

    budget_str = f"{budget_min} {currency}" if budget_min else "Договірна"

    text = (
        f"🆕 <b>{title}</b>\n\n"
        f"💰 Бюджет: <b>{budget_str}</b>\n"
        f"🛠 Навички: {skills_str}\n"
        f"📊 Ставок: {bid_count}\n\n"
        f"📋 <i>{description[:500]}{'...' if len(description) > 500 else ''}</i>\n\n"
        f"🔗 <a href='{url}'>Відкрити проект</a>"
    )

    return text, title, description, skills_str, url
