import asyncio
import logging
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from freelancehunt import get_latest_projects, format_project
from ai_reply import generate_reply, score_project, analyze_skills_trend
from tracker import set_status, format_tracker, STATUSES
from currency import get_usd_rate

# ── Конфиг ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MY_CHAT_ID     = int(os.getenv("MY_CHAT_ID"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "120"))

SEEN_FILE      = "seen_projects.json"
FAVORITES_FILE = "favorites.json"
SETTINGS_FILE  = "settings.json"
STATS_FILE     = "stats.json"
TEMPLATES_FILE = "templates.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher()

# ── Утилиты ──────────────────────────────────────────────
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_seen():       return set(load_json(SEEN_FILE, []))
def save_seen(s):      save_json(SEEN_FILE, list(s))
def load_favorites():  return load_json(FAVORITES_FILE, [])
def save_favorites(f): save_json(FAVORITES_FILE, f)
def load_templates():  return load_json(TEMPLATES_FILE, [])
def save_templates(t): save_json(TEMPLATES_FILE, t)

def load_settings():
    return load_json(SETTINGS_FILE, {
        "min_budget": 0,
        "max_bids": 999,
        "skills": ["сайт", "веб", "web", "HTML", "CSS", "JavaScript", "JS", "Python", "Telegram", "верстка", "бот", "лендинг", "React", "Node", "WordPress", "WP", "PHP", "програмування", "розробка", "frontend", "backend", "скрипт", "автоматизація"],
        "blacklist": [],
        "quiet_start": 23,
        "quiet_end": 8,
        "paused": False,
        "min_score": 0,
        "vip_budget": 2000,
    })

def save_settings(s): save_json(SETTINGS_FILE, s)

def load_stats():
    return load_json(STATS_FILE, {
        "total_seen": 0,
        "replies_generated": 0,
        "skipped": 0,
        "won": 0,
    })

def save_stats(s): save_json(STATS_FILE, s)

def inc_stat(key, val=1):
    s = load_stats()
    s[key] = s.get(key, 0) + val
    save_stats(s)

# ── Тихий режим ──────────────────────────────────────────
def is_quiet_time():
    settings = load_settings()
    h = datetime.now().hour
    qs = settings.get("quiet_start", 23)
    qe = settings.get("quiet_end", 8)
    if qs > qe:
        return h >= qs or h < qe
    return qs <= h < qe

# ── Фильтрация ───────────────────────────────────────────
def is_relevant(project, settings):
    attrs = project.get("attributes", {})

    # Бюджет
    budget_obj = attrs.get("budget") or {}
    amount = budget_obj.get("amount") or 0
    if amount > 0 and amount < settings.get("min_budget", 0):
        return False

    # Макс ставок
    bids = attrs.get("bid_count", 0) or 0
    if bids > settings.get("max_bids", 999):
        return False

    title = (attrs.get("name") or "").lower()
    desc  = (attrs.get("description") or "").lower()
    proj_skills = " ".join((sk.get("name") or "").lower() for sk in attrs.get("skills", []))
    text = f"{title} {desc} {proj_skills}"

    # Чёрный список
    for word in settings.get("blacklist", []):
        if word.lower() in text:
            return False

    # Если список навыков пустой — показываем всё
    skills_filter = [s.lower() for s in settings.get("skills", [])]
    if not skills_filter:
        return True

    # Проверяем совпадение — достаточно одного слова
    return any(kw in text for kw in skills_filter)

# ── Клавиатура ───────────────────────────────────────────
def project_keyboard(pid, title, skills, description, url, budget):
    b = InlineKeyboardBuilder()
    s = lambda x: str(x)[:55].replace(":", "·")
    b.row(
        InlineKeyboardButton(text="✍️ Відклик", callback_data=f"reply:{s(pid)}:{s(title)}:{s(skills)}:{s(description)}"),
        InlineKeyboardButton(text="🤖 Оцінка AI", callback_data=f"score:{s(pid)}:{s(title)}:{s(skills)}:{s(description)}"),
    )
    b.row(
        InlineKeyboardButton(text="⭐ Зберегти", callback_data=f"fav:{pid}:{s(title)}:{s(budget)}"),
        InlineKeyboardButton(text="🚫 Пропустити", callback_data=f"skip:{pid}"),
    )
    b.row(
        InlineKeyboardButton(text="📤 Відклик надіслано", callback_data=f"track:{pid}:{s(title)}:{s(budget)}:sent"),
    )
    b.row(InlineKeyboardButton(text="🔗 Відкрити проект", url=url))
    return b.as_markup()

