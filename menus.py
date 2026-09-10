from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

def main_menu():
    """Главное меню — Reply клавиатура"""
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text="🔍 Перевірити зараз"),
        KeyboardButton(text="🔔 Повідомлення"),
    )
    b.row(
        KeyboardButton(text="⭐ Обране"),
        KeyboardButton(text="📋 Трекер"),
    )
    b.row(
        KeyboardButton(text="📊 Статистика"),
        KeyboardButton(text="📈 Тренди"),
    )
    b.row(
        KeyboardButton(text="⚙️ Налаштування"),
        KeyboardButton(text="❓ Допомога"),
    )
    return b.as_markup(resize_keyboard=True)

def settings_menu(settings: dict):
    """Меню настроек — Inline"""
    b = InlineKeyboardBuilder()
    paused   = settings.get("paused", False)
    budget   = settings.get("min_budget", 0)
    max_bids = settings.get("max_bids", 999)
    qs       = settings.get("quiet_start", 23)
    qe       = settings.get("quiet_end", 8)

    b.row(InlineKeyboardButton(
        text=f"{'⏸ Пауза ON' if paused else '▶️ Пауза OFF'} — натисни",
        callback_data="set_pause"
    ))
    b.row(InlineKeyboardButton(
        text=f"💰 Мін. бюджет: {budget} UAH",
        callback_data="set_budget"
    ))
    b.row(InlineKeyboardButton(
        text=f"📊 Макс. ставок: {max_bids}",
        callback_data="set_maxbids"
    ))
    b.row(InlineKeyboardButton(
        text=f"😴 Тихий режим: {qs}:00—{qe}:00",
        callback_data="set_quiet"
    ))
    b.row(InlineKeyboardButton(
        text="🛠 Навички (редагувати)",
        callback_data="set_skills"
    ))
    b.row(InlineKeyboardButton(
        text="🚫 Чорний список",
        callback_data="set_blacklist"
    ))
    b.row(InlineKeyboardButton(
        text="🔥 VIP бюджет: " + str(settings.get("vip_budget", 2000)) + " UAH",
        callback_data="set_vip"
    ))
    b.row(InlineKeyboardButton(text="✅ Готово", callback_data="set_done"))
    return b.as_markup()

def project_card_keyboard(pid, title, skills, description, url, budget):
    """Клавиатура под карточкой проекта"""
    b = InlineKeyboardBuilder()
    s = lambda x: str(x)[:55].replace(":", "·")
    b.row(
        InlineKeyboardButton(text="✍️ Відклик",     callback_data=f"reply:{s(pid)}:{s(title)}:{s(skills)}:{s(description)}"),
        InlineKeyboardButton(text="🤖 Оцінка",      callback_data=f"score:{s(pid)}:{s(title)}:{s(skills)}:{s(description)}"),
    )
    b.row(
        InlineKeyboardButton(text="⭐ Зберегти",    callback_data=f"fav:{pid}:{s(title)}:{s(budget)}"),
        InlineKeyboardButton(text="🚫 Пропустити",  callback_data=f"skip:{pid}"),
    )
    b.row(
        InlineKeyboardButton(text="📤 Надіслав відклик", callback_data=f"track:{pid}:{s(title)}:{s(budget)}:sent"),
    )
    b.row(InlineKeyboardButton(text="🔗 Відкрити на сайті", url=url))
    return b.as_markup()

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

def notifications_menu():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💬 Листування",       callback_data="notif_threads"))
    b.row(InlineKeyboardButton(text="📤 Мої ставки",       callback_data="notif_feed"))
    b.row(InlineKeyboardButton(text="👤 Мій профіль",      callback_data="notif_profile"))
    return b.as_markup()
