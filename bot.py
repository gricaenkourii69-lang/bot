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
from aiogram.types import InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from freelancehunt import get_latest_projects, format_project
from ai_reply import generate_reply, score_project, analyze_skills_trend
from tracker import set_status, format_tracker, STATUSES, load_tracker
from currency import get_usd_rate
from notifications import (
    get_threads, get_feed, get_profile,
    format_thread, format_feed_item,
    load_last_notif, save_last_notif
)
from menus import (
    main_menu, settings_menu, project_card_keyboard,
    tracker_status_keyboard, notifications_menu
)

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
dp  = Dispatcher(storage=MemoryStorage())

# ── FSM стани для налаштувань ─────────────────────────────
class SettingsState(StatesGroup):
    waiting_budget   = State()
    waiting_maxbids  = State()
    waiting_quiet    = State()
    waiting_skills   = State()
    waiting_blacklist= State()
    waiting_vip      = State()

class TemplateState(StatesGroup):
    waiting_name = State()
    waiting_text = State()

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
        "skills": [
            "сайт", "веб", "web", "HTML", "CSS", "JavaScript", "JS",
            "Python", "Telegram", "верстка", "бот", "лендинг",
            "React", "Node", "WordPress", "WP", "PHP",
            "програмування", "розробка", "frontend", "backend",
            "скрипт", "автоматизація", "парсинг"
        ],
        "blacklist": [],
        "quiet_start": 23,
        "quiet_end": 8,
        "paused": False,
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

def inc_stat(key, val=1):
    s = load_stats()
    s[key] = s.get(key, 0) + val
    save_json(STATS_FILE, s)

def is_quiet_time():
    settings = load_settings()
    h  = datetime.now().hour
    qs = settings.get("quiet_start", 23)
    qe = settings.get("quiet_end", 8)
    if qs > qe:
        return h >= qs or h < qe
    return qs <= h < qe

def is_relevant(project, settings):
    attrs = project.get("attributes", {})
    budget_obj = attrs.get("budget") or {}
    amount     = budget_obj.get("amount") or 0
    if amount > 0 and amount < settings.get("min_budget", 0):
        return False
    bids = attrs.get("bid_count", 0) or 0
    if bids > settings.get("max_bids", 999):
        return False
    title = (attrs.get("name") or "").lower()
    desc  = (attrs.get("description") or "").lower()
    proj_skills = " ".join(
        (sk.get("name") or "").lower() for sk in attrs.get("skills", [])
    )
    text = f"{title} {desc} {proj_skills}"
    for word in settings.get("blacklist", []):
        if word.lower() in text:
            return False
    skills_filter = [s.lower() for s in settings.get("skills", [])]
    if not skills_filter:
        return True
    return any(kw in text for kw in skills_filter)

# ── /start ───────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    await msg.answer(
        "👋 Привіт! Я <b>FreelanceRadar</b> 🎯\n\n"
        "Знаходжу замовлення на Freelancehunt, генерую відклики через AI, "
        "слідкую за повідомленнями та допомагаю вигравати проекти.\n\n"
        "Обери дію в меню нижче 👇",
        reply_markup=main_menu()
    )

# ── Reply кнопки головного меню ──────────────────────────
@dp.message(F.text == "🔍 Перевірити зараз")
async def menu_check(msg: Message):
    await msg.answer("🔍 Перевіряю нові замовлення...")
    await check_new_projects(force=True)

@dp.message(F.text == "🔔 Повідомлення")
async def menu_notif(msg: Message):
    await msg.answer("🔔 <b>Повідомлення Freelancehunt:</b>", reply_markup=notifications_menu())

@dp.message(F.text == "⭐ Обране")
async def menu_favorites(msg: Message):
    favs = load_favorites()
    if not favs:
        await msg.answer("⭐ Обране порожнє.\nНатисни ⭐ під замовленням щоб зберегти.")
        return
    text = "⭐ <b>Збережені замовлення:</b>\n\n"
    for i, f in enumerate(favs[-15:], 1):
        text += f"{i}. <a href='{f['url']}'>{f['title'][:50]}</a>"
        if f.get("budget"):
            text += f" — {f['budget']}"
        text += "\n"
    await msg.answer(text, disable_web_page_preview=True)

