import asyncio
import logging
import json
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

from freelancehunt import get_latest_projects, format_project
from ai_reply import generate_reply

# ── Конфиг ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MY_CHAT_ID     = int(os.getenv("MY_CHAT_ID"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "120"))  # секунды между проверками

SEEN_FILE = "seen_projects.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN, parse_mode="HTML")
dp  = Dispatcher()

# ── Хранилище увиденных проектов ─────────────────────────
def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

# ── Команды ──────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    await msg.answer(
        "👋 Привіт! Я <b>FreelanceRadar</b> — твій помічник для пошуку замовлень.\n\n"
        "Я буду моніторити Freelancehunt кожні 2 хвилини та надсилати нові проекти "
        "разом з готовим AI-відкликом.\n\n"
        "📌 Команди:\n"
        "/start — запустити бота\n"
        "/check — перевірити зараз\n"
        "/clear — очистити історію переглянутих\n"
        "/status — статус бота"
    )

@dp.message(Command("check"))
async def cmd_check(msg: types.Message):
    await msg.answer("🔍 Перевіряю нові замовлення...")
    await check_new_projects(force=True)

@dp.message(Command("clear"))
async def cmd_clear(msg: types.Message):
    save_seen(set())
    await msg.answer("🗑 Історія очищена. Наступна перевірка покаже останні проекти.")

@dp.message(Command("status"))
async def cmd_status(msg: types.Message):
    seen = load_seen()
    await msg.answer(
        f"✅ Бот працює\n"
        f"👁 Переглянуто проектів: {len(seen)}\n"
        f"⏱ Інтервал перевірки: {CHECK_INTERVAL} сек."
    )

# ── Кнопка "Згенерувати відклик" ─────────────────────────
@dp.callback_query(F.data.startswith("reply:"))
async def cb_generate_reply(call: types.CallbackQuery):
    await call.answer("⏳ Генерую відклик...")

    parts = call.data.split(":", 3)
    # reply:<title>:<skills>:<description>
    if len(parts) < 4:
        await call.message.answer("⚠️ Помилка даних проекту.")
        return

    _, title, skills, description = parts

    await call.message.answer("✍️ <b>Генерую відклик через AI...</b>")
    reply_text = await generate_reply(title, description, skills)

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Скопіювати", callback_data="copy_hint")

    await call.message.answer(
        f"💬 <b>Готовий відклик:</b>\n\n{reply_text}",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "copy_hint")
async def cb_copy_hint(call: types.CallbackQuery):
    await call.answer("Виділи текст вище і скопіюй 👆", show_alert=True)

# ── Основная логика мониторинга ──────────────────────────
async def check_new_projects(force: bool = False):
    seen = load_seen()
    projects = await get_latest_projects()

    new_count = 0
    for project in projects:
        pid = str(project.get("id", ""))
        if pid in seen and not force:
            continue

        seen.add(pid)
        text, title, description, skills, url = format_project(project)

        # Кнопки
        builder = InlineKeyboardBuilder()
        safe_title = title[:50].replace(":", "")
        safe_skills = skills[:50].replace(":", "")
        safe_desc = description[:200].replace(":", "")

        builder.row(
            InlineKeyboardButton(
                text="✍️ Згенерувати відклик",
                callback_data=f"reply:{safe_title}:{safe_skills}:{safe_desc}"
            )
        )
        builder.row(
            InlineKeyboardButton(text="🔗 Відкрити проект", url=url)
        )

        try:
            await bot.send_message(
                MY_CHAT_ID,
                text,
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True
            )
            new_count += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            log.error(f"Помилка відправки: {e}")

    save_seen(seen)

    if force and new_count == 0:
        await bot.send_message(MY_CHAT_ID, "😴 Нових замовлень поки немає.")

    if new_count > 0:
        log.info(f"Надіслано {new_count} нових проектів")

# ── Фоновый мониторинг ───────────────────────────────────
async def monitor_loop():
    log.info("Моніторинг запущено")
    await bot.send_message(
        MY_CHAT_ID,
        f"🚀 <b>FreelanceRadar запущено!</b>\n"
        f"Перевіряю нові замовлення кожні {CHECK_INTERVAL} сек.\n"
        f"Напиши /check щоб перевірити зараз."
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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
