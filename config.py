"""
Конфигурация из переменных окружения (.env).
"""
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Модель агента. sonnet — оптимум цена/качество для такой задачи.
# Для более сложных рассуждений можно claude-opus-4-8, для удешевления — haiku.
MODEL = os.getenv("MODEL", "claude-sonnet-4-6")

# Доступы к Яндекс.Директу (понадобятся при реальной интеграции)
YANDEX_DIRECT_TOKEN = os.getenv("YANDEX_DIRECT_TOKEN", "")


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "да"}


# --- Кэш метрик в SQLite (Приоритет 2 из SPEC.md) ---------------------------
# По умолчанию ВЫКЛЮЧЕН: бот работает напрямую через провайдера (мок),
# чтобы не ломать запуск «из коробки». Включите USE_CACHE=true, чтобы
# инструменты читали из локальной базы, а бот регулярно её синхронизировал.
USE_CACHE = _as_bool(os.getenv("USE_CACHE", "false"))

# Путь к файлу базы (в .gitignore). Можно вынести на отдельный диск/том.
DB_PATH = os.getenv("DB_PATH", "metrics.sqlite3")

# Сколько дней истории держать в кэше и тянуть при синхронизации.
SYNC_DAYS = int(os.getenv("SYNC_DAYS", "30"))

# Период фоновой синхронизации в минутах (используется ботом).
SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))
