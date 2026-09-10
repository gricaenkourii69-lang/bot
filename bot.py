import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
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
    get_threads, get_profile, get_my_bids,
    format_thread, format_bid,
    load_last_notif, save_last_notif
)
from menus import (
    main_menu, home_inline, settings_menu,
    orders_menu, notif_menu, tracker_menu,
    templates_menu, project_card_keyboard,
    tracker_status_keyboard, back_home
)

# ── Конфіг ──────────────────────────────────────────────
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

# ── FSM ──────────────────────────────────────────────────
class SettingsState(StatesGroup):
    waiting_budget    = State()
    waiting_maxbids   = State()
    waiting_quiet     = State()
    waiting_skills    = State()
    waiting_blacklist = State()
    waiting_vip       = State()

class TemplateState(StatesGroup):
    waiting_input = State()

# ── Утиліти ──────────────────────────────────────────────
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
        "min_budget": 0, "max_bids": 999,
        "skills": [
            "сайт","веб","web","HTML","CSS","JavaScript","JS",
            "Python","Telegram","верстка","бот","лендинг",
            "React","Node","WordPress","WP","PHP",
            "програмування","розробка","frontend","backend",
            "скрипт","автоматизація","парсинг",
        ],
        "blacklist": [],
        "quiet_start": 23, "quiet_end": 8,
        "paused": False, "vip_budget": 2000,
    })

def save_settings(s): save_json(SETTINGS_FILE, s)

def load_stats():
    return load_json(STATS_FILE, {
        "total_seen": 0, "replies_generated": 0,
        "skipped": 0, "won": 0,
    })

def inc_stat(key, val=1):
    s = load_stats(); s[key] = s.get(key, 0) + val; save_json(STATS_FILE, s)

def is_quiet_time():
    s = load_settings(); h = datetime.now().hour
    qs, qe = s.get("quiet_start", 23), s.get("quiet_end", 8)
    return (h >= qs or h < qe) if qs > qe else (qs <= h < qe)

def is_relevant(project, settings):
    attrs = project.get("attributes", {})
    amount = (attrs.get("budget") or {}).get("amount") or 0
    if amount > 0 and amount < settings.get("min_budget", 0):
        return False
    if (attrs.get("bid_count") or 0) > settings.get("max_bids", 999):
        return False
    title = (attrs.get("name") or "").lower()
    desc  = (attrs.get("description") or "").lower()
    sk    = " ".join((s.get("name") or "").lower() for s in attrs.get("skills", []))
    text  = f"{title} {desc} {sk}"
    for w in settings.get("blacklist", []):
        if w.lower() in text:
            return False
    sf = [s.lower() for s in settings.get("skills", [])]
    return any(kw in text for kw in sf) if sf else True

# ── /start ───────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    await msg.answer(
        "👋 Привіт! Я <b>FreelanceRadar</b> 🎯\n\n"
        "Знаходжу замовлення, генерую AI-відклики,\n"
        "слідкую за повідомленнями і трекером.",
        reply_markup=main_menu()
    )
    await msg.answer("📌 <b>Головне меню:</b>", reply_markup=home_inline())

# ── Головне меню ─────────────────────────────────────────
@dp.message(F.text == "🏠 Головне меню")
async def show_home_btn(msg: Message):
    await msg.answer("📌 <b>Головне меню:</b>", reply_markup=home_inline())

@dp.message(F.text == "🔍 Перевірити зараз")
async def quick_check_btn(msg: Message):
    await msg.answer("🔍 Перевіряю...")
    await check_new_projects(force=True)

