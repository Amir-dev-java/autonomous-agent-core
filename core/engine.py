"""Workflow state machine with persistent per-stage outcomes."""

from __future__ import annotations

import uuid
from pathlib import Path, PurePosixPath
from typing import Callable, TypeVar

from core.context import TaskContext
from core.models import Review, StepStatus, TaskRequest
from roles.contracts import Executor, Planner, Reviewer
from tools.git_tools import GitTools
from tools.runner import SafeRunner

T = TypeVar("T")


class WorkflowStageError(RuntimeError):
    pass


class WorkflowEngine:
    STAGES = ("planning", "worktree", "implementation", "tests", "review")

    def __init__(self, context: TaskContext, git: GitTools, runner: SafeRunner,
                 planner: Planner, executor: Executor, reviewer: Reviewer) -> None:
        self.context = context
        self.git = git
        self.runner = runner
        self.planner = planner
        self.executor = executor
        self.reviewer = reviewer

    def run(self, request: TaskRequest) -> dict[str, object]:
        task_id = request.task_id or uuid.uuid4().hex[:12]
        request = TaskRequest(request.objective, str(Path(request.repository).resolve()), task_id)
        self.context.create_task(task_id, request.objective, request.repository)
        paths: dict[str, str] = {}
        try:
            plan = self._stage(task_id, "planning", lambda: self.planner.plan(request),
                               lambda value: {"summary": value.summary, "steps": list(value.steps),
                                              "test_profile": value.test_profile})
            repository = Path(request.repository).resolve()
            worktree_path = self.git.workspace_root / task_id / "worktree"
            worktree = self._stage(
                task_id, "worktree",
                lambda: self.git.create_worktree(repository, worktree_path, f"agent/{task_id}"),
                lambda value: {"path": str(value), "branch": self.git.branch_name(value)},
            )
            paths["worktree"] = str(worktree)
            implementation = self._stage(
                task_id, "implementation",
                lambda: self._apply_implementation(request, plan, worktree),
                lambda value: {"explanation": value.explanation,
                               "files": [edit.path for edit in value.edits]},
            )
            test_result = self._stage(
                task_id, "tests", lambda: self.runner.run(plan.test_profile, worktree),
                lambda value: {"passed": value.passed, "returncode": value.returncode,
                               "stdout": value.stdout, "stderr": value.stderr,
                               "command": list(value.command)},
                success=lambda result: result.passed,
                failure_reason=lambda result: result.stderr or f"test process exited {result.returncode}",
            )
            review: Review = self._stage(
                task_id, "review",
                lambda: self._review(worktree, request, plan, implementation, test_result),
                lambda value: {"approved": value.approved, "findings": list(value.findings)},
                success=lambda result: result.approved,
                failure_reason=lambda result: "; ".join(result.findings) or "review rejected",
            )
            report = (
                f"Task {task_id}: succeeded\n"
                f"Branch: {self.git.branch_name(worktree)}\n"
                f"Tests: passed\n"
                f"Review: approved\n"
                f"Worktree: {worktree}"
            )
            self.context.set_task_status(task_id, StepStatus.SUCCEEDED, report)
            return {"task_id": task_id, "status": "succeeded", "report": report,
                    "branch": self.git.branch_name(worktree), "worktree": str(worktree)}
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.context.set_task_status(task_id, StepStatus.FAILED, reason)
            return {"task_id": task_id, "status": "failed", "report": reason, **paths}

    def _stage(self, task_id: str, name: str, operation: Callable[[], T],
               payload: Callable[[T], dict[str, object]],
               success: Callable[[T], bool] = lambda _value: True,
               failure_reason: Callable[[T], str] = lambda _value: "stage rejected") -> T:
        self.context.record_step(task_id, name, StepStatus.RUNNING)
        try:
            result = operation()
            result_payload = payload(result)
            if not success(result):
                reason = failure_reason(result)
                self.context.record_step(task_id, name, StepStatus.FAILED, reason, result_payload)
                raise WorkflowStageError(f"{name} failed: {reason}")
            self.context.record_step(task_id, name, StepStatus.SUCCEEDED, payload=result_payload)
            return result
        except WorkflowStageError:
            raise
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.context.record_step(task_id, name, StepStatus.FAILED, reason)
            raise WorkflowStageError(f"{name} failed: {reason}") from exc

    def _apply_implementation(self, request, plan, worktree):
        implementation = self.executor.implement(request, plan)
        expected = set(plan.expected_files)
        root = Path(worktree).resolve()
        for edit in implementation.edits:
            if len(edit.old_text.encode("utf-8")) > 1024 * 1024 or len(edit.new_text.encode("utf-8")) > 1024 * 1024:
                raise ValueError("An individual file edit may not exceed 1 MiB")
            relative = PurePosixPath(edit.path)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError(f"Unsafe edit path: {edit.path}")
            if expected and edit.path not in expected:
                raise ValueError(f"Edit is outside planner-approved files: {edit.path}")
            target = root.joinpath(*relative.parts).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"Edit escapes worktree: {edit.path}")
            if not target.is_file():
                raise ValueError(f"Edit target does not exist: {edit.path}")
            original = target.read_text(encoding="utf-8")
            matches = original.count(edit.old_text)
            if matches != 1:
                raise ValueError(f"Expected one exact match in {edit.path}; found {matches}")
            target.write_text(original.replace(edit.old_text, edit.new_text, 1), encoding="utf-8")
        if not implementation.edits:
            raise ValueError("Executor returned no file edits")
        return implementation

    def _review(self, worktree, request, plan, implementation, tests):
        diff = self.git.diff(worktree)
        if len(diff.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Git diff exceeds the 1 MiB review limit")
        return self.reviewer.review(request, plan, implementation, diff, tests)