@dp.message(F.text == "📋 Трекер")
async def menu_tracker(msg: Message):
    await msg.answer(format_tracker(), disable_web_page_preview=True)

@dp.message(F.text == "📊 Статистика")
async def menu_stats(msg: Message):
    await show_stats(msg)

@dp.message(F.text == "📈 Тренди")
async def menu_trends(msg: Message):
    await msg.answer("📈 Аналізую ринок...")
    projects = await get_latest_projects()
    analysis = await analyze_skills_trend(projects)
    await msg.answer(f"📈 <b>Аналіз ринку:</b>\n\n{analysis}")

@dp.message(F.text == "⚙️ Налаштування")
async def menu_settings(msg: Message):
    settings = load_settings()
    await msg.answer(
        "⚙️ <b>Налаштування бота:</b>\n\nОбери що змінити:",
        reply_markup=settings_menu(settings)
    )

@dp.message(F.text == "❓ Допомога")
async def menu_help(msg: Message):
    await msg.answer(
        "❓ <b>Як користуватись FreelanceRadar:</b>\n\n"
        "🔍 <b>Перевірити зараз</b> — показати нові замовлення\n"
        "🔔 <b>Повідомлення</b> — особисті повідомлення та стрічка подій\n"
        "⭐ <b>Обране</b> — збережені замовлення\n"
        "📋 <b>Трекер</b> — статуси твоїх замовлень\n"
        "📊 <b>Статистика</b> — твоя активність\n"
        "📈 <b>Тренди</b> — AI аналіз ринку\n"
        "⚙️ <b>Налаштування</b> — фільтри, бюджет, тихий режим\n\n"
        "<b>Під кожним замовленням:</b>\n"
        "✍️ Відклик — AI генерує персональний текст\n"
        "🤖 Оцінка — AI оцінює замовлення 1-10\n"
        "⭐ Зберегти — додати в обране\n"
        "🚫 Пропустити — видалити картку\n"
        "📤 Відклик надіслано — додати в трекер\n\n"
        "<b>Шаблони:</b>\n"
        "/addtemplate Назва | Текст\n"
        "/templates — переглянути\n\n"
        "<b>Курс:</b> /rate"
    )

# ── Команди ──────────────────────────────────────────────
@dp.message(Command("check"))
async def cmd_check(msg: Message):
    await msg.answer("🔍 Перевіряю...")
    await check_new_projects(force=True)

@dp.message(Command("clear"))
async def cmd_clear(msg: Message):
    save_seen(set())
    await msg.answer("🗑 Історія очищена. Наступна перевірка покаже всі актуальні проекти.")

@dp.message(Command("rate"))
async def cmd_rate(msg: Message):
    rate = await get_usd_rate()
    await msg.answer(f"💱 Курс НБУ: <b>1 USD = {rate:.2f} UAH</b>")

@dp.message(Command("templates"))
async def cmd_templates(msg: Message):
    templates = load_templates()
    if not templates:
        await msg.answer("📝 Шаблонів немає.\n\nДодати: /addtemplate Назва | Текст")
        return
    text = "📝 <b>Шаблони відгуків:</b>\n\n"
    for i, t in enumerate(templates, 1):
        text += f"{i}. <b>{t['name']}</b>\n<i>{t['text'][:120]}...</i>\n\n"
    await msg.answer(text)

@dp.message(Command("addtemplate"))
async def cmd_addtemplate(msg: Message):
    parts = msg.text[len("/addtemplate"):].strip().split("|", 1)
    if len(parts) < 2:
        await msg.answer("❌ Формат: /addtemplate Назва | Текст шаблону")
        return
    name, text = parts[0].strip(), parts[1].strip()
    templates = load_templates()
    templates.append({"name": name, "text": text})
    save_templates(templates)
    await msg.answer(f"✅ Шаблон <b>{name}</b> збережено!")

