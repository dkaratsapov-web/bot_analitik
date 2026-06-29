"""
Проактивные алерты по аномалиям (Приоритет 3 из SPEC.md).

Бот сам, по расписанию, сканирует проекты и сообщает о подозрительных
изменениях за последний день: всплеск расхода, просадка конверсий, рост
CPA. Здесь — только логика обнаружения и форматирования: чистые функции
без сети и без aiogram, чтобы их можно было прогонять в smoke_test.

Переиспользует детектор аномалий из data.zscore_anomalies.
"""

from __future__ import annotations

import data

# Какие метрики и в какую сторону считаем тревожными для «последнего дня».
# (метрика, тревожное направление из zscore_anomalies, заголовок, единица)
_RULES = [
    ("cost", "выше нормы", "Расход подскочил", "₽"),
    ("conversions", "ниже нормы", "Просадка конверсий", ""),
    ("cpa", "выше нормы", "CPA вырос", "₽"),
]


def _fmt(value, unit: str) -> str:
    """Человекочитаемое значение метрики с единицей."""
    if isinstance(value, float):
        value = round(value, 2)
    return f"{value} {unit}".strip()


def scan(provider, projects=None, days: int = 14, z: float = 2.0) -> list[dict]:
    """Найти аномалии за ПОСЛЕДНИЙ день по всем (или заданным) проектам.

    Возвращает список словарей-алертов. Пустой список — всё спокойно.
    Не делает сетевых вызовов сам по себе: всё через переданный provider.
    """
    projects = projects or provider.list_projects()
    alerts: list[dict] = []
    for p in projects:
        rows = provider.get_rows(p, days)
        if len(rows) < 5:  # слишком мало данных для статистики
            continue
        latest = rows[-1]["date"]
        for metric, bad_direction, title, unit in _RULES:
            for f in data.zscore_anomalies(rows, metric, threshold=z):
                if f["date"] == latest and f["direction"] == bad_direction:
                    alerts.append({
                        "project": p,
                        "metric": metric,
                        "date": latest,
                        "value": f["value"],
                        "mean": f["mean"],
                        "z": f["z"],
                        "title": title,
                        "unit": unit,
                    })
    return alerts


def format_report(alerts: list[dict]) -> str:
    """Собрать текст уведомления для Telegram. Пусто — если алертов нет."""
    if not alerts:
        return ""
    lines = ["🔔 Аномалии за последний день:"]
    # сгруппировать по проекту для читаемости
    by_project: dict[str, list[dict]] = {}
    for a in alerts:
        by_project.setdefault(a["project"], []).append(a)
    for project, items in by_project.items():
        lines.append(f"\n📁 {project} ({items[0]['date']}):")
        for a in items:
            lines.append(
                f"  • {a['title']}: {a['metric']} = {_fmt(a['value'], a['unit'])} "
                f"(норма ~{_fmt(a['mean'], a['unit'])}, z={a['z']})"
            )
    lines.append("\nСпросите детали — разберу причину и дам рекомендации.")
    return "\n".join(lines)


def build_report(provider, **kwargs) -> str:
    """Удобная обёртка: просканировать и сразу отформатировать."""
    return format_report(scan(provider, **kwargs))