def tracker_keyboard(pid, title, budget):
    b = InlineKeyboardBuilder()
    s = lambda x: str(x)[:55].replace(":", "·")
    statuses = [
        ("💬 Відповіли", "replied"),
        ("🔧 В роботі", "working"),
        ("🏆 Виграно", "won"),
        ("❌ Програно", "lost"),
    ]
    for label, status in statuses:
        b.button(text=label, callback_data=f"track:{pid}:{s(title)}:{s(budget)}:{status}")
    b.adjust(2)
    return b.as_markup()

# ── /start ───────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    await msg.answer(
        "👋 Привіт! Я <b>FreelanceRadar</b> 🎯\n\n"
        "<b>Основні команди:</b>\n"
        "/check — перевірити зараз\n"
        "/skills — налаштувати навички\n"
        "/budget — мінімальний бюджет\n"
        "/blacklist — слова-фільтри\n"
        "/quiet — тихий режим\n\n"
        "<b>Дані:</b>\n"
        "/favorites — збережені замовлення\n"
        "/tracker — трекер замовлень\n"
        "/templates — шаблони відгуків\n"
        "/stats — статистика\n"
        "/trends — аналіз ринку\n\n"
        "<b>Інше:</b>\n"
        "/rate — поточний курс USD\n"
        "/pause — пауза моніторингу\n"
        "/clear — очистити історію\n"
        "/help — детальна допомога"
    )

