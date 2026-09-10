from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


# ── Головна Reply-клавіатура (завжди внизу) ──────────────
def main_menu():
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text="🏠 Головне меню"),
        KeyboardButton(text="🔍 Перевірити зараз"),
    )
    return b.as_markup(resize_keyboard=True)


# ── Головне Inline-меню ───────────────────────────────────
def home_inline():
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🔍 Замовлення",    callback_data="menu_orders"),
        InlineKeyboardButton(text="🔔 Повідомлення",  callback_data="menu_notif"),
    )
    b.row(
        InlineKeyboardButton(text="📋 Трекер",        callback_data="menu_tracker"),
        InlineKeyboardButton(text="⭐ Обране",         callback_data="menu_favorites"),
    )
    b.row(
        InlineKeyboardButton(text="📊 Статистика",    callback_data="menu_stats"),
        InlineKeyboardButton(text="📈 Тренди",        callback_data="menu_trends"),
    )
    b.row(
        InlineKeyboardButton(text="⚙️ Налаштування",  callback_data="menu_settings"),
        InlineKeyboardButton(text="📝 Шаблони",       callback_data="menu_templates"),
    )
    b.row(
        InlineKeyboardButton(text="👤 Профіль",       callback_data="menu_profile"),
        InlineKeyboardButton(text="❓ Допомога",       callback_data="menu_help"),
    )
    return b.as_markup()


# ── Підменю: Замовлення ───────────────────────────────────
def orders_menu():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔍 Перевірити нові зараз",     callback_data="orders_check"))
    b.row(InlineKeyboardButton(text="🗑 Скинути історію (показати всі)", callback_data="orders_clear"))
    b.row(
        InlineKeyboardButton(text="⏸ Пауза моніторингу",   callback_data="orders_pause"),
        InlineKeyboardButton(text="▶️ Відновити",           callback_data="orders_resume"),
    )
    b.row(InlineKeyboardButton(text="💱 Курс USD",           callback_data="orders_rate"))
    b.row(InlineKeyboardButton(text="◀️ Назад",              callback_data="menu_home"))
    return b.as_markup()


# ── Підменю: Повідомлення ─────────────────────────────────
def notif_menu():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💬 Листування",          callback_data="notif_threads"))
    b.row(InlineKeyboardButton(text="📤 Мої ставки",          callback_data="notif_feed"))
    b.row(InlineKeyboardButton(text="👤 Мій профіль",         callback_data="notif_profile"))
    b.row(InlineKeyboardButton(text="◀️ Назад",               callback_data="menu_home"))
    return b.as_markup()


# ── Підменю: Налаштування ─────────────────────────────────
def settings_menu(settings: dict):
    b = InlineKeyboardBuilder()
    paused   = settings.get("paused", False)
    budget   = settings.get("min_budget", 0)
    max_bids = settings.get("max_bids", 999)
    qs       = settings.get("quiet_start", 23)
    qe       = settings.get("quiet_end", 8)
    vip      = settings.get("vip_budget", 2000)

    b.row(InlineKeyboardButton(
        text=f"{'⏸ Моніторинг: ПАУЗА' if paused else '▶️ Моніторинг: АКТИВНИЙ'}",
        callback_data="set_pause"
    ))
    b.row(
        InlineKeyboardButton(text=f"💰 Мін. бюджет: {budget} UAH", callback_data="set_budget"),
        InlineKeyboardButton(text=f"📊 Макс. ставок: {max_bids}",  callback_data="set_maxbids"),
    )
    b.row(
        InlineKeyboardButton(text=f"😴 Тихий: {qs}:00—{qe}:00",   callback_data="set_quiet"),
        InlineKeyboardButton(text=f"🔥 VIP: {vip}+ UAH",           callback_data="set_vip"),
    )
    b.row(InlineKeyboardButton(text="🛠 Навички",                   callback_data="set_skills"))
    b.row(InlineKeyboardButton(text="🚫 Чорний список",             callback_data="set_blacklist"))
    b.row(InlineKeyboardButton(text="◀️ Назад",                     callback_data="menu_home"))
    return b.as_markup()


# ── Підменю: Шаблони ──────────────────────────────────────
def templates_menu(templates: list):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Додати шаблон",      callback_data="tpl_add"))
    for i, t in enumerate(templates[:8]):
        b.row(
            InlineKeyboardButton(text=f"📝 {t['name'][:25]}",  callback_data=f"tpl_view:{i}"),
            InlineKeyboardButton(text="🗑",                    callback_data=f"tpl_del:{i}"),
        )
    b.row(InlineKeyboardButton(text="◀️ Назад",              callback_data="menu_home"))
    return b.as_markup()


# ── Підменю: Трекер ───────────────────────────────────────
def tracker_menu():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📋 Всі замовлення",          callback_data="tracker_all"))
    b.row(
        InlineKeyboardButton(text="📤 Надіслані",   callback_data="tracker_sent"),
        InlineKeyboardButton(text="💬 Відповіли",  callback_data="tracker_replied"),
    )
    b.row(
        InlineKeyboardButton(text="🏆 Виграні",    callback_data="tracker_won"),
        InlineKeyboardButton(text="❌ Програні",   callback_data="tracker_lost"),
    )
    b.row(InlineKeyboardButton(text="◀️ Назад",    callback_data="menu_home"))
    return b.as_markup()


# ── Клавіатура під карткою проекту ───────────────────────
def project_card_keyboard(pid, title, skills, description, url, budget):
    b = InlineKeyboardBuilder()
    s = lambda x: str(x)[:55].replace(":", "·")
    b.row(
        InlineKeyboardButton(text="✍️ Відклик",  callback_data=f"reply:{s(pid)}:{s(title)}:{s(skills)}:{s(description)}"),
        InlineKeyboardButton(text="🤖 Оцінка",   callback_data=f"score:{s(pid)}:{s(title)}:{s(skills)}:{s(description)}"),
    )
    b.row(
        InlineKeyboardButton(text="⭐ Зберегти",  callback_data=f"fav:{pid}:{s(title)}:{s(budget)}"),
        InlineKeyboardButton(text="🚫 Пропустити",callback_data=f"skip:{pid}"),
    )
    b.row(
        InlineKeyboardButton(text="📤 Відклик надіслано", callback_data=f"track:{pid}:{s(title)}:{s(budget)}:sent"),
    )
    b.row(InlineKeyboardButton(text="🔗 Відкрити на сайті", url=url))
    return b.as_markup()


# ── Клавіатура статусів трекера ───────────────────────────
def tracker_status_keyboard(pid, title, budget):
    b = InlineKeyboardBuilder()
    s = lambda x: str(x)[:55].replace(":", "·")
    b.row(
        InlineKeyboardButton(text="💬 Відповіли",  callback_data=f"track:{pid}:{s(title)}:{s(budget)}:replied"),
        InlineKeyboardButton(text="🔧 В роботі",   callback_data=f"track:{pid}:{s(title)}:{s(budget)}:working"),
    )
    b.row(
        InlineKeyboardButton(text="🏆 Виграно!",   callback_data=f"track:{pid}:{s(title)}:{s(budget)}:won"),
        InlineKeyboardButton(text="❌ Програно",   callback_data=f"track:{pid}:{s(title)}:{s(budget)}:lost"),
    )
    return b.as_markup()


# ── Кнопка "Назад у меню" ────────────────────────────────
def back_home():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Головне меню", callback_data="menu_home"))
    return b.as_markup()
