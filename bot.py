import asyncio
import logging
import json
import os
from datetime import datetime, time
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from freelancehunt import get_latest_projects, format_project
from ai_reply import generate_reply

# ── Конфиг ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MY_CHAT_ID     = int(os.getenv("MY_CHAT_ID"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "120"))

# ── Файлы хранилищ ───────────────────────────────────────
SEEN_FILE      = "seen_projects.json"
FAVORITES_FILE = "favorites.json"
SETTINGS_FILE  = "settings.json"
STATS_FILE     = "stats.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher()

# ── Утилиты хранилища ────────────────────────────────────
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_seen():      return set(load_json(SEEN_FILE, []))
def save_seen(s):     save_json(SEEN_FILE, list(s))
def load_favorites(): return load_json(FAVORITES_FILE, [])
def save_favorites(f): save_json(FAVORITES_FILE, f)

def load_settings():
    return load_json(SETTINGS_FILE, {
        "min_budget": 0,
        "skills": ["HTML", "CSS", "JavaScript", "Python", "Telegram", "верстка", "бот", "сайт", "лендинг", "React", "Node"],
        "paused": False
    })

def save_settings(s): save_json(SETTINGS_FILE, s)

def load_stats():
    return load_json(STATS_FILE, {
        "total_seen": 0,
        "replies_generated": 0,
        "favorites_count": 0,
        "skipped": 0
    })

def save_stats(s): save_json(STATS_FILE, s)

def inc_stat(key, val=1):
    s = load_stats()
    s[key] = s.get(key, 0) + val
    save_stats(s)

# ── Фильтрация проектов ──────────────────────────────────
def is_relevant(project, settings):
    attrs = project.get("attributes", {})

    # Фильтр по бюджету
    budget = attrs.get("budget", {})
    if budget:
        amount = budget.get("amount", 0) or 0
        if amount > 0 and amount < settings.get("min_budget", 0):
            return False

    # Фильтр по навыкам
    skills_filter = [s.lower() for s in settings.get("skills", [])]
    if not skills_filter:
        return True

    title = (attrs.get("name") or "").lower()
    desc  = (attrs.get("description") or "").lower()
    proj_skills = " ".join(
        (sk.get("name") or "").lower()
        for sk in attrs.get("skills", [])
    )
    text = f"{title} {desc} {proj_skills}"

    return any(kw in text for kw in skills_filter)

# ── Клавиатура для проекта ───────────────────────────────
def project_keyboard(pid, title, skills, description, url):
    b = InlineKeyboardBuilder()
    safe = lambda s: str(s)[:60].replace(":", "·")
    b.row(
        InlineKeyboardButton(text="✍️ Відклик", callback_data=f"reply:{safe(pid)}:{safe(title)}:{safe(skills)}:{safe(description)}"),
    )
    b.row(
        InlineKeyboardButton(text="⭐ Зберегти", callback_data=f"fav:{pid}"),
        InlineKeyboardButton(text="🚫 Пропустити", callback_data=f"skip:{pid}"),
    )
    b.row(InlineKeyboardButton(text="🔗 Відкрити", url=url))
    return b.as_markup()

# ── /start ───────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    await msg.answer(
        "👋 Привіт! Я <b>FreelanceRadar</b> — твій помічник для пошуку замовлень на Freelancehunt.\n\n"
        "<b>Команди:</b>\n"
        "/check — перевірити зараз\n"
        "/skills — переглянути/змінити навички\n"
        "/budget — мінімальний бюджет\n"
        "/favorites — збережені замовлення\n"
        "/stats — статистика\n"
        "/pause — пауза / продовжити моніторинг\n"
        "/clear — очистити історію\n"
        "/help — допомога"
    )

# ── /help ────────────────────────────────────────────────
@dp.message(Command("help"))
async def cmd_help(msg: types.Message):
    await msg.answer(
        "<b>Як користуватись:</b>\n\n"
        "Бот кожні 2 хвилини перевіряє нові замовлення.\n"
        "Якщо замовлення відповідає твоїм навичкам — надсилає картку.\n\n"
        "✍️ <b>Відклик</b> — AI генерує персональний відклик\n"
        "⭐ <b>Зберегти</b> — додає в обране\n"
        "🚫 <b>Пропустити</b> — позначає як небажане\n\n"
        "<b>Налаштування:</b>\n"
        "/skills HTML CSS Python — встановити навички\n"
        "/budget 500 — мінімальний бюджет в UAH\n"
        "/pause — зупинити/відновити моніторинг"
    )

