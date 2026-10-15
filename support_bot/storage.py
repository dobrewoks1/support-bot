"""Журнал диалогов в SQLite и расчёт метрик.

Для каждого обращения сохраняется: кто спросил, что спросил, что ответил бот,
какая статья базы знаний подошла, статус (закрыто ботом / передано оператору /
отвечено оператором) и ответ оператора, если он был.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

STATUS_CLOSED = "closed_by_bot"
STATUS_ESCALATED = "escalated"
STATUS_OPERATOR = "answered_by_operator"

STATUS_LABELS = {
    STATUS_CLOSED: "закрыто ботом",
    STATUS_ESCALATED: "передано оператору",
    STATUS_OPERATOR: "отвечено оператором",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dialogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    username TEXT,
    question TEXT NOT NULL,
    answer TEXT,
    status TEXT NOT NULL,
    matched_entry TEXT,
    score REAL,
    provider TEXT,
    operator_answer TEXT,
    answered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dialogs_status ON dialogs(status);
"""


@dataclass(frozen=True)
class Dialog:
    """Строка журнала."""

    id: int
    created_at: str
    user_id: int
    chat_id: int
    username: str | None
    question: str
    answer: str | None
    status: str
    matched_entry: str | None
    score: float | None
    provider: str | None
    operator_answer: str | None
    answered_at: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    """Обёртка над SQLite. Потокобезопасна за счёт блокировки на запись."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # Для ":memory:" держим одно соединение, иначе база исчезнет между вызовами.
        self._memory_conn = (
            sqlite3.connect(":memory:", check_same_thread=False) if self.db_path == ":memory:" else None
        )
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._memory_conn or sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                if conn is not self._memory_conn:
                    conn.close()

    def log(
        self,
        *,
        user_id: int,
        chat_id: int,
        username: str | None,
        question: str,
        answer: str | None,
        status: str,
        matched_entry: str | None = None,
        score: float | None = None,
        provider: str | None = None,
    ) -> int:
        """Записать обращение и вернуть его номер (он же номер тикета для оператора)."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO dialogs (created_at, user_id, chat_id, username, question, answer,
                                        status, matched_entry, score, provider)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_now(), user_id, chat_id, username, question, answer, status, matched_entry, score, provider),
            )
            return int(cur.lastrowid)

    def set_operator_answer(self, dialog_id: int, text: str) -> Dialog | None:
        """Сохранить ответ оператора и перевести обращение в статус «отвечено оператором»."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE dialogs SET operator_answer = ?, answered_at = ?, status = ? WHERE id = ?",
                (text, _now(), STATUS_OPERATOR, dialog_id),
            )
        return self.get(dialog_id)

    def get(self, dialog_id: int) -> Dialog | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM dialogs WHERE id = ?", (dialog_id,)).fetchone()
        return Dialog(**dict(row)) if row else None

    def recent(self, limit: int = 20) -> list[Dialog]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM dialogs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [Dialog(**dict(r)) for r in rows]

    def stats(self, top_n: int = 5) -> dict[str, Any]:
        """Сводные метрики: всего обращений, по статусам, топ вопросов."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM dialogs").fetchone()[0]
            by_status = {
                row["status"]: row["n"]
                for row in conn.execute("SELECT status, COUNT(*) AS n FROM dialogs GROUP BY status")
            }
            top = conn.execute(
                """SELECT COALESCE(matched_entry, question) AS topic, COUNT(*) AS n
                   FROM dialogs GROUP BY topic ORDER BY n DESC, topic LIMIT ?""",
                (top_n,),
            ).fetchall()
            escalated_topics = conn.execute(
                """SELECT question AS topic, COUNT(*) AS n FROM dialogs
                   WHERE status IN (?, ?) GROUP BY topic ORDER BY n DESC, topic LIMIT ?""",
                (STATUS_ESCALATED, STATUS_OPERATOR, top_n),
            ).fetchall()
        closed = by_status.get(STATUS_CLOSED, 0)
        escalated = by_status.get(STATUS_ESCALATED, 0) + by_status.get(STATUS_OPERATOR, 0)
        return {
            "total": total,
            "closed_by_bot": closed,
            "escalated": escalated,
            "answered_by_operator": by_status.get(STATUS_OPERATOR, 0),
            "bot_share": round(closed / total, 3) if total else 0.0,
            "top_questions": [{"topic": r["topic"], "count": r["n"]} for r in top],
            "top_escalated": [{"topic": r["topic"], "count": r["n"]} for r in escalated_topics],
        }
