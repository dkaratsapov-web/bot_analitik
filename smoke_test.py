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
import os
import tempfile

import alerts
import data
import storage
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

    # Кэш-слой (SQLite): round-trip без сети, на временной базе.
    failures.extend(_check_cache(project))

    # Алерты по аномалиям + подписки: без сети, на временной базе.
    failures.extend(_check_alerts(project))

    print("\n" + "=" * 60)
    if failures:
        print("СМОУК-ТЕСТ ПРОВАЛЕН:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("СМОУК-ТЕСТ ПРОЙДЕН: все инструменты отработали без ошибок.")
    return 0


def _check_cache(project: str) -> list[str]:
    """Проверить SQLite-хранилище и CachedProvider без сети.

    Используем временный файл базы, чтобы не трогать рабочую metrics.sqlite3
    и не оставлять мусора. Базовый провайдер — MockProvider (детерминирован)."""
    problems: list[str] = []
    fd, path = tempfile.mkstemp(prefix="smoke_metrics_", suffix=".sqlite3")
    os.close(fd)
    try:
        cached = data.CachedProvider(data.MockProvider(), path, sync_days=30)

        # 1) Холодный кэш: get_rows должен лениво синхронизироваться и вернуть данные.
        rows = cached.get_rows(project, days=14)
        print(f"\n### CachedProvider.get_rows({project}, 14) -> {len(rows)} строк (cold)")
        if len(rows) != 14:
            problems.append(f"cache: ожидал 14 строк после промаха, получил {len(rows)}")
        if rows and not all("cpa" in r for r in rows):
            problems.append("cache: производные метрики (cpa) не посчитаны")

        # 2) Явный sync по всем проектам наполняет базу.
        written = cached.sync()
        print(f"### CachedProvider.sync() -> обновлено {written} строк")
        if written <= 0:
            problems.append("cache: sync() не записал ни одной строки")

        # 3) Прямое чтение из storage возвращает «сырые» строки.
        with storage.open_db(path) as conn:
            raw = storage.get_raw_rows(conn, project, 7)
            cnt = storage.count_rows(conn, project)
        print(f"### storage.get_raw_rows({project}, 7) -> {len(raw)} строк; всего {cnt}")
        if len(raw) != 7:
            problems.append(f"storage: ожидал 7 сырых строк, получил {len(raw)}")
        if raw and set(raw[0]) != set(storage.RAW_FIELDS):
            problems.append("storage: набор полей сырой строки не совпал с RAW_FIELDS")
    except Exception as e:  # noqa: BLE001 — смоук-тест должен поймать любую поломку
        problems.append(f"cache: исключение — {e!r}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return problems


def _check_alerts(project: str) -> list[str]:
    """Проверить логику алертов и хранилище подписок без сети."""
    problems: list[str] = []
    provider = data.MockProvider()

    # 1) scan возвращает список (на моке аномалий может и не быть — это норма).
    found = alerts.scan(provider, z=2.0)
    print(f"\n### alerts.scan(z=2.0) -> {len(found)} аномалий")
    if not isinstance(found, list):
        problems.append(f"alerts: scan вернул не list ({type(found).__name__})")

    # 2) format_report: пусто при пустом входе, текст — при синтетическом алерте.
    if alerts.format_report([]) != "":
        problems.append("alerts: format_report([]) должен быть пустой строкой")
    synthetic = [{
        "project": project, "metric": "cost", "date": "2026-06-29",
        "value": 99999.0, "mean": 50000.0, "z": 3.4,
        "title": "Расход подскочил", "unit": "₽",
    }]
    report = alerts.format_report(synthetic)
    print("### alerts.format_report(synthetic):")
    print(report)
    if project not in report or "Расход подскочил" not in report:
        problems.append("alerts: отчёт не содержит ожидаемого текста")

    # 3) Подписки: add / list / is_subscribed / remove на временной базе.
    fd, path = tempfile.mkstemp(prefix="smoke_subs_", suffix=".sqlite3")
    os.close(fd)
    try:
        with storage.open_db(path) as conn:
            added = storage.add_subscriber(conn, 12345, "2026-06-29T09:00:00")
            again = storage.add_subscriber(conn, 12345, "2026-06-29T09:00:00")
            subs = storage.list_subscribers(conn)
            subscribed = storage.is_subscribed(conn, 12345)
            removed = storage.remove_subscriber(conn, 12345)
            empty = storage.list_subscribers(conn)
        print(f"### subs: added={added} again={again} list={subs} "
              f"is_sub={subscribed} removed={removed} after={empty}")
        if not (added and not again and subs == [12345] and subscribed
                and removed and empty == []):
            problems.append("alerts: жизненный цикл подписки отработал неверно")
    except Exception as e:  # noqa: BLE001
        problems.append(f"alerts: исключение в подписках — {e!r}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
