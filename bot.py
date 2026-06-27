"""
Telegram-бот (aiogram 3.x).

MVP работает на long polling — проще всего для запуска.
Для продакшна переключитесь на webhook (комментарий внизу).

История диалога хранится в памяти процесса (словарь chat_id -> messages).
Это нормально для MVP; при перезапуске обнуляется. Позже — Redis/БД.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

import agent
import config

logging.basicConfig(level=logging.INFO)
router = Router()

# chat_id -> история сообщений для агента
SESSIONS: dict[int, list[dict]] = {}

WELCOME = (
    "Привет! Я помогаю с рекламой по двум направлениям:\n\n"
    "📊 *Аналитика кампаний* — спрашивай про метрики, динамику, аномалии.\n"
    "   Например: «Что с CPA в clinic-stoma за неделю?» или «Топ-3 проекта по расходу».\n\n"
    "✍️ *Директ* — семантика и объявления.\n"
    "   Например: «Расширь ключи: кухни на заказ» или «Напиши объявление для autoservice».\n\n"
    "/reset — очистить контекст диалога."
)


@router.message(Command("start"))
async def cmd_start(message: Message):
    SESSIONS[message.chat.id] = []
    await message.answer(WELCOME, parse_mode="Markdown")


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    SESSIONS[message.chat.id] = []
    await message.answer("Контекст очищен.")


@router.message()
async def handle_text(message: Message):
    if not message.text:
        return
    chat_id = message.chat.id
    history = SESSIONS.get(chat_id, [])

    await message.bot.send_chat_action(chat_id, "typing")
    try:
        # агент синхронный — уводим в отдельный поток, чтобы не блокировать бота
        answer, history = await asyncio.to_thread(agent.run_agent, message.text, history)
        SESSIONS[chat_id] = agent.trim_history(history)
        await message.answer(answer)
    except Exception as e:
        logging.exception("Ошибка агента")
        await message.answer(f"⚠️ Ошибка: {e}")


async def main():
    bot = Bot(token=config.TELEGRAM_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    logging.info("Бот запущен (polling).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


# --- Продакшн: webhook вместо polling ---------------------------------------
# Polling удобен для разработки. На сервере с публичным доменом лучше webhook:
# Telegram сам присылает апдейты на ваш HTTPS-эндпоинт — меньше задержка и
# нагрузка. См. aiogram + aiohttp:
# https://docs.aiogram.dev/en/latest/dispatcher/webhook.html
