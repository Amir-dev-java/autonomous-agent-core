"""Shared data contracts for the workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskRequest:
    objective: str
    repository: str
    task_id: str = ""


@dataclass(frozen=True)
class Plan:
    summary: str
    steps: tuple[str, ...]
    test_profile: str
    expected_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileEdit:
    path: str
    old_text: str
    new_text: str


@dataclass(frozen=True)
class Implementation:
    edits: tuple[FileEdit, ...] = ()
    explanation: str = ""


@dataclass(frozen=True)
class TestResult:
    passed: bool
    returncode: int
    stdout: str
    stderr: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class Review:
    approved: bool
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    objective: str
    repository: str
    status: StepStatus
    report: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StepRecord:
    task_id: str
    name: str
    status: StepStatus
    reason: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None


def to_json_dict(value: Any) -> dict[str, Any]:
    """Convert a dataclass contract into a JSON-compatible mapping."""
    return asdict(value)
