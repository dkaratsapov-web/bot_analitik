"""
Смоук-тест инструментов БЕЗ LLM и БЕЗ сети.

Прогоняй после правок в data.py / tools.py:

    python smoke_test.py

Опирается только на стандартную библиотеку (через data.py/tools.py).
Если какой-то инструмент падает или возвращает {"error": ...} там, где
ошибки быть не должно, — тест завершится с ненулевым кодом возврата.
"""

from __future__ import annotations

import json

import data
import tools


def _call(name: str, args: dict) -> dict:
    """Вызвать инструмент через реестр и напечатать результат."""
    result = tools.run_tool(name, args)
    print(f"\n### {name}({json.dumps(args, ensure_ascii=False)})")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    project = data.PROJECTS[0]
    failures: list[str] = []

    checks = [
        ("list_projects", {}),
        ("get_metrics", {"project": project, "days": 14}),
        ("compare_periods", {"project": project, "metric": "cpa", "days": 7}),
        ("top_projects", {"metric": "cost", "days": 7, "limit": 3}),
        ("find_anomalies", {"project": project, "metric": "cpa", "days": 14}),
        ("expand_keywords", {"seeds": ["кухни на заказ", "ремонт квартир"]}),
        ("validate_ad", {
            "title": "Кухни на заказ в Москве",
            "title2": "Срок 14 дней",
            "text": "Замер бесплатно. Гарантия 5 лет. Рассрочка 0%.",
        }),
    ]

    for name, args in checks:
        result = _call(name, args)
        if not isinstance(result, dict):
            failures.append(f"{name}: вернул не dict ({type(result).__name__})")
        elif "error" in result:
            failures.append(f"{name}: {result['error']}")

    print("\n" + "=" * 60)
    if failures:
        print("СМОУК-ТЕСТ ПРОВАЛЕН:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("СМОУК-ТЕСТ ПРОЙДЕН: все инструменты отработали без ошибок.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
