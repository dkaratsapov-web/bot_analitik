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