# ── /check ───────────────────────────────────────────────
@dp.message(Command("check"))
async def cmd_check(msg: types.Message):
    await msg.answer("🔍 Перевіряю нові замовлення...")
    await check_new_projects(force=True)

# ── /skills ──────────────────────────────────────────────
@dp.message(Command("skills"))
async def cmd_skills(msg: types.Message):
    settings = load_settings()
    args = msg.text.strip().split()[1:]

    if args:
        settings["skills"] = args
        save_settings(settings)
        await msg.answer(f"✅ Навички оновлено:\n<code>{', '.join(args)}</code>")
    else:
        current = settings.get("skills", [])
        await msg.answer(
            f"🛠 <b>Поточні навички:</b>\n<code>{', '.join(current)}</code>\n\n"
            f"Щоб змінити: /skills HTML CSS Python Telegram"
        )

# ── /budget ──────────────────────────────────────────────
@dp.message(Command("budget"))
async def cmd_budget(msg: types.Message):
    settings = load_settings()
    args = msg.text.strip().split()[1:]

    if args and args[0].isdigit():
        settings["min_budget"] = int(args[0])
        save_settings(settings)
        await msg.answer(f"✅ Мінімальний бюджет: <b>{args[0]} UAH</b>")
    else:
        await msg.answer(
            f"💰 <b>Мінімальний бюджет:</b> {settings.get('min_budget', 0)} UAH\n\n"
            f"Щоб змінити: /budget 500"
        )

# ── /pause ───────────────────────────────────────────────
@dp.message(Command("pause"))
async def cmd_pause(msg: types.Message):
    settings = load_settings()
    settings["paused"] = not settings.get("paused", False)
    save_settings(settings)
    status = "⏸ Моніторинг призупинено" if settings["paused"] else "▶️ Моніторинг відновлено"
    await msg.answer(status)

# ── /favorites ───────────────────────────────────────────
@dp.message(Command("favorites"))
async def cmd_favorites(msg: types.Message):
    favs = load_favorites()
    if not favs:
        await msg.answer("⭐ Обране порожнє.\nНатисни ⭐ під замовленням щоб зберегти.")
        return

    text = "⭐ <b>Збережені замовлення:</b>\n\n"
    for i, f in enumerate(favs[-10:], 1):
        text += f"{i}. <a href='{f['url']}'>{f['title']}</a> — {f['budget']}\n"

    await msg.answer(text, disable_web_page_preview=True)

# ── /stats ───────────────────────────────────────────────
@dp.message(Command("stats"))
async def cmd_stats(msg: types.Message):
    stats    = load_stats()
    settings = load_settings()
    seen     = load_seen()
    favs     = load_favorites()

    await msg.answer(
        "📊 <b>Статистика:</b>\n\n"
        f"👁 Переглянуто замовлень: <b>{len(seen)}</b>\n"
        f"✍️ Відгуків згенеровано: <b>{stats.get('replies_generated', 0)}</b>\n"
        f"⭐ Збережено в обране: <b>{len(favs)}</b>\n"
        f"🚫 Пропущено: <b>{stats.get('skipped', 0)}</b>\n\n"
        f"⚙️ <b>Налаштування:</b>\n"
        f"💰 Мін. бюджет: {settings.get('min_budget', 0)} UAH\n"
        f"🛠 Навички: {', '.join(settings.get('skills', []))}\n"
        f"{'⏸ На паузі' if settings.get('paused') else '▶️ Активний'}"
    )

# ── /clear ───────────────────────────────────────────────
@dp.message(Command("clear"))
async def cmd_clear(msg: types.Message):
    save_seen(set())
    await msg.answer("🗑 Історія очищена. Наступна перевірка покаже всі актуальні проекти.")

