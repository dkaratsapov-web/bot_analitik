"""
Локальное хранилище метрик на SQLite.

Назначение: кэшировать дневные строки метрик, чтобы не дёргать API
источника (Яндекс.Директ) на каждый вопрос. Регулярная синхронизация
наполняет базу, а инструменты читают уже из неё.

Намеренно используется ТОЛЬКО стандартная библиотека (`sqlite3`) — без
тяжёлых зависимостей, как требует конвенция проекта. Модуль ничего не
импортирует из `data.py`/`tools.py`, чтобы не было циклических импортов:
хранит и отдаёт «сырые» строки (date, impressions, clicks, cost,
conversions), а производные метрики (CTR/CPC/CPA/CR) считает вызывающий
код.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Iterable, Optional

# Поля «сырой» дневной строки — ровно то, что отдаёт источник данных.
RAW_FIELDS = ("date", "impressions", "clicks", "cost", "conversions")


def connect(db_path: str) -> sqlite3.Connection:
    """Открыть соединение и убедиться, что схема создана."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metrics (
            project      TEXT    NOT NULL,
            date         TEXT    NOT NULL,
            impressions  INTEGER NOT NULL,
            clicks       INTEGER NOT NULL,
            cost         REAL    NOT NULL,
            conversions  INTEGER NOT NULL,
            PRIMARY KEY (project, date)
        )
        """
    )
    # Время последней успешной синхронизации по проекту (ISO-строка).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_meta (
            project    TEXT PRIMARY KEY,
            synced_at  TEXT NOT NULL
        )
        """
    )
    # Подписки чатов на проактивные алерты (Приоритет 3).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_subs (
            chat_id     INTEGER PRIMARY KEY,
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()


def upsert_rows(conn: sqlite3.Connection, project: str, rows: Iterable[dict]) -> int:
    """Вставить/обновить дневные строки проекта. Возвращает число строк."""
    payload = [
        (
            project,
            r["date"],
            int(r["impressions"]),
            int(r["clicks"]),
            float(r["cost"]),
            int(r["conversions"]),
        )
        for r in rows
    ]
    if not payload:
        return 0
    conn.executemany(
        """
        INSERT INTO metrics (project, date, impressions, clicks, cost, conversions)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(project, date) DO UPDATE SET
            impressions = excluded.impressions,
            clicks      = excluded.clicks,
            cost        = excluded.cost,
            conversions = excluded.conversions
        """,
        payload,
    )
    conn.commit()
    return len(payload)


def get_raw_rows(conn: sqlite3.Connection, project: str, days: int) -> list[dict]:
    """Последние `days` дневных строк проекта по возрастанию даты.

    Возвращает «сырые» строки без производных метрик (их считает
    вызывающий код — например, data._with_derived)."""
    cur = conn.execute(
        """
        SELECT date, impressions, clicks, cost, conversions
        FROM metrics
        WHERE project = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (project, days),
    )
    rows = [dict(r) for r in cur.fetchall()]
    rows.reverse()  # вернуть по возрастанию даты
    return rows


def count_rows(conn: sqlite3.Connection, project: str) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM metrics WHERE project = ?", (project,))
    return int(cur.fetchone()[0])


def mark_synced(conn: sqlite3.Connection, project: str, synced_at: str) -> None:
    conn.execute(
        """
        INSERT INTO sync_meta (project, synced_at) VALUES (?, ?)
        ON CONFLICT(project) DO UPDATE SET synced_at = excluded.synced_at
        """,
        (project, synced_at),
    )
    conn.commit()


def last_synced(conn: sqlite3.Connection, project: str) -> Optional[str]:
    cur = conn.execute("SELECT synced_at FROM sync_meta WHERE project = ?", (project,))
    row = cur.fetchone()
    return row[0] if row else None


def known_projects(conn: sqlite3.Connection) -> list[str]:
    """Проекты, по которым в базе есть хоть какие-то данные."""
    cur = conn.execute("SELECT DISTINCT project FROM metrics ORDER BY project")
    return [r[0] for r in cur.fetchall()]


# --- Подписки на проактивные алерты -----------------------------------------
def add_subscriber(conn: sqlite3.Connection, chat_id: int, created_at: str) -> bool:
    """Подписать чат на алерты. True — если подписка новая."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO alert_subs (chat_id, created_at) VALUES (?, ?)",
        (chat_id, created_at),
    )
    conn.commit()
    return cur.rowcount > 0


def remove_subscriber(conn: sqlite3.Connection, chat_id: int) -> bool:
    """Отписать чат. True — если подписка была."""
    cur = conn.execute("DELETE FROM alert_subs WHERE chat_id = ?", (chat_id,))
    conn.commit()
    return cur.rowcount > 0


def list_subscribers(conn: sqlite3.Connection) -> list[int]:
    cur = conn.execute("SELECT chat_id FROM alert_subs ORDER BY chat_id")
    return [int(r[0]) for r in cur.fetchall()]


def is_subscribed(conn: sqlite3.Connection, chat_id: int) -> bool:
    cur = conn.execute("SELECT 1 FROM alert_subs WHERE chat_id = ?", (chat_id,))
    return cur.fetchone() is not None


# Удобный контекст-менеджер для разовых операций.
def open_db(db_path: str):
    return closing(connect(db_path))