# ── Статистика ───────────────────────────────────────────
async def show_stats(msg: Message):
    stats    = load_stats()
    settings = load_settings()
    seen     = load_seen()
    favs     = load_favorites()
    tracker  = load_tracker()
    won      = sum(1 for v in tracker.values() if v.get("status") == "won")
    rate     = await get_usd_rate()

    await msg.answer(
        "📊 <b>Статистика FreelanceRadar</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👁  Переглянуто замовлень:  <b>{len(seen)}</b>\n"
        f"✍️  Відгуків згенеровано:   <b>{stats.get('replies_generated', 0)}</b>\n"
        f"⭐  В обраному:             <b>{len(favs)}</b>\n"
        f"🚫  Пропущено:              <b>{stats.get('skipped', 0)}</b>\n"
        f"🏆  Виграно проектів:       <b>{won}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💱  Курс: 1 USD = {rate:.2f} UAH\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰  Мін. бюджет:  {settings.get('min_budget', 0)} UAH\n"
        f"📊  Макс. ставок: {settings.get('max_bids', 999)}\n"
        f"😴  Тихий режим:  {settings.get('quiet_start')}:00—{settings.get('quiet_end')}:00\n"
        f"{'⏸  На паузі' if settings.get('paused') else '▶️  Активний'}"
    )

# ── Notifications callbacks ───────────────────────────────
@dp.callback_query(F.data == "notif_threads")
async def cb_notif_threads(call: types.CallbackQuery):
    await call.answer("⏳ Завантажую...")
    threads = await get_threads()
    if not threads:
        await call.message.answer("💬 Повідомлень немає.")
        return
    await call.message.answer("💬 <b>Останні повідомлення:</b>\n━━━━━━━━━━━━━━")
    for t in threads[:5]:
        text, is_new = format_thread(t)
        await call.message.answer(text, disable_web_page_preview=True)
        await asyncio.sleep(0.3)

@dp.callback_query(F.data == "notif_feed")
async def cb_notif_feed(call: types.CallbackQuery):
    await call.answer("⏳ Завантажую...")
    feed = await get_feed()
    if not feed:
        await call.message.answer("🔔 Стрічка подій порожня.")
        return
    await call.message.answer("🔔 <b>Стрічка подій:</b>\n━━━━━━━━━━━━━━")
    for item in feed[:7]:
        text = format_feed_item(item)
        await call.message.answer(text, disable_web_page_preview=True)
        await asyncio.sleep(0.3)

@dp.callback_query(F.data == "notif_profile")
async def cb_notif_profile(call: types.CallbackQuery):
    await call.answer("⏳ Завантажую...")
    profile = await get_profile()
    if not profile:
        await call.message.answer("⚠️ Не вдалося завантажити профіль.")
        return
    attrs   = profile.get("attributes", {})
    login   = attrs.get("login", "—")
    rating  = attrs.get("rating", 0)
    reviews = attrs.get("reviews_count", 0)
    balance = attrs.get("balance", {}) or {}
    amount  = balance.get("amount", 0)
    currency = balance.get("currency", "UAH")
    rate    = await get_usd_rate()
    usd     = round(amount / rate) if currency == "UAH" else amount

    await call.message.answer(
        f"👤 <b>Профіль Freelancehunt</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Логін: <b>{login}</b>\n"
        f"⭐ Рейтинг: <b>{rating}</b>\n"
        f"💬 Відгуків: <b>{reviews}</b>\n"
        f"💰 Баланс: <b>{amount} {currency}</b> (~${usd})\n"
        f"🔗 <a href='https://freelancehunt.com/freelancer/{login}.html'>Мій профіль</a>"
    )

# ── Settings callbacks ────────────────────────────────────
@dp.callback_query(F.data == "set_pause")
async def cb_set_pause(call: types.CallbackQuery):
    settings = load_settings()
    settings["paused"] = not settings.get("paused", False)
    save_settings(settings)
    await call.answer("⏸ Пауза" if settings["paused"] else "▶️ Активний")
    await call.message.edit_reply_markup(reply_markup=settings_menu(settings))