# ── Callback: відклик ────────────────────────────────────
@dp.callback_query(F.data.startswith("reply:"))
async def cb_reply(call: types.CallbackQuery):
    await call.answer("⏳ Генерую відклик...")
    parts = call.data.split(":", 4)
    if len(parts) < 5:
        await call.message.answer("⚠️ Помилка.")
        return

    _, pid, title, skills, description = parts
    await call.message.answer("✍️ Генерую відклик через AI...")
    reply_text = await generate_reply(title, description, skills)
    inc_stat("replies_generated")

    b = InlineKeyboardBuilder()
    b.button(text="📋 Скопіювати (виділи вище)", callback_data="noop")
    await call.message.answer(
        f"💬 <b>Готовий відклик:</b>\n\n{reply_text}",
        reply_markup=b.as_markup()
    )

# ── Callback: обране ─────────────────────────────────────
@dp.callback_query(F.data.startswith("fav:"))
async def cb_fav(call: types.CallbackQuery):
    pid = call.data.split(":", 1)[1]
    # Знаходимо дані з тексту повідомлення
    text = call.message.text or call.message.caption or ""
    lines = text.split("\n")
    title  = lines[0].replace("🆕 ", "").strip() if lines else pid
    url    = ""
    budget = ""
    for line in lines:
        if "Бюджет:" in line:
            budget = line.replace("💰 Бюджет:", "").strip()

    favs = load_favorites()
    if any(f["id"] == pid for f in favs):
        await call.answer("Вже збережено ⭐")
        return

    favs.append({"id": pid, "title": title, "budget": budget, "url": f"https://freelancehunt.com/project/{pid}.html"})
    save_favorites(favs)
    await call.answer("⭐ Збережено в обране!")

# ── Callback: пропустити ─────────────────────────────────
@dp.callback_query(F.data.startswith("skip:"))
async def cb_skip(call: types.CallbackQuery):
    inc_stat("skipped")
    await call.answer("🚫 Пропущено")
    await call.message.delete()

# ── Callback: заглушка ───────────────────────────────────
@dp.callback_query(F.data == "noop")
async def cb_noop(call: types.CallbackQuery):
    await call.answer("Виділи текст і скопіюй 👆", show_alert=True)

# ── Моніторинг ───────────────────────────────────────────
async def check_new_projects(force=False):
    settings = load_settings()
    if settings.get("paused") and not force:
        return

    seen     = load_seen()
    projects = await get_latest_projects()
    new_count = 0

    for project in projects:
        pid = str(project.get("id", ""))
        if pid in seen:
            continue
        seen.add(pid)

        if not is_relevant(project, settings):
            continue

        text, title, description, skills, url = format_project(project)
        inc_stat("total_seen")

        try:
            await bot.send_message(
                MY_CHAT_ID,
                text,
                reply_markup=project_keyboard(pid, title, skills, description, url),
                disable_web_page_preview=True
            )
            new_count += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            log.error(f"Помилка: {e}")

    save_seen(seen)

    if force and new_count == 0:
        await bot.send_message(MY_CHAT_ID, "😴 Нових підходящих замовлень немає.")

# ── Щоденна зведення о 9:00 ─────────────────────────────
async def daily_digest():
    while True:
        now = datetime.now()
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            target = target.replace(day=target.day + 1)
        await asyncio.sleep((target - now).total_seconds())

        stats = load_stats()
        favs  = load_favorites()
        await bot.send_message(
            MY_CHAT_ID,
            f"☀️ <b>Доброго ранку!</b>\n\n"
            f"📊 За вчора:\n"
            f"👁 Переглянуто: {stats.get('total_seen', 0)}\n"
            f"✍️ Відгуків: {stats.get('replies_generated', 0)}\n"
            f"⭐ В обраному: {len(favs)}\n\n"
            f"Надсилаю /check щоб перевірити нові замовлення 🚀"
        )

# ── Фоновий моніторинг ───────────────────────────────────
async def monitor_loop():
    log.info("Моніторинг запущено")
    await bot.send_message(
        MY_CHAT_ID,
        "🚀 <b>FreelanceRadar запущено!</b>\n\n"
        "Перевіряю нові замовлення кожні 2 хв.\n"
        "Надішли /help щоб побачити всі команди."
    )
    while True:
        try:
            await check_new_projects()
        except Exception as e:
            log.error(f"Помилка моніторингу: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

# ── Запуск ───────────────────────────────────────────────
async def main():
    asyncio.create_task(monitor_loop())
    asyncio.create_task(daily_digest())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