@dp.callback_query(F.data == "menu_home")
async def cb_home(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_text("📌 <b>Головне меню:</b>", reply_markup=home_inline())
    except Exception:
        await call.message.answer("📌 <b>Головне меню:</b>", reply_markup=home_inline())

# ── Замовлення ────────────────────────────────────────────
@dp.callback_query(F.data == "menu_orders")
async def cb_orders(call: types.CallbackQuery):
    await call.answer()
    s = load_settings()
    st = "⏸ На паузі" if s.get("paused") else "▶️ Активний"
    await call.message.edit_text(
        f"🔍 <b>Замовлення</b>\nСтатус: {st} · Інтервал: {CHECK_INTERVAL}с",
        reply_markup=orders_menu()
    )

@dp.callback_query(F.data == "orders_check")
async def cb_orders_check(call: types.CallbackQuery):
    await call.answer("🔍 Перевіряю...")
    await call.message.edit_text("🔍 <b>Перевіряю нові замовлення...</b>", reply_markup=back_home())
    await check_new_projects(force=True)

@dp.callback_query(F.data == "orders_clear")
async def cb_orders_clear(call: types.CallbackQuery):
    save_seen(set())
    await call.answer("🗑 Готово!")
    await call.message.edit_text("🗑 <b>Історія очищена!</b>\nНаступна перевірка покаже всі актуальні замовлення.", reply_markup=orders_menu())

@dp.callback_query(F.data == "orders_pause")
async def cb_orders_pause(call: types.CallbackQuery):
    s = load_settings(); s["paused"] = True; save_settings(s)
    await call.answer("⏸ Пауза")
    await call.message.edit_text("⏸ <b>Моніторинг призупинено</b>", reply_markup=orders_menu())

@dp.callback_query(F.data == "orders_resume")
async def cb_orders_resume(call: types.CallbackQuery):
    s = load_settings(); s["paused"] = False; save_settings(s)
    await call.answer("▶️ Відновлено")
    await call.message.edit_text("▶️ <b>Моніторинг активний!</b>", reply_markup=orders_menu())

@dp.callback_query(F.data == "orders_rate")
async def cb_orders_rate(call: types.CallbackQuery):
    await call.answer("⏳")
    rate = await get_usd_rate()
    await call.message.edit_text(f"💱 <b>Курс НБУ</b>\n1 USD = <b>{rate:.2f} UAH</b>", reply_markup=orders_menu())

# ── Повідомлення ──────────────────────────────────────────
@dp.callback_query(F.data == "menu_notif")
async def cb_notif(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("🔔 <b>Повідомлення</b>\nОбери що переглянути:", reply_markup=notif_menu())

@dp.callback_query(F.data == "notif_threads")
async def cb_threads(call: types.CallbackQuery):
    await call.answer("⏳")
    threads = await get_threads()
    if not threads:
        await call.message.edit_text("💬 <b>Листування</b>\nПовідомлень немає.", reply_markup=notif_menu())
        return
    await call.message.edit_text(f"💬 <b>Листування</b> ({len(threads)} тредів):", reply_markup=notif_menu())
    for t in threads[:5]:
        text, _ = format_thread(t)
        await call.message.answer(text, disable_web_page_preview=True)
        await asyncio.sleep(0.3)

@dp.callback_query(F.data == "notif_feed")
async def cb_bids(call: types.CallbackQuery):
    await call.answer("⏳")
    bids = await get_my_bids()
    if not bids:
        await call.message.edit_text("📤 <b>Мої ставки</b>\nАктивних ставок немає.", reply_markup=notif_menu())
        return
    await call.message.edit_text(f"📤 <b>Мої ставки</b> ({len(bids)}):", reply_markup=notif_menu())
    for bid in bids[:8]:
        await call.message.answer(format_bid(bid), disable_web_page_preview=True)
        await asyncio.sleep(0.3)

@dp.callback_query(F.data == "notif_profile")
async def cb_profile(call: types.CallbackQuery):
    await call.answer("⏳")
    profile = await get_profile()
    if not profile:
        await call.message.edit_text("⚠️ Не вдалося завантажити профіль.", reply_markup=notif_menu())
        return
    attrs = profile.get("attributes", {})
    login = attrs.get("login", "—")
    rating = attrs.get("rating", 0)
    reviews = attrs.get("reviews_count", 0)
    balance = attrs.get("balance") or {}
    amount = balance.get("amount", 0)
    currency = balance.get("currency", "UAH")
    rate = await get_usd_rate()
    usd = round(amount / rate) if currency == "UAH" else amount
    await call.message.edit_text(
        f"👤 <b>Мій профіль</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Логін:    <b>{login}</b>\n"
        f"⭐ Рейтинг:  <b>{rating}</b>\n"
        f"💬 Відгуків: <b>{reviews}</b>\n"
        f"💰 Баланс:   <b>{amount} {currency}</b> (~${usd})\n"
        f"🔗 <a href='https://freelancehunt.com/freelancer/{login}.html'>Відкрити</a>",
        reply_markup=notif_menu()
    )

# ── Трекер ────────────────────────────────────────────────
@dp.callback_query(F.data == "menu_tracker")
async def cb_tracker(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("📋 <b>Трекер замовлень</b>\nОбери фільтр:", reply_markup=tracker_menu())

@dp.callback_query(F.data.startswith("tracker_"))
async def cb_tracker_filter(call: types.CallbackQuery):
    await call.answer("⏳")
    f = call.data.replace("tracker_", "")
    tracker = load_tracker()
    if not tracker:
        await call.message.edit_text("📋 Трекер порожній.\nДодай замовлення через кнопку 📤.", reply_markup=tracker_menu())
        return
    filtered = tracker if f == "all" else {k: v for k, v in tracker.items() if v.get("status") == f}
    if not filtered:
        await call.message.edit_text("📋 Замовлень з таким статусом немає.", reply_markup=tracker_menu())
        return
    icons = {"sent":"📤","replied":"💬","working":"🔧","won":"🏆","lost":"❌"}
    text = "📋 <b>Трекер замовлень:</b>\n━━━━━━━━━━━━━━━━━━\n"
    for pid, info in list(filtered.items())[-15:]:
        icon = icons.get(info.get("status",""), "•")
        text += f"{icon} <a href='{info['url']}'>{info['title'][:40]}</a>"
        if info.get("budget"):
            text += f" — {info['budget']}"
        text += f"\n    <i>{info.get('updated','')}</i>\n"
    await call.message.edit_text(text, reply_markup=tracker_menu(), disable_web_page_preview=True)

# ── Обране ────────────────────────────────────────────────
@dp.callback_query(F.data == "menu_favorites")
async def cb_favorites(call: types.CallbackQuery):
    await call.answer()
    favs = load_favorites()
    if not favs:
        await call.message.edit_text("⭐ <b>Обране</b>\n\nПоки порожнє.\nНатискай ⭐ під замовленнями.", reply_markup=back_home())
        return
    text = f"⭐ <b>Обране</b> ({len(favs)}):\n━━━━━━━━━━━━━━━━━━\n"
    for i, f in enumerate(favs[-15:], 1):
        text += f"{i}. <a href='{f['url']}'>{f['title'][:45]}</a>"
        if f.get("budget"):
            text += f" — {f['budget']}"
        text += "\n"
    await call.message.edit_text(text, reply_markup=back_home(), disable_web_page_preview=True)

# ── Статистика ────────────────────────────────────────────
@dp.callback_query(F.data == "menu_stats")
async def cb_stats(call: types.CallbackQuery):
    await call.answer("⏳")
    stats = load_stats(); s = load_settings()
    seen = load_seen(); favs = load_favorites()
    tracker = load_tracker()
    won = sum(1 for v in tracker.values() if v.get("status") == "won")
    rate = await get_usd_rate()
    await call.message.edit_text(
        "📊 <b>Статистика FreelanceRadar</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👁  Показано замовлень:    <b>{stats.get('total_seen',0)}</b>\n"
        f"✍️  Відгуків згенеровано: <b>{stats.get('replies_generated',0)}</b>\n"
        f"⭐  В обраному:            <b>{len(favs)}</b>\n"
        f"🚫  Пропущено:             <b>{stats.get('skipped',0)}</b>\n"
        f"🏆  Виграно:               <b>{won}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💱  1 USD = {rate:.2f} UAH\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰  Мін. бюджет:  {s.get('min_budget',0)} UAH\n"
        f"📊  Макс. ставок: {s.get('max_bids',999)}\n"
        f"😴  Тихий режим:  {s.get('quiet_start')}:00—{s.get('quiet_end')}:00\n"
        f"{'⏸  На паузі' if s.get('paused') else '▶️  Активний'}",
        reply_markup=back_home()
    )

# ── Тренди ────────────────────────────────────────────────
@dp.callback_query(F.data == "menu_trends")
async def cb_trends(call: types.CallbackQuery):
    await call.answer("⏳")
    await call.message.edit_text("📈 <b>Аналізую ринок...</b>", reply_markup=back_home())
    projects = await get_latest_projects()
    analysis = await analyze_skills_trend(projects)
    await call.message.edit_text(
        f"📈 <b>Аналіз ринку Freelancehunt</b>\n━━━━━━━━━━━━━━━━━━━━\n{analysis}",
        reply_markup=back_home()
    )

# ── Налаштування ──────────────────────────────────────────
@dp.callback_query(F.data == "menu_settings")
async def cb_settings(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("⚙️ <b>Налаштування</b>\nНатисни на параметр щоб змінити:", reply_markup=settings_menu(load_settings()))

@dp.callback_query(F.data == "set_pause")
async def cb_set_pause(call: types.CallbackQuery):
    s = load_settings(); s["paused"] = not s.get("paused", False); save_settings(s)
    await call.answer("⏸ Пауза" if s["paused"] else "▶️ Активний")
    await call.message.edit_reply_markup(reply_markup=settings_menu(s))

@dp.callback_query(F.data == "set_budget")
async def cb_set_budget(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("💰 Введи мінімальний бюджет у UAH (наприклад: <code>500</code>):")
    await state.set_state(SettingsState.waiting_budget)

@dp.message(SettingsState.waiting_budget)
async def state_budget(msg: Message, state: FSMContext):
    if msg.text.strip().isdigit():
        s = load_settings(); s["min_budget"] = int(msg.text.strip()); save_settings(s)
        await msg.answer(f"✅ Мін. бюджет: <b>{msg.text} UAH</b>", reply_markup=main_menu())
        await state.clear()
    else:
        await msg.answer("❌ Введи число, наприклад: <code>500</code>")

@dp.callback_query(F.data == "set_maxbids")
async def cb_set_maxbids(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("📊 Введи максимальну кількість ставок (наприклад: <code>15</code>):")
    await state.set_state(SettingsState.waiting_maxbids)

@dp.message(SettingsState.waiting_maxbids)
async def state_maxbids(msg: Message, state: FSMContext):
    if msg.text.strip().isdigit():
        s = load_settings(); s["max_bids"] = int(msg.text.strip()); save_settings(s)
        await msg.answer(f"✅ Макс. ставок: <b>{msg.text}</b>", reply_markup=main_menu())
        await state.clear()
    else:
        await msg.answer("❌ Введи число")

@dp.callback_query(F.data == "set_quiet")
async def cb_set_quiet(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("😴 Введи тихий режим: <code>23 8</code> (з 23:00 до 8:00):")
    await state.set_state(SettingsState.waiting_quiet)

@dp.message(SettingsState.waiting_quiet)
async def state_quiet(msg: Message, state: FSMContext):
    parts = msg.text.strip().split()
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        s = load_settings(); s["quiet_start"] = int(parts[0]); s["quiet_end"] = int(parts[1]); save_settings(s)
        await msg.answer(f"✅ Тихий режим: {parts[0]}:00 — {parts[1]}:00", reply_markup=main_menu())
        await state.clear()
    else:
        await msg.answer("❌ Формат: <code>23 8</code>")

@dp.callback_query(F.data == "set_skills")
async def cb_set_skills(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    s = load_settings()
    await call.message.answer(
        f"🛠 <b>Поточні навички:</b>\n<code>{', '.join(s.get('skills',[]))}</code>\n\n"
        "Введи нові через пробіл:\n<code>HTML CSS Python Telegram сайт</code>"
    )
    await state.set_state(SettingsState.waiting_skills)

@dp.message(SettingsState.waiting_skills)
async def state_skills(msg: Message, state: FSMContext):
    skills = msg.text.strip().split()
    s = load_settings(); s["skills"] = skills; save_settings(s)
    await msg.answer(f"✅ Навички: <code>{', '.join(skills)}</code>", reply_markup=main_menu())
    await state.clear()

@dp.callback_query(F.data == "set_blacklist")
async def cb_set_blacklist(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    s = load_settings()
    await call.message.answer(
        f"🚫 <b>Чорний список:</b>\n<code>{', '.join(s.get('blacklist',[])) or 'порожній'}</code>\n\n"
        "Введи слова через пробіл:"
    )
    await state.set_state(SettingsState.waiting_blacklist)

@dp.message(SettingsState.waiting_blacklist)
async def state_blacklist(msg: Message, state: FSMContext):
    words = msg.text.strip().split()
    s = load_settings(); s["blacklist"] = words; save_settings(s)
    await msg.answer(f"✅ Чорний список: <code>{', '.join(words)}</code>", reply_markup=main_menu())
    await state.clear()

@dp.callback_query(F.data == "set_vip")
async def cb_set_vip(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("🔥 Введи суму VIP бюджету в UAH:")
    await state.set_state(SettingsState.waiting_vip)

@dp.message(SettingsState.waiting_vip)
async def state_vip(msg: Message, state: FSMContext):
    if msg.text.strip().isdigit():
        s = load_settings(); s["vip_budget"] = int(msg.text.strip()); save_settings(s)
        await msg.answer(f"✅ VIP бюджет: <b>{msg.text} UAH</b>", reply_markup=main_menu())
        await state.clear()
    else:
        await msg.answer("❌ Введи число")

@dp.callback_query(F.data == "set_done")
async def cb_set_done(call: types.CallbackQuery):
    await call.answer("✅")
    await call.message.edit_text("📌 <b>Головне меню:</b>", reply_markup=home_inline())

# ── Шаблони ───────────────────────────────────────────────
@dp.callback_query(F.data == "menu_templates")
async def cb_templates(call: types.CallbackQuery):
    await call.answer()
    templates = load_templates()
    await call.message.edit_text(
        f"📝 <b>Шаблони відгуків</b> ({len(templates)}):\n━━━━━━━━━━━━━━━━━━",
        reply_markup=templates_menu(templates)
    )

@dp.callback_query(F.data == "tpl_add")
async def cb_tpl_add(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer(
        "📝 Введи шаблон у форматі:\n<code>Назва | Текст шаблону</code>\n\n"
        "Приклад:\n<code>Стандартний | Привіт! Маю досвід у веб-розробці...</code>"
    )
    await state.set_state(TemplateState.waiting_input)

@dp.message(TemplateState.waiting_input)
async def state_template(msg: Message, state: FSMContext):
    parts = msg.text.strip().split("|", 1)
    if len(parts) < 2:
        await msg.answer("❌ Формат: <code>Назва | Текст</code>")
        return
    name, text = parts[0].strip(), parts[1].strip()
    templates = load_templates(); templates.append({"name": name, "text": text}); save_templates(templates)
    await msg.answer(f"✅ Шаблон <b>{name}</b> збережено!", reply_markup=main_menu())
    await state.clear()

@dp.callback_query(F.data.startswith("tpl_view:"))
async def cb_tpl_view(call: types.CallbackQuery):
    idx = int(call.data.split(":")[1]); templates = load_templates()
    if idx < len(templates):
        t = templates[idx]
        await call.answer()
        await call.message.answer(f"📝 <b>{t['name']}</b>\n━━━━━━━━━━━━━━\n{t['text']}", reply_markup=back_home())

@dp.callback_query(F.data.startswith("tpl_del:"))
async def cb_tpl_del(call: types.CallbackQuery):
    idx = int(call.data.split(":")[1]); templates = load_templates()
    if idx < len(templates):
        name = templates[idx]["name"]; templates.pop(idx); save_templates(templates)
        await call.answer(f"🗑 «{name}» видалено")
        await call.message.edit_reply_markup(reply_markup=templates_menu(templates))

# ── Профіль ───────────────────────────────────────────────
@dp.callback_query(F.data == "menu_profile")
async def cb_profile_main(call: types.CallbackQuery):
    await call.answer("⏳")
    profile = await get_profile()
    if not profile:
        await call.message.edit_text("⚠️ Не вдалося завантажити профіль.", reply_markup=back_home())
        return
    attrs = profile.get("attributes", {})
    login = attrs.get("login", "—"); rating = attrs.get("rating", 0)
    reviews = attrs.get("reviews_count", 0)
    balance = attrs.get("balance") or {}
    amount = balance.get("amount", 0); currency = balance.get("currency", "UAH")
    rate = await get_usd_rate(); usd = round(amount / rate) if currency == "UAH" else amount
    await call.message.edit_text(
        f"👤 <b>Мій профіль Freelancehunt</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Логін:    <b>{login}</b>\n⭐ Рейтинг:  <b>{rating}</b>\n"
        f"💬 Відгуків: <b>{reviews}</b>\n💰 Баланс:   <b>{amount} {currency}</b> (~${usd})\n"
        f"🔗 <a href='https://freelancehunt.com/freelancer/{login}.html'>Відкрити профіль</a>",
        reply_markup=back_home()
    )

# ── Допомога ──────────────────────────────────────────────
@dp.callback_query(F.data == "menu_help")
async def cb_help(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "❓ <b>FreelanceRadar — Довідка</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔍 <b>Замовлення</b> — перевірити нові, пауза, скинути історію\n"
        "🔔 <b>Повідомлення</b> — листування, ставки, профіль\n"
        "📋 <b>Трекер</b> — статуси твоїх замовлень\n"
        "⭐ <b>Обране</b> — збережені замовлення\n"
        "📊 <b>Статистика</b> — вся активність\n"
        "📈 <b>Тренди</b> — AI аналіз ринку\n"
        "⚙️ <b>Налаштування</b> — фільтри кнопками\n"
        "📝 <b>Шаблони</b> — готові тексти відгуків\n"
        "👤 <b>Профіль</b> — баланс, рейтинг\n\n"
        "<b>Під кожним замовленням:</b>\n"
        "✍️ Відклик — AI пише персональний текст\n"
        "🤖 Оцінка — AI оцінює 1-10 чи варто братись\n"
        "⭐ Зберегти · 🚫 Пропустити · 📤 Трекер",
        reply_markup=back_home()
    )

# ── Callbacks карток проектів ─────────────────────────────
@dp.callback_query(F.data.startswith("reply:"))
async def cb_reply(call: types.CallbackQuery):
    await call.answer("⏳")
    parts = call.data.split(":", 4)
    if len(parts) < 5: return
    _, pid, title, skills, description = parts
    templates = load_templates()
    if templates:
        b = InlineKeyboardBuilder()
        b.button(text="🤖 AI відклик", callback_data=f"ai_reply:{pid}:{title}:{skills}:{description}")
        for i, t in enumerate(templates[:4]):
            b.button(text=f"📝 {t['name'][:20]}", callback_data=f"tpl_reply:{i}")
        b.adjust(1)
        await call.message.answer("Оберіть тип відклику:", reply_markup=b.as_markup())
    else:
        await call.message.answer("✍️ Генерую AI відклик...")
        reply_text = await generate_reply(title, description, skills)
        inc_stat("replies_generated")
        await call.message.answer(f"💬 <b>AI відклик:</b>\n━━━━━━━━━━━━━━━━━━\n{reply_text}")

@dp.callback_query(F.data.startswith("ai_reply:"))
async def cb_ai_reply(call: types.CallbackQuery):
    await call.answer("⏳")
    parts = call.data.split(":", 4)
    if len(parts) < 5: return
    _, pid, title, skills, description = parts
    reply_text = await generate_reply(title, description, skills)
    inc_stat("replies_generated")
    await call.message.answer(f"💬 <b>AI відклик:</b>\n━━━━━━━━━━━━━━━━━━\n{reply_text}")

@dp.callback_query(F.data.startswith("tpl_reply:"))
async def cb_tpl_reply(call: types.CallbackQuery):
    idx = int(call.data.split(":")[1]); templates = load_templates()
    if idx < len(templates):
        t = templates[idx]
        await call.answer()
        await call.message.answer(f"📝 <b>{t['name']}</b>\n━━━━━━━━━━━━━━\n{t['text']}")

@dp.callback_query(F.data.startswith("score:"))
async def cb_score(call: types.CallbackQuery):
    await call.answer("🤖 Оцінюю...")
    parts = call.data.split(":", 4)
    if len(parts) < 5: return
    _, pid, title, skills, description = parts
    result = await score_project(title, description, skills)
    score = result.get("score", 5); pros = result.get("pros","—"); cons = result.get("cons","—"); verdict = result.get("verdict","Нормально")
    filled = "🟩" * score + "⬜" * (10 - score)
    await call.message.answer(
        f"🤖 <b>Оцінка AI: {score}/10</b>\n{filled}\n<b>{verdict}</b>\n━━━━━━━━━━\n✅ {pros}\n❌ {cons}"
    )

@dp.callback_query(F.data.startswith("fav:"))
async def cb_fav(call: types.CallbackQuery):
    parts = call.data.split(":", 3)
    pid = parts[1] if len(parts)>1 else ""; title = parts[2] if len(parts)>2 else pid; budget = parts[3] if len(parts)>3 else ""
    favs = load_favorites()
    if any(f["id"] == pid for f in favs):
        await call.answer("Вже збережено ⭐"); return
    favs.append({"id":pid,"title":title,"budget":budget,"url":f"https://freelancehunt.com/project/{pid}.html"})
    save_favorites(favs); await call.answer("⭐ Збережено!")

@dp.callback_query(F.data.startswith("skip:"))
async def cb_skip(call: types.CallbackQuery):
    inc_stat("skipped"); await call.answer("🚫 Пропущено")
    try: await call.message.delete()
    except: pass

@dp.callback_query(F.data.startswith("track:"))
async def cb_track(call: types.CallbackQuery):
    parts = call.data.split(":", 4)
    if len(parts) < 5: return
    _, pid, title, budget, status = parts
    set_status(pid, title, f"https://freelancehunt.com/project/{pid}.html", status, budget)
    if status == "won": inc_stat("won"); await call.answer("🏆 Виграно!")
    else: await call.answer(f"✅ {STATUSES.get(status, status)}")
    if status == "sent":
        await call.message.answer(
            f"📤 <b>Відклик надіслано</b>\n<i>{title}</i>\n\nОновіть статус:",
            reply_markup=tracker_status_keyboard(pid, title, budget)
        )

# ── Команди ──────────────────────────────────────────────
@dp.message(Command("check"))
async def cmd_check(msg: Message):
    await msg.answer("🔍 Перевіряю...")
    await check_new_projects(force=True)

@dp.message(Command("clear"))
async def cmd_clear(msg: Message):
    save_seen(set()); await msg.answer("🗑 Історія очищена.")

@dp.message(Command("rate"))
async def cmd_rate(msg: Message):
    rate = await get_usd_rate(); await msg.answer(f"💱 1 USD = <b>{rate:.2f} UAH</b>")

# ── Моніторинг ────────────────────────────────────────────
async def check_new_projects(force=False):
    settings = load_settings()
    if settings.get("paused") and not force: return
    if is_quiet_time() and not force: return
    seen = load_seen(); projects = await get_latest_projects(); new_count = 0
    if not seen and not force:
        for p in projects: seen.add(str(p.get("id","")))
        save_seen(seen); log.info(f"Перший запуск: запам'ятали {len(seen)} проектів"); return
    for project in projects:
        pid = str(project.get("id",""))
        if pid in seen: continue
        seen.add(pid)
        if not is_relevant(project, settings): continue
        text, title, description, skills, url, budget = await format_project(project)
        amount = (project.get("attributes",{}).get("budget") or {}).get("amount") or 0
        vip_min = settings.get("vip_budget", 2000)
        prefix = f"🔥🔥🔥 <b>VIP ЗАМОВЛЕННЯ! {amount} UAH!</b>\n━━━━━━━━━━━━━━━━━━\n" if amount >= vip_min else ""
        try:
            await bot.send_message(MY_CHAT_ID, prefix+text, reply_markup=project_card_keyboard(pid,title,skills,description,url,budget), disable_web_page_preview=True)
            inc_stat("total_seen"); new_count += 1; await asyncio.sleep(0.5)
        except Exception as e: log.error(f"Помилка: {e}")
    save_seen(seen)
    if force and new_count == 0:
        await bot.send_message(MY_CHAT_ID, "😴 Нових підходящих замовлень немає.", reply_markup=home_inline())

async def check_notifications():
    last = load_last_notif()
    threads = await get_threads()
    for t in threads:
        unread = (t.get("attributes") or {}).get("unread_count", 0) or 0
        tid = str(t.get("id",""))
        if unread and tid != str(last.get("thread_id")):
            text, _ = format_thread(t)
            await bot.send_message(MY_CHAT_ID, f"💬 <b>Нове повідомлення!</b>\n━━━━━━━━━━━━━━\n{text}", disable_web_page_preview=True)
            last["thread_id"] = tid; save_last_notif(last); break

async def daily_digest():
    while True:
        now = datetime.now()
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now.hour >= 9: target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        stats = load_stats(); favs = load_favorites()
        tracker = load_tracker(); won = sum(1 for v in tracker.values() if v.get("status")=="won")
        rate = await get_usd_rate()
        await bot.send_message(MY_CHAT_ID,
            f"☀️ <b>Доброго ранку!</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Вчора:\n👁 Показано: {stats.get('total_seen',0)}\n"
            f"✍️ Відгуків: {stats.get('replies_generated',0)}\n🏆 Виграно: {won}\n⭐ В обраному: {len(favs)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n💱 1 USD = {rate:.2f} UAH",
            reply_markup=home_inline()
        )

_started = False

async def monitor_loop():
    global _started
    if not _started:
        _started = True
        await bot.send_message(MY_CHAT_ID,
            "🚀 <b>FreelanceRadar запущено!</b>\nПеревіряю нові замовлення кожні 2 хв. 👇",
            reply_markup=home_inline()
        )
    while True:
        try:
            await check_new_projects()
            await check_notifications()
        except Exception as e:
            log.error(f"Помилка: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

async def main():
    asyncio.create_task(monitor_loop())
    asyncio.create_task(daily_digest())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