@dp.callback_query(F.data == "set_budget")
async def cb_set_budget(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("💰 Введи мінімальний бюджет у UAH (наприклад: 500):")
    await state.set_state(SettingsState.waiting_budget)

@dp.message(SettingsState.waiting_budget)
async def state_budget(msg: Message, state: FSMContext):
    if msg.text.isdigit():
        settings = load_settings()
        settings["min_budget"] = int(msg.text)
        save_settings(settings)
        await msg.answer(f"✅ Мін. бюджет: <b>{msg.text} UAH</b>", reply_markup=main_menu())
        await state.clear()
    else:
        await msg.answer("❌ Введи число, наприклад: 500")

@dp.callback_query(F.data == "set_maxbids")
async def cb_set_maxbids(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("📊 Введи максимальну кількість ставок (наприклад: 15):")
    await state.set_state(SettingsState.waiting_maxbids)

@dp.message(SettingsState.waiting_maxbids)
async def state_maxbids(msg: Message, state: FSMContext):
    if msg.text.isdigit():
        settings = load_settings()
        settings["max_bids"] = int(msg.text)
        save_settings(settings)
        await msg.answer(f"✅ Макс. ставок: <b>{msg.text}</b>", reply_markup=main_menu())
        await state.clear()
    else:
        await msg.answer("❌ Введи число, наприклад: 15")

@dp.callback_query(F.data == "set_quiet")
async def cb_set_quiet(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("😴 Введи тихий режим у форматі: <code>23 8</code> (з 23:00 до 8:00):")
    await state.set_state(SettingsState.waiting_quiet)

@dp.message(SettingsState.waiting_quiet)
async def state_quiet(msg: Message, state: FSMContext):
    parts = msg.text.strip().split()
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        settings = load_settings()
        settings["quiet_start"] = int(parts[0])
        settings["quiet_end"]   = int(parts[1])
        save_settings(settings)
        await msg.answer(f"✅ Тихий режим: {parts[0]}:00 — {parts[1]}:00", reply_markup=main_menu())
        await state.clear()
    else:
        await msg.answer("❌ Формат: 23 8")

@dp.callback_query(F.data == "set_skills")
async def cb_set_skills(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    settings = load_settings()
    current  = ", ".join(settings.get("skills", []))
    await call.message.answer(
        f"🛠 Поточні навички:\n<code>{current}</code>\n\n"
        f"Введи нові через пробіл:\n<code>HTML CSS Python Telegram сайт</code>"
    )
    await state.set_state(SettingsState.waiting_skills)

@dp.message(SettingsState.waiting_skills)
async def state_skills(msg: Message, state: FSMContext):
    skills = msg.text.strip().split()
    settings = load_settings()
    settings["skills"] = skills
    save_settings(settings)
    await msg.answer(f"✅ Навички: <code>{', '.join(skills)}</code>", reply_markup=main_menu())
    await state.clear()

@dp.callback_query(F.data == "set_blacklist")
async def cb_set_blacklist(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    settings = load_settings()
    current  = ", ".join(settings.get("blacklist", []))
    await call.message.answer(
        f"🚫 Чорний список:\n<code>{current or 'порожній'}</code>\n\n"
        f"Введи слова через пробіл (замовлення з цими словами буде скрито):"
    )
    await state.set_state(SettingsState.waiting_blacklist)

@dp.message(SettingsState.waiting_blacklist)
async def state_blacklist(msg: Message, state: FSMContext):
    words = msg.text.strip().split()
    settings = load_settings()
    settings["blacklist"] = words
    save_settings(settings)
    await msg.answer(f"✅ Чорний список: <code>{', '.join(words)}</code>", reply_markup=main_menu())
    await state.clear()

@dp.callback_query(F.data == "set_vip")
async def cb_set_vip(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("🔥 Введи суму VIP бюджету в UAH (при такому бюджеті буде спеціальний алерт):")
    await state.set_state(SettingsState.waiting_vip)

@dp.message(SettingsState.waiting_vip)
async def state_vip(msg: Message, state: FSMContext):
    if msg.text.isdigit():
        settings = load_settings()
        settings["vip_budget"] = int(msg.text)
        save_settings(settings)
        await msg.answer(f"✅ VIP бюджет: <b>{msg.text} UAH</b>", reply_markup=main_menu())
        await state.clear()
    else:
        await msg.answer("❌ Введи число")

@dp.callback_query(F.data == "set_done")
async def cb_set_done(call: types.CallbackQuery):
    await call.answer("✅ Збережено!")
    await call.message.answer("✅ Налаштування збережено!", reply_markup=main_menu())

# ── Project callbacks ─────────────────────────────────────
@dp.callback_query(F.data.startswith("reply:"))
async def cb_reply(call: types.CallbackQuery):
    await call.answer("⏳ Генерую...")
    parts = call.data.split(":", 4)
    if len(parts) < 5:
        return
    _, pid, title, skills, description = parts
    templates = load_templates()
    if templates:
        b = InlineKeyboardBuilder()
        b.button(text="🤖 AI відклик", callback_data=f"ai_reply:{pid}:{title}:{skills}:{description}")
        for i, t in enumerate(templates[:3]):
            b.button(text=f"📝 {t['name']}", callback_data=f"tpl_reply:{i}")
        b.adjust(1)
        await call.message.answer("Оберіть тип відклику:", reply_markup=b.as_markup())
    else:
        reply_text = await generate_reply(title, description, skills)
        inc_stat("replies_generated")
        await call.message.answer(
            f"💬 <b>AI відклик:</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{reply_text}"
        )

@dp.callback_query(F.data.startswith("ai_reply:"))
async def cb_ai_reply(call: types.CallbackQuery):
    await call.answer("⏳ Генерую...")
    parts = call.data.split(":", 4)
    if len(parts) < 5:
        return
    _, pid, title, skills, description = parts
    reply_text = await generate_reply(title, description, skills)
    inc_stat("replies_generated")
    await call.message.answer(
        f"💬 <b>AI відклик:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{reply_text}"
    )

@dp.callback_query(F.data.startswith("tpl_reply:"))
async def cb_tpl_reply(call: types.CallbackQuery):
    idx = int(call.data.split(":")[1])
    templates = load_templates()
    if idx < len(templates):
        t = templates[idx]
        await call.answer()
        await call.message.answer(
            f"📝 <b>Шаблон «{t['name']}»:</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{t['text']}"
        )

@dp.callback_query(F.data.startswith("score:"))
async def cb_score(call: types.CallbackQuery):
    await call.answer("🤖 Оцінюю...")
    parts = call.data.split(":", 4)
    if len(parts) < 5:
        return
    _, pid, title, skills, description = parts
    result  = await score_project(title, description, skills)
    score   = result.get("score", 5)
    pros    = result.get("pros", "—")
    cons    = result.get("cons", "—")
    verdict = result.get("verdict", "Нормально")
    filled  = "🟩" * score + "⬜" * (10 - score)

    await call.message.answer(
        f"🤖 <b>Оцінка AI: {score}/10</b>\n"
        f"{filled}\n"
        f"<b>Вердикт:</b> {verdict}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ {pros}\n"
        f"❌ {cons}"
    )

@dp.callback_query(F.data.startswith("fav:"))
async def cb_fav(call: types.CallbackQuery):
    parts  = call.data.split(":", 3)
    pid    = parts[1] if len(parts) > 1 else ""
    title  = parts[2] if len(parts) > 2 else pid
    budget = parts[3] if len(parts) > 3 else ""
    favs   = load_favorites()
    if any(f["id"] == pid for f in favs):
        await call.answer("Вже збережено ⭐")
        return
    favs.append({
        "id": pid, "title": title, "budget": budget,
        "url": f"https://freelancehunt.com/project/{pid}.html"
    })
    save_favorites(favs)
    await call.answer("⭐ Збережено в обране!")

@dp.callback_query(F.data.startswith("skip:"))
async def cb_skip(call: types.CallbackQuery):
    inc_stat("skipped")
    await call.answer("🚫 Пропущено")
    try:
        await call.message.delete()
    except Exception:
        pass

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
        await call.answer(f"✅ {STATUSES.get(status, status)}")
    if status == "sent":
        await call.message.answer(
            f"📤 <b>Відклик надіслано</b>\n<i>{title}</i>\n\nОновіть статус:",
            reply_markup=tracker_status_keyboard(pid, title, budget)
        )

# ── Моніторинг нових проектів ─────────────────────────────
async def check_new_projects(force=False):
    settings = load_settings()
    if settings.get("paused") and not force:
        return
    if is_quiet_time() and not force:
        return

    seen      = load_seen()
    projects  = await get_latest_projects()
    new_count = 0

    for project in projects:
        pid = str(project.get("id", ""))
        if pid in seen:
            continue
        seen.add(pid)
        if not is_relevant(project, settings):
            continue

        text, title, description, skills, url, budget = await format_project(project)
        inc_stat("total_seen")

        attrs   = project.get("attributes", {})
        amount  = (attrs.get("budget") or {}).get("amount") or 0
        vip_min = settings.get("vip_budget", 2000)
        if amount >= vip_min:
            await bot.send_message(
                MY_CHAT_ID,
                f"🔥🔥🔥 <b>VIP ЗАМОВЛЕННЯ!</b>\n💰 Бюджет: <b>{amount} UAH</b>"
            )

        try:
            await bot.send_message(
                MY_CHAT_ID,
                text,
                reply_markup=project_card_keyboard(pid, title, skills, description, url, budget),
                disable_web_page_preview=True
            )
            new_count += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            log.error(f"Помилка: {e}")

    save_seen(seen)
    if force and new_count == 0:
        await bot.send_message(MY_CHAT_ID, "😴 Нових підходящих замовлень немає.")

# ── Моніторинг повідомлень ────────────────────────────────
async def check_notifications():
    last = load_last_notif()

    # Перевіряємо непрочитані треди
    threads = await get_threads()
    for t in threads:
        attrs  = t.get("attributes", {})
        unread = attrs.get("unread_count", 0)
        tid    = str(t.get("id", ""))
        if unread and tid != str(last.get("thread_id")):
            text, _ = format_thread(t)
            await bot.send_message(
                MY_CHAT_ID,
                f"💬 <b>Нове повідомлення на Freelancehunt!</b>\n━━━━━━━━━━━━━━\n{text}",
                disable_web_page_preview=True
            )
            last["thread_id"] = tid
            save_last_notif(last)
            break

    # Стрічка подій
    feed = await get_feed()
    if feed:
        first_id = str(feed[0].get("id", ""))
        if first_id and first_id != str(last.get("feed_id")):
            item = feed[0]
            text = format_feed_item(item)
            itype = (item.get("attributes") or {}).get("type", "")
            if itype in ("award", "review"):
                await bot.send_message(
                    MY_CHAT_ID,
                    f"🔔 <b>Нова подія!</b>\n━━━━━━━━━━━━━━\n{text}",
                    disable_web_page_preview=True
                )
            last["feed_id"] = first_id
            save_last_notif(last)

# ── Щоденна зведення ─────────────────────────────────────
async def daily_digest():
    while True:
        now    = datetime.now()
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now.hour >= 9:
            from datetime import timedelta
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())

        stats   = load_stats()
        favs    = load_favorites()
        tracker = load_tracker()
        won     = sum(1 for v in tracker.values() if v.get("status") == "won")
        rate    = await get_usd_rate()

        await bot.send_message(
            MY_CHAT_ID,
            f"☀️ <b>Доброго ранку!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Статистика:\n"
            f"👁  Переглянуто: {stats.get('total_seen', 0)}\n"
            f"✍️  Відгуків: {stats.get('replies_generated', 0)}\n"
            f"🏆  Виграно: {won}\n"
            f"⭐  В обраному: {len(favs)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💱  1 USD = {rate:.2f} UAH\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Натисни 🔍 щоб перевірити нові замовлення 🚀",
            reply_markup=main_menu()
        )

# ── Фоновий моніторинг ───────────────────────────────────
async def monitor_loop():
    log.info("Моніторинг запущено")
    await bot.send_message(
        MY_CHAT_ID,
        "🚀 <b>FreelanceRadar запущено!</b>\n\n"
        "Перевіряю нові замовлення та повідомлення кожні 2 хв.\n"
        "Натисни кнопку нижче щоб почати 👇",
        reply_markup=main_menu()
    )
    while True:
        try:
            await check_new_projects()
            await check_notifications()
        except Exception as e:
            log.error(f"Помилка: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

# ── Запуск ───────────────────────────────────────────────
async def main():
    asyncio.create_task(monitor_loop())
    asyncio.create_task(daily_digest())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
