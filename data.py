"""
Слой данных.

Сейчас работает на МОК-данных, чтобы бота можно было запустить сразу,
без доступов к API. Когда получите токен Яндекс.Директа — реализуйте
методы YandexDirectClient (см. ссылки на эндпоинты внизу файла),
и поменяйте get_provider() так, чтобы он возвращал реальный клиент.

Намеренно использует только стандартную библиотеку Python — никаких
pandas/numpy, чтобы проект запускался без установки тяжёлых зависимостей.
Для больших объёмов данных позже имеет смысл перейти на pandas + PostgreSQL.
"""

from __future__ import annotations

import random
import statistics
from datetime import date, timedelta
from typing import Optional

# --- Список ваших проектов (замените на свои) -------------------------------
PROJECTS = [
    "shop-mebel", "clinic-stoma", "autoservice", "fitness-club", "law-firm",
    "online-school", "delivery-food", "beauty-salon", "b2b-saas", "travel-agency",
]


# --- Генератор реалистичных мок-метрик ---------------------------------------
def _seeded_rows(project: str, days: int) -> list[dict]:
    """Детерминированные «дневные» строки метрик для проекта."""
    rng = random.Random(hash(project) & 0xFFFF)  # стабильный сид на проект
    base_imp = rng.randint(3000, 25000)
    base_ctr = rng.uniform(0.03, 0.12)
    base_cpc = rng.uniform(8, 45)        # рубли
    base_cr = rng.uniform(0.02, 0.10)    # конверсия из клика в лид

    rows = []
    today = date.today()
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        # дневные колебания + лёгкий тренд
        wobble = rng.uniform(0.8, 1.2)
        imp = int(base_imp * wobble)
        ctr = max(0.005, base_ctr * rng.uniform(0.85, 1.15))
        clicks = int(imp * ctr)
        cpc = base_cpc * rng.uniform(0.9, 1.1)
        cost = round(clicks * cpc, 2)
        conv = int(clicks * base_cr * rng.uniform(0.7, 1.3))
        rows.append({
            "date": d.isoformat(),
            "impressions": imp,
            "clicks": clicks,
            "cost": cost,
            "conversions": conv,
        })
    return rows


def _with_derived(rows: list[dict]) -> list[dict]:
    """Добавляет производные метрики: CTR, CPC, CPA, CR."""
    out = []
    for r in rows:
        clicks = r["clicks"] or 0
        imp = r["impressions"] or 0
        conv = r["conversions"] or 0
        cost = r["cost"] or 0.0
        out.append({
            **r,
            "ctr": round(clicks / imp, 4) if imp else 0.0,
            "cpc": round(cost / clicks, 2) if clicks else 0.0,
            "cpa": round(cost / conv, 2) if conv else 0.0,
            "cr": round(conv / clicks, 4) if clicks else 0.0,
        })
    return out


class MockProvider:
    """Источник данных-заглушка. Полностью повторяет интерфейс,
    который потом реализует реальный YandexDirectClient."""

    def list_projects(self) -> list[str]:
        return PROJECTS

    def get_rows(self, project: str, days: int = 14) -> list[dict]:
        if project not in PROJECTS:
            return []
        return _with_derived(_seeded_rows(project, days))


class YandexDirectClient:
    """РЕАЛЬНЫЙ клиент Яндекс.Директа. Сейчас не реализован — заглушка.

    Когда дойдут руки до интеграции:
      1. Получите OAuth-токен и доступ к API Директа.
      2. Реализуйте get_rows() через Reports API (TSV-отчёт).
      3. В get_provider() верните YandexDirectClient вместо MockProvider.

    Документация:
      - Reports API:   https://yandex.ru/dev/direct/doc/reports/reports.html
      - OAuth:         https://yandex.ru/dev/direct/doc/dg/concepts/auth-token.html
      - Wordstat (для семантики во втором боте):
                       https://yandex.ru/dev/direct/doc/dg/objects/keywordsresearch.html
    """

    def __init__(self, oauth_token: str, client_login: Optional[str] = None):
        self.token = oauth_token
        self.client_login = client_login
        # TODO: import requests; завести базовый URL и заголовки

    def list_projects(self) -> list[str]:
        raise NotImplementedError("Реализуйте через список кампаний Директа")

    def get_rows(self, project: str, days: int = 14) -> list[dict]:
        raise NotImplementedError("Реализуйте через Reports API Директа")


def get_provider():
    """Единая точка получения источника данных.
    Поменяйте здесь на YandexDirectClient(token), когда будет токен."""
    return MockProvider()


# --- Утилиты агрегации (используются инструментами агента) -------------------
def aggregate(rows: list[dict]) -> dict:
    """Свернуть набор дневных строк в суммарные метрики за период."""
    if not rows:
        return {}
    imp = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    cost = round(sum(r["cost"] for r in rows), 2)
    conv = sum(r["conversions"] for r in rows)
    return {
        "impressions": imp,
        "clicks": clicks,
        "cost": cost,
        "conversions": conv,
        "ctr": round(clicks / imp, 4) if imp else 0.0,
        "cpc": round(cost / clicks, 2) if clicks else 0.0,
        "cpa": round(cost / conv, 2) if conv else 0.0,
        "cr": round(conv / clicks, 4) if clicks else 0.0,
    }


def zscore_anomalies(rows: list[dict], metric: str, threshold: float = 2.0) -> list[dict]:
    """Простая детекция аномалий по z-оценке для одной метрики."""
    vals = [r[metric] for r in rows]
    if len(vals) < 4:
        return []
    mean = statistics.mean(vals)
    stdev = statistics.pstdev(vals)
    if stdev == 0:
        return []
    flagged = []
    for r in rows:
        z = (r[metric] - mean) / stdev
        if abs(z) >= threshold:
            flagged.append({
                "date": r["date"],
                "metric": metric,
                "value": r[metric],
                "mean": round(mean, 2),
                "z": round(z, 2),
                "direction": "выше нормы" if z > 0 else "ниже нормы",
            })
    return flagged
