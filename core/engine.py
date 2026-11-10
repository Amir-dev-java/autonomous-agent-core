"""Workflow state machine with persistent per-stage outcomes."""

from __future__ import annotations

import uuid
import re
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
    STAGES = ("repository", "planning", "worktree", "implementation", "staging",
              "tests", "review", "commit")

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
        source_repository = Path(request.repository).expanduser().resolve()
        request = TaskRequest(request.objective, str(source_repository), task_id)
        self.context.create_task(task_id, request.objective, str(source_repository))
        paths: dict[str, str] = {}
        try:
            source_isolated = source_repository.is_relative_to(self.git.workspace_root)
            repository = self._stage(
                task_id, "repository",
                lambda: source_repository if source_isolated else self.git.clone_local_repository(
                    source_repository, Path(task_id) / "repository"
                ),
                lambda value: {"path": str(value), "isolated_copy": not source_isolated},
            )
            request = TaskRequest(request.objective, str(repository), task_id)
            plan = self._stage(task_id, "planning", lambda: self.planner.plan(request),
                               lambda value: {"summary": value.summary, "steps": list(value.steps),
                                              "test_profile": value.test_profile})
            worktree_path = self.git.workspace_root / task_id / "worktree"
            worktree = self._stage(
                task_id, "worktree",
                lambda: self.git.create_worktree(repository, worktree_path, f"agent/{task_id}"),
                lambda value: {"path": str(value), "branch": self.git.branch_name(value)},
            )
            paths["worktree"] = str(worktree)
            implementation = self._stage(
                task_id, "implementation",
                lambda: self._implement_with_retry(request, plan, worktree),
                lambda value: {"explanation": value.explanation,
                               "files": [edit.path for edit in value.edits]},
            )
            self._stage(
                task_id, "staging",
                lambda: self.git.stage_paths(worktree, tuple(edit.path for edit in implementation.edits)),
                lambda _value: {"files": [edit.path for edit in implementation.edits]},
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
            commit = self._stage(
                task_id, "commit",
                lambda: self.git.commit_changes(
                    worktree, "agent: " + " ".join(request.objective.split())[:72]
                ),
                lambda value: {"commit": value},
            )
            report = (
                f"Task {task_id}: succeeded\n"
                f"Branch: {self.git.branch_name(worktree)}\n"
                f"Commit: {commit}\n"
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

    def _implement_with_retry(self, request, plan, worktree):
        feedback = ""
        for attempt in range(2):
            generation_request = TaskRequest(
                request.objective + feedback, request.repository, request.task_id
            )
            implementation = self.executor.implement(generation_request, plan)
            try:
                self._apply_implementation(implementation, plan, worktree, request)
                return implementation
            except ValueError as exc:
                if attempt or not str(exc).startswith("Expected one exact match"):
                    raise
                feedback = (
                    "\n\nCorrection for the previous draft: it was rejected because its old_text "
                    "matched multiple locations. Regenerate the edits with a longer exact old_text "
                    "that includes the relevant class/function declaration and surrounding lines, "
                    "so each edit matches exactly once. Do not change unrelated functions."
                )
        raise RuntimeError("Could not generate a unique patch")

    def _apply_implementation(self, implementation, plan, worktree, request):
        expected = set(plan.expected_files)
        root = Path(worktree).resolve()
        writes: list[tuple[Path, str]] = []
        for edit in implementation.edits:
            if len(edit.old_text.encode("utf-8")) > 1024 * 1024 or len(edit.new_text.encode("utf-8")) > 1024 * 1024:
                raise ValueError("An individual file edit may not exceed 1 MiB")
            relative = PurePosixPath(edit.path)
            if (relative.is_absolute() or ".." in relative.parts or not relative.parts
                    or "\\" in edit.path or ":" in edit.path or "\0" in edit.path):
                raise ValueError(f"Unsafe edit path: {edit.path}")
            if expected and edit.path not in expected:
                raise ValueError(f"Edit is outside planner-approved files: {edit.path}")
            untrusted_target = root.joinpath(*relative.parts)
            cursor = root
            for part in relative.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError(f"Symbolic-link edits are not allowed: {edit.path}")
            target = untrusted_target.resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"Edit escapes worktree: {edit.path}")
            if edit.old_text == "":
                if target.exists():
                    raise ValueError(f"New file already exists: {edit.path}")
                writes.append((target, edit.new_text))
            else:
                if not target.is_file():
                    raise ValueError(f"Edit target does not exist: {edit.path}")
                original = target.read_text(encoding="utf-8")
                matches = original.count(edit.old_text)
                if matches != 1:
                    if matches == 0:
                        raise ValueError(f"Expected one exact match in {edit.path}; found 0")
                    scoped_index = self._scoped_match(
                        original, edit.old_text, request.objective,
                        plan.summary + " " + " ".join(plan.steps),
                    )
                    if scoped_index is None:
                        raise ValueError(f"Expected one exact match in {edit.path}; found {matches}")
                    changed = (original[:scoped_index] + edit.new_text +
                               original[scoped_index + len(edit.old_text):])
                else:
                    changed = original.replace(edit.old_text, edit.new_text, 1)
                writes.append((target, changed))
        if not implementation.edits:
            raise ValueError("Executor returned no file edits")
        for target, content in writes:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return implementation

    @staticmethod
    def _scoped_match(source: str, old_text: str, objective: str, plan_text: str) -> int | None:
        """Resolve a repeated snippet only when the plan names one unique code scope."""
        declarations = list(re.finditer(
            r"(?m)^\s*(?:async\s+def|def|function|class)\s+([A-Za-z_]\w*)", source
        ))
        mentioned = set(re.findall(r"\b[A-Za-z_]\w*\b", objective + " " + plan_text))
        candidates: list[int] = []
        cursor = 0
        while (index := source.find(old_text, cursor)) >= 0:
            active_scope = None
            for declaration in declarations:
                if declaration.start() > index:
                    break
                active_scope = declaration.group(1)
            if active_scope in mentioned:
                candidates.append(index)
            cursor = index + len(old_text)
        return candidates[0] if len(candidates) == 1 else None

    def _review(self, worktree, request, plan, implementation, tests):
        diff = self.git.diff(worktree)
        if len(diff.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Git diff exceeds the 1 MiB review limit")
        return self.reviewer.review(request, plan, implementation, diff, tests)
