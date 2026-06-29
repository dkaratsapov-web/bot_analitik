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
from datetime import datetime

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
    "/reset — очистить контекст диалога.\n"
    "/alerts_on, /alerts_off — ежедневные уведомления об аномалиях."
)


@router.message(Command("start"))
async def cmd_start(message: Message):
    SESSIONS[message.chat.id] = []
    await message.answer(WELCOME, parse_mode="Markdown")


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    SESSIONS[message.chat.id] = []
    await message.answer("Контекст очищен.")


@router.message(Command("alerts_on"))
async def cmd_alerts_on(message: Message):
    import storage

    now = datetime.now().isoformat(timespec="seconds")
    with storage.open_db(config.DB_PATH) as conn:
        is_new = storage.add_subscriber(conn, message.chat.id, now)
    if not config.ALERTS_ENABLED:
        await message.answer(
            "Подписка сохранена, но ежедневные алерты сейчас выключены "
            "(ALERTS_ENABLED=false). Включите их в настройках бота."
        )
        return
    await message.answer(
        "✅ Подписал на ежедневные алерты по аномалиям."
        if is_new else "Вы уже подписаны на алерты."
    )


@router.message(Command("alerts_off"))
async def cmd_alerts_off(message: Message):
    import storage

    with storage.open_db(config.DB_PATH) as conn:
        existed = storage.remove_subscriber(conn, message.chat.id)
    await message.answer(
        "🔕 Отписал от алертов." if existed else "Вы и так не были подписаны."
    )


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


async def _alerts_job(bot: Bot) -> None:
    """Ежедневная сводка аномалий → всем подписанным чатам."""
    import alerts
    import data
    import storage

    try:
        provider = data.get_provider()
        # scan может ходить в сеть у реального провайдера — уводим в поток
        report = await asyncio.to_thread(
            alerts.build_report, provider, z=config.ALERT_ZSCORE
        )
        if not report:
            logging.info("Алерты: аномалий не найдено, рассылку пропускаю.")
            return
        with storage.open_db(config.DB_PATH) as conn:
            subscribers = storage.list_subscribers(conn)
        for chat_id in subscribers:
            try:
                await bot.send_message(chat_id, report)
            except Exception:
                logging.exception("Не смог отправить алерт в чат %s", chat_id)
    except Exception:
        logging.exception("Ошибка задачи алертов")


def _start_scheduler(bot: Bot) -> "object | None":
    """Запустить фоновые задачи: синхронизацию кэша (USE_CACHE) и ежедневные
    алерты (ALERTS_ENABLED). APScheduler — тяжёлая зависимость, поэтому
    импортируется лениво и только когда хоть одна задача включена."""
    if not (config.USE_CACHE or config.ALERTS_ENABLED):
        return None

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()

    if config.USE_CACHE:
        import data

        provider = data.get_provider()
        sync = getattr(provider, "sync", None)
        if sync is None:
            logging.warning("USE_CACHE=true, но провайдер без sync() — пропускаю синк.")
        else:
            def sync_job():
                try:
                    written = sync()
                    logging.info("Синхронизация кэша: обновлено строк — %s", written)
                except Exception:
                    logging.exception("Ошибка фоновой синхронизации кэша")

            sync_job()  # первичная синхронизация, чтобы база не была пустой
            scheduler.add_job(sync_job, "interval", minutes=config.SYNC_INTERVAL_MINUTES)
            logging.info(
                "Синхронизация кэша: каждые %s мин.", config.SYNC_INTERVAL_MINUTES
            )

    if config.ALERTS_ENABLED:
        scheduler.add_job(
            _alerts_job, "cron", hour=config.ALERTS_HOUR, minute=0, args=[bot]
        )
        logging.info("Ежедневные алерты: в %02d:00.", config.ALERTS_HOUR)

    scheduler.start()
    return scheduler


async def main():
    bot = Bot(token=config.TELEGRAM_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    _start_scheduler(bot)
    logging.info("Бот запущен (polling).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


# --- Продакшн: webhook вместо polling ---------------------------------------
# Polling удобен для разработки. На сервере с публичным доменом лучше webhook:
# Telegram сам присылает апдейты на ваш HTTPS-эндпоинт — меньше задержка и
# нагрузка. См. aiogram + aiohttp:
# https://docs.aiogram.dev/en/latest/dispatcher/webhook.html