# ── /help ────────────────────────────────────────────────
@dp.message(Command("help"))
async def cmd_help(msg: types.Message):
    await msg.answer(
        "<b>Детальна допомога:</b>\n\n"
        "🔍 <b>Фільтри:</b>\n"
        "/skills HTML CSS Python — встановити навички\n"
        "/budget 500 — мін. бюджет (UAH)\n"
        "/blacklist слово1 слово2 — слова-виключення\n"
        "/maxbids 10 — макс. кількість ставок\n\n"
        "😴 <b>Тихий режим:</b>\n"
        "/quiet 23 8 — не турбувати з 23:00 до 08:00\n\n"
        "📋 <b>Трекер:</b>\n"
        "Натисни '📤 Відклик надіслано' під замовленням\n"
        "Потім відмічай статус: Відповіли / Виграно / Програно\n\n"
        "📝 <b>Шаблони:</b>\n"
        "/addtemplate Назва | Текст шаблону\n"
        "/templates — переглянути всі\n\n"
        "📈 <b>Аналітика:</b>\n"
        "/trends — AI аналіз попиту на навички\n"
        "/stats — твоя статистика\n"
        "/rate — курс долара"
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
        await msg.answer(f"✅ Навички: <code>{', '.join(args)}</code>")
    else:
        current = settings.get("skills", [])
        await msg.answer(f"🛠 <b>Навички:</b> <code>{', '.join(current)}</code>\n\nЗмінити: /skills HTML CSS Python")

# ── /budget ──────────────────────────────────────────────
@dp.message(Command("budget"))
async def cmd_budget(msg: types.Message):
    settings = load_settings()
    args = msg.text.strip().split()[1:]
    if args and args[0].isdigit():
        settings["min_budget"] = int(args[0])
        save_settings(settings)
        await msg.answer(f"✅ Мін. бюджет: <b>{args[0]} UAH</b>")
    else:
        await msg.answer(f"💰 Мін. бюджет: {settings.get('min_budget', 0)} UAH\n\nЗмінити: /budget 500")

# ── /maxbids ─────────────────────────────────────────────
@dp.message(Command("maxbids"))
async def cmd_maxbids(msg: types.Message):
    settings = load_settings()
    args = msg.text.strip().split()[1:]
    if args and args[0].isdigit():
        settings["max_bids"] = int(args[0])
        save_settings(settings)
        await msg.answer(f"✅ Макс. ставок: <b>{args[0]}</b>")
    else:
        await msg.answer(f"📊 Макс. ставок: {settings.get('max_bids', 999)}\n\nЗмінити: /maxbids 15")

# ── /blacklist ───────────────────────────────────────────
@dp.message(Command("blacklist"))
async def cmd_blacklist(msg: types.Message):
    settings = load_settings()
    args = msg.text.strip().split()[1:]
    if args:
        settings["blacklist"] = args
        save_settings(settings)
        await msg.answer(f"🚫 Чорний список: <code>{', '.join(args)}</code>")
    else:
        current = settings.get("blacklist", [])
        await msg.answer(f"🚫 <b>Чорний список:</b> <code>{', '.join(current)}</code>\n\nЗмінити: /blacklist слово1 слово2")

# ── /quiet ───────────────────────────────────────────────
@dp.message(Command("quiet"))
async def cmd_quiet(msg: types.Message):
    settings = load_settings()
    args = msg.text.strip().split()[1:]
    if len(args) == 2 and args[0].isdigit() and args[1].isdigit():
        settings["quiet_start"] = int(args[0])
        settings["quiet_end"]   = int(args[1])
        save_settings(settings)
        await msg.answer(f"😴 Тихий режим: {args[0]}:00 — {args[1]}:00")
    else:
        qs = settings.get("quiet_start", 23)
        qe = settings.get("quiet_end", 8)
        await msg.answer(f"😴 Тихий режим: {qs}:00 — {qe}:00\n\nЗмінити: /quiet 23 8")

# ── /pause ───────────────────────────────────────────────
@dp.message(Command("pause"))
async def cmd_pause(msg: types.Message):
    settings = load_settings()
    settings["paused"] = not settings.get("paused", False)
    save_settings(settings)
    await msg.answer("⏸ Моніторинг призупинено" if settings["paused"] else "▶️ Моніторинг відновлено")

# ── /clear ───────────────────────────────────────────────
@dp.message(Command("clear"))
async def cmd_clear(msg: types.Message):
    save_seen(set())
    await msg.answer("🗑 Історія очищена.")

# ── /favorites ───────────────────────────────────────────
@dp.message(Command("favorites"))
async def cmd_favorites(msg: types.Message):
    favs = load_favorites()
    if not favs:
        await msg.answer("⭐ Обране порожнє.")
        return
    text = "⭐ <b>Збережені замовлення:</b>\n\n"
    for i, f in enumerate(favs[-15:], 1):
        text += f"{i}. <a href='{f['url']}'>{f['title'][:45]}</a>"
        if f.get("budget"):
            text += f" — {f['budget']}"
        text += "\n"
    await msg.answer(text, disable_web_page_preview=True)

# ── /tracker ─────────────────────────────────────────────
@dp.message(Command("tracker"))
async def cmd_tracker(msg: types.Message):
    await msg.answer(format_tracker(), disable_web_page_preview=True)

# ── /templates ───────────────────────────────────────────
@dp.message(Command("templates"))
async def cmd_templates(msg: types.Message):
    templates = load_templates()
    if not templates:
        await msg.answer(
            "📝 Шаблонів немає.\n\n"
            "Додати: /addtemplate Назва | Текст шаблону"
        )
        return
    text = "📝 <b>Шаблони відгуків:</b>\n\n"
    for i, t in enumerate(templates, 1):
        text += f"{i}. <b>{t['name']}</b>\n<i>{t['text'][:100]}...</i>\n\n"
    await msg.answer(text)

# ── /addtemplate ─────────────────────────────────────────
@dp.message(Command("addtemplate"))
async def cmd_addtemplate(msg: types.Message):
    parts = msg.text[len("/addtemplate"):].strip().split("|", 1)
    if len(parts) < 2:
        await msg.answer("❌ Формат: /addtemplate Назва | Текст шаблону")
        return
    name, text = parts[0].strip(), parts[1].strip()
    templates = load_templates()
    templates.append({"name": name, "text": text})
    save_templates(templates)
    await msg.answer(f"✅ Шаблон <b>{name}</b> збережено!")

# ── /stats ───────────────────────────────────────────────
@dp.message(Command("stats"))
async def cmd_stats(msg: types.Message):
    stats    = load_stats()
    settings = load_settings()
    seen     = load_seen()
    favs     = load_favorites()
    from tracker import load_tracker
    tracker  = load_tracker()
    won      = sum(1 for v in tracker.values() if v.get("status") == "won")

    await msg.answer(
        "📊 <b>Статистика:</b>\n\n"
        f"👁 Переглянуто: <b>{len(seen)}</b>\n"
        f"✍️ Відгуків: <b>{stats.get('replies_generated', 0)}</b>\n"
        f"⭐ В обраному: <b>{len(favs)}</b>\n"
        f"🚫 Пропущено: <b>{stats.get('skipped', 0)}</b>\n"
        f"🏆 Виграно: <b>{won}</b>\n\n"
        f"⚙️ <b>Налаштування:</b>\n"
        f"💰 Мін. бюджет: {settings.get('min_budget', 0)} UAH\n"
        f"🛠 Навички: {', '.join(settings.get('skills', []))[:60]}\n"
        f"🚫 Чорний список: {', '.join(settings.get('blacklist', []))}\n"
        f"😴 Тихий режим: {settings.get('quiet_start')}:00—{settings.get('quiet_end')}:00\n"
        f"{'⏸ На паузі' if settings.get('paused') else '▶️ Активний'}"
    )

# ── /trends ──────────────────────────────────────────────
@dp.message(Command("trends"))
async def cmd_trends(msg: types.Message):
    await msg.answer("📈 Аналізую ринок...")
    projects = await get_latest_projects()
    analysis = await analyze_skills_trend(projects)
    await msg.answer(f"📈 <b>Аналіз ринку:</b>\n\n{analysis}")

# ── /rate ────────────────────────────────────────────────
@dp.message(Command("rate"))
async def cmd_rate(msg: types.Message):
    rate = await get_usd_rate()
    await msg.answer(f"💱 Курс НБУ: <b>1 USD = {rate:.2f} UAH</b>")

# ── Callback: відклик ────────────────────────────────────
@dp.callback_query(F.data.startswith("reply:"))
async def cb_reply(call: types.CallbackQuery):
    await call.answer("⏳ Генерую...")
    parts = call.data.split(":", 4)
    if len(parts) < 5:
        return
    _, pid, title, skills, description = parts

    # Показати шаблони якщо є
    templates = load_templates()
    if templates:
        b = InlineKeyboardBuilder()
        b.button(text="🤖 AI відклик", callback_data=f"ai_reply:{pid}:{title}:{skills}:{description}")
        for i, t in enumerate(templates[:3]):
            b.button(text=f"📝 {t['name']}", callback_data=f"tpl_reply:{i}")
        b.adjust(1)
        await call.message.answer(
            "Оберіть тип відклику:",
            reply_markup=b.as_markup()
        )
    else:
        await call.message.answer("✍️ Генерую AI відклик...")
        reply_text = await generate_reply(title, description, skills)
        inc_stat("replies_generated")
        await call.message.answer(f"💬 <b>Готовий відклик:</b>\n\n{reply_text}")

@dp.callback_query(F.data.startswith("ai_reply:"))
async def cb_ai_reply(call: types.CallbackQuery):
    await call.answer("⏳ Генерую...")
    parts = call.data.split(":", 4)
    if len(parts) < 5:
        return
    _, pid, title, skills, description = parts
    reply_text = await generate_reply(title, description, skills)
    inc_stat("replies_generated")
    await call.message.answer(f"💬 <b>AI відклик:</b>\n\n{reply_text}")

@dp.callback_query(F.data.startswith("tpl_reply:"))
async def cb_tpl_reply(call: types.CallbackQuery):
    idx = int(call.data.split(":")[1])
    templates = load_templates()
    if idx < len(templates):
        t = templates[idx]
        await call.answer()
        await call.message.answer(f"📝 <b>Шаблон «{t['name']}»:</b>\n\n{t['text']}")

# ── Callback: оцінка AI ───────────────────────────────────
@dp.callback_query(F.data.startswith("score:"))
async def cb_score(call: types.CallbackQuery):
    await call.answer("🤖 Оцінюю...")
    parts = call.data.split(":", 4)
    if len(parts) < 5:
        return
    _, pid, title, skills, description = parts

    result = await score_project(title, description, skills)
    score   = result.get("score", 5)
    pros    = result.get("pros", "")
    cons    = result.get("cons", "")
    verdict = result.get("verdict", "Нормально")

    stars = "⭐" * min(score, 10)
    await call.message.answer(
        f"🤖 <b>Оцінка AI: {score}/10</b> {stars}\n"
        f"<b>Вердикт:</b> {verdict}\n\n"
        f"✅ {pros}\n"
        f"❌ {cons}"
    )

# ── Callback: обране ─────────────────────────────────────
@dp.callback_query(F.data.startswith("fav:"))
async def cb_fav(call: types.CallbackQuery):
    parts = call.data.split(":", 3)
    pid    = parts[1] if len(parts) > 1 else ""
    title  = parts[2] if len(parts) > 2 else pid
    budget = parts[3] if len(parts) > 3 else ""

    favs = load_favorites()
    if any(f["id"] == pid for f in favs):
        await call.answer("Вже збережено ⭐")
        return

    favs.append({
        "id": pid,
        "title": title,
        "budget": budget,
        "url": f"https://freelancehunt.com/project/{pid}.html"
    })
    save_favorites(favs)
    await call.answer("⭐ Збережено в обране!")

# ── Callback: пропустити ─────────────────────────────────
@dp.callback_query(F.data.startswith("skip:"))
async def cb_skip(call: types.CallbackQuery):
    inc_stat("skipped")
    await call.answer("🚫 Пропущено")
    try:
        await call.message.delete()
    except Exception:
        pass

# ── Callback: трекер ─────────────────────────────────────
@dp.callback_query(F.data.startswith("track:"))
async def cb_track(call: types.CallbackQuery):
    parts = call.data.split(":", 4)
    if len(parts) < 5:
        return
    _, pid, title, budget, status = parts
    url = f"https://freelancehunt.com/project/{pid}.html"
    set_status(pid, title, url, status, budget)

    if status == "won":
        inc_stat("won")
        await call.answer("🏆 Виграно! Вітаю!")
    else:
        label = STATUSES.get(status, status)
        await call.answer(f"✅ {label}")

    # Показати кнопки наступних статусів
    if status == "sent":
        await call.message.answer(
            f"📤 <b>Відклик надіслано</b> на замовлення\n<i>{title}</i>\n\n"
            f"Оновіть статус коли буде відповідь:",
            reply_markup=tracker_keyboard(pid, title, budget)
        )

# ── Моніторинг ───────────────────────────────────────────
async def check_new_projects(force=False):
    settings = load_settings()
    if settings.get("paused") and not force:
        return
    if is_quiet_time() and not force:
        return

    seen     = load_seen()
    projects = await get_latest_projects()
    new_count = 0
    all_projects = []

    for project in projects:
        pid = str(project.get("id", ""))
        if pid in seen:
            continue
        seen.add(pid)
        all_projects.append(project)

        if not is_relevant(project, settings):
            continue

        text, title, description, skills, url, budget = await format_project(project)
        inc_stat("total_seen")

        # VIP алерт для великих бюджетів
        attrs   = project.get("attributes", {})
        amount  = (attrs.get("budget") or {}).get("amount") or 0
        vip_min = settings.get("vip_budget", 2000)
        if amount >= vip_min:
            await bot.send_message(MY_CHAT_ID, f"🔥 <b>ВАУ-ЗАМОВЛЕННЯ! {amount} UAH!</b>")

        try:
            await bot.send_message(
                MY_CHAT_ID,
                text,
                reply_markup=project_keyboard(pid, title, skills, description, url, budget),
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
        now    = datetime.now()
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now.hour >= 9:
            target = target.replace(day=target.day + 1)
        await asyncio.sleep((target - now).total_seconds())

        stats   = load_stats()
        favs    = load_favorites()
        from tracker import load_tracker
        tracker = load_tracker()
        won     = sum(1 for v in tracker.values() if v.get("status") == "won")
        rate    = await get_usd_rate()

        await bot.send_message(
            MY_CHAT_ID,
            f"☀️ <b>Доброго ранку!</b>\n\n"
            f"📊 Статистика:\n"
            f"👁 Переглянуто: {stats.get('total_seen', 0)}\n"
            f"✍️ Відгуків: {stats.get('replies_generated', 0)}\n"
            f"🏆 Виграно: {won}\n"
            f"⭐ В обраному: {len(favs)}\n\n"
            f"💱 Курс: 1 USD = {rate:.2f} UAH\n\n"
            f"Надішли /check щоб перевірити нові замовлення 🚀"
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
