"""SQLite-backed task and step history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import StepRecord, StepStatus, TaskRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskContext:
    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                objective TEXT NOT NULL,
                repository TEXT NOT NULL,
                status TEXT NOT NULL,
                report TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS steps (
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                payload TEXT NOT NULL DEFAULT '{}',
                started_at TEXT,
                finished_at TEXT,
                PRIMARY KEY (task_id, name)
            );
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> TaskContext:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create_task(self, task_id: str, objective: str, repository: str) -> TaskRecord:
        now = _now()
        self._connection.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, objective, repository, StepStatus.PENDING.value, None, now, now),
        )
        self._connection.commit()
        return self.get_task(task_id)

    def set_task_status(self, task_id: str, status: StepStatus, report: str | None = None) -> None:
        cursor = self._connection.execute(
            "UPDATE tasks SET status = ?, report = COALESCE(?, report), updated_at = ? WHERE task_id = ?",
            (status.value, report, _now(), task_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Unknown task: {task_id}")
        self._connection.commit()

    def record_step(
        self,
        task_id: str,
        name: str,
        status: StepStatus,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> StepRecord:
        now = _now()
        previous = self._connection.execute(
            "SELECT started_at FROM steps WHERE task_id = ? AND name = ?", (task_id, name)
        ).fetchone()
        started = previous["started_at"] if previous and previous["started_at"] else now
        finished = now if status in (StepStatus.SUCCEEDED, StepStatus.FAILED) else None
        self._connection.execute(
            """INSERT INTO steps(task_id,name,status,reason,payload,started_at,finished_at)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(task_id,name) DO UPDATE SET
               status=excluded.status, reason=excluded.reason, payload=excluded.payload,
               started_at=excluded.started_at, finished_at=excluded.finished_at""",
            (task_id, name, status.value, reason, json.dumps(payload or {}), started, finished),
        )
        self._connection.commit()
        return self.get_step(task_id, name)

    def get_task(self, task_id: str) -> TaskRecord:
        row = self._connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown task: {task_id}")
        return TaskRecord(
            task_id=row["task_id"], objective=row["objective"], repository=row["repository"],
            status=StepStatus(row["status"]), report=row["report"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def get_step(self, task_id: str, name: str) -> StepRecord:
        row = self._connection.execute(
            "SELECT * FROM steps WHERE task_id = ? AND name = ?", (task_id, name)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown step: {task_id}/{name}")
        return StepRecord(
            task_id=row["task_id"], name=row["name"], status=StepStatus(row["status"]),
            reason=row["reason"], payload=json.loads(row["payload"]),
            started_at=row["started_at"], finished_at=row["finished_at"],
        )

    def get_steps(self, task_id: str) -> list[StepRecord]:
        names = self._connection.execute(
            "SELECT name FROM steps WHERE task_id = ? ORDER BY rowid", (task_id,)
        ).fetchall()
        return [self.get_step(task_id, row["name"]) for row in names]
