"""
Инструменты (tools), которые агент может вызывать.

Здесь две группы:
  1) АНАЛИТИКА — отвечает на вопросы по статистике кампаний.
  2) СПЕЦИАЛИСТ ПО ДИРЕКТУ — семантика и проверка объявлений.

Архитектурный смысл: оба бота, которые вы хотели («аналитик» и
«специалист по Директу»), — это просто РАЗНЫЕ НАБОРЫ ИНСТРУМЕНТОВ у
одного и того же агента. Хотите два отдельных бота — просто отдавайте
агенту разные подмножества TOOLS (см. agent.py).

Каждый инструмент = (1) JSON-схема для модели + (2) обычная Python-функция.
"""

from __future__ import annotations

import data

# ============================================================================
# ГРУППА 1. АНАЛИТИКА
# ============================================================================

def tool_list_projects() -> dict:
    return {"projects": data.get_provider().list_projects()}


def tool_get_metrics(project: str, days: int = 14) -> dict:
    rows = data.get_provider().get_rows(project, days)
    if not rows:
        return {"error": f"Проект '{project}' не найден"}
    return {"project": project, "period_days": days, "totals": data.aggregate(rows)}


def tool_compare_periods(project: str, metric: str, days: int = 7) -> dict:
    """Сравнить текущий период с предыдущим такой же длины."""
    rows = data.get_provider().get_rows(project, days * 2)
    if not rows:
        return {"error": f"Проект '{project}' не найден"}
    prev, cur = rows[:days], rows[days:]
    a = data.aggregate(prev).get(metric)
    b = data.aggregate(cur).get(metric)
    if a is None or b is None:
        return {"error": f"Неизвестная метрика '{metric}'"}
    change = round((b - a) / a * 100, 1) if a else None
    return {
        "project": project, "metric": metric,
        "previous": a, "current": b,
        "change_pct": change,
    }


def tool_top_projects(metric: str = "cost", days: int = 7, limit: int = 5) -> dict:
    """Рейтинг проектов по метрике (например, самые дорогие по расходу)."""
    prov = data.get_provider()
    scored = []
    for p in prov.list_projects():
        agg = data.aggregate(prov.get_rows(p, days))
        if metric in agg:
            scored.append({"project": p, metric: agg[metric]})
    scored.sort(key=lambda x: x[metric], reverse=True)
    return {"metric": metric, "ranking": scored[:limit]}


def tool_find_anomalies(project: str, metric: str = "cpa", days: int = 14) -> dict:
    """Найти дни с аномальными значениями метрики."""
    rows = data.get_provider().get_rows(project, days)
    if not rows:
        return {"error": f"Проект '{project}' не найден"}
    flags = data.zscore_anomalies(rows, metric)
    return {"project": project, "metric": metric, "anomalies": flags or "не найдено"}


# ============================================================================
# ГРУППА 2. СПЕЦИАЛИСТ ПО ДИРЕКТУ
# ============================================================================

# Лимиты символов в Яндекс.Директе (актуальные на момент написания)
DIRECT_LIMITS = {
    "title": 56,        # Заголовок 1
    "title2": 30,       # Заголовок 2
    "text": 81,         # Текст объявления
    "sitelink": 30,     # Быстрая ссылка
    "display_path": 20, # Отображаемая ссылка
}

# Базовые коммерческие модификаторы для расширения семантики
_INTENT_MODS = ["купить", "цена", "стоимость", "заказать", "недорого",
                "отзывы", "официальный", "с доставкой", "рядом", "онлайн"]
# Слова, по которым обычно собирают минус-слова (нецелевой трафик)
_NEGATIVE_HINTS = ["бесплатно", "своими руками", "скачать", "вакансии",
                   "б у", "реферат", "википедия"]


def tool_expand_keywords(seeds: list[str]) -> dict:
    """Расширить список ключевых фраз коммерческими модификаторами
    и предложить минус-слова. Это базовая офлайн-версия; позже можно
    подключить Wordstat для реальной частотности."""
    expanded = []
    for s in seeds:
        s = s.strip().lower()
        if not s:
            continue
        expanded.append(s)
        for m in _INTENT_MODS:
            expanded.append(f"{s} {m}")
    # убрать дубли, сохранив порядок
    seen, unique = set(), []
    for kw in expanded:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return {
        "keywords": unique,
        "suggested_negatives": _NEGATIVE_HINTS,
        "note": "Для реальной частотности подключите Wordstat API Директа.",
    }


def tool_validate_ad(title: str, title2: str = "", text: str = "") -> dict:
    """Проверить объявление на соответствие лимитам Директа."""
    checks = {
        "title": (title, DIRECT_LIMITS["title"]),
        "title2": (title2, DIRECT_LIMITS["title2"]),
        "text": (text, DIRECT_LIMITS["text"]),
    }
    result, ok = {}, True
    for field, (value, limit) in checks.items():
        length = len(value)
        passed = length <= limit
        ok = ok and passed
        result[field] = {"length": length, "limit": limit, "ok": passed}
    return {"valid": ok, "fields": result}


# ============================================================================
# РЕЕСТР: связываем имена инструментов с функциями и JSON-схемами
# ============================================================================

DISPATCH = {
    "list_projects": tool_list_projects,
    "get_metrics": tool_get_metrics,
    "compare_periods": tool_compare_periods,
    "top_projects": tool_top_projects,
    "find_anomalies": tool_find_anomalies,
    "expand_keywords": tool_expand_keywords,
    "validate_ad": tool_validate_ad,
}

# Схемы в формате Anthropic tool use
TOOL_SCHEMAS = [
    {
        "name": "list_projects",
        "description": "Вернуть список всех проектов (рекламных аккаунтов).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_metrics",
        "description": "Суммарные метрики проекта за N дней: показы, клики, расход, "
                       "конверсии, CTR, CPC, CPA, CR.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "days": {"type": "integer", "default": 14},
            },
            "required": ["project"],
        },
    },
    {
        "name": "compare_periods",
        "description": "Сравнить метрику текущего периода с предыдущим такой же длины "
                       "(динамика в %). Метрики: impressions, clicks, cost, conversions, "
                       "ctr, cpc, cpa, cr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "metric": {"type": "string"},
                "days": {"type": "integer", "default": 7},
            },
            "required": ["project", "metric"],
        },
    },
    {
        "name": "top_projects",
        "description": "Рейтинг проектов по метрике (например, топ по расходу cost).",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "default": "cost"},
                "days": {"type": "integer", "default": 7},
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "find_anomalies",
        "description": "Найти дни с аномальными значениями метрики (всплески/просадки).",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "metric": {"type": "string", "default": "cpa"},
                "days": {"type": "integer", "default": 14},
            },
            "required": ["project"],
        },
    },
    {
        "name": "expand_keywords",
        "description": "Расширить ключевые фразы коммерческими модификаторами и "
                       "предложить минус-слова. Для семантики в Директе.",
        "input_schema": {
            "type": "object",
            "properties": {
                "seeds": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["seeds"],
        },
    },
    {
        "name": "validate_ad",
        "description": "Проверить заголовки и текст объявления на лимиты символов Директа.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "title2": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["title"],
        },
    },
]


def run_tool(name: str, args: dict) -> dict:
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"Неизвестный инструмент: {name}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"Неверные аргументы для {name}: {e}"}
