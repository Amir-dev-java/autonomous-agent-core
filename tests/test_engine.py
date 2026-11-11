import tempfile
import unittest
from pathlib import Path

from core.context import TaskContext
from core.engine import WorkflowEngine
from core.models import Implementation, Review, StepStatus, TaskRequest
from roles.demo import DemoProvider
from tools.git_tools import GitTools
from tools.runner import SafeRunner


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "buggy_project"


class WrongExecutor(DemoProvider):
    def implement(self, request, plan):
        self.calls = getattr(self, "calls", 0) + 1
        if self.calls > 1:
            wrong = DemoProvider.new_expression.replace("left + right", "left * right")
            return Implementation(
                edits=(self._edit(wrong, wrong),),
                explanation="Keep the incorrect multiplication for the retry-limit test",
            )
        return Implementation(
            edits=(self._wrong_edit(),), explanation="Deliberately incorrect test implementation"
        )

    @staticmethod
    def _wrong_edit():
        from core.models import FileEdit
        return FileEdit("calculator.py", DemoProvider.old_expression,
                        DemoProvider.new_expression.replace("left + right", "left * right"))

    @staticmethod
    def _edit(old_text, new_text):
        from core.models import FileEdit
        return FileEdit("calculator.py", old_text, new_text)


class FixAfterFeedbackExecutor(WrongExecutor):
    def __init__(self):
        self.requests = []

    def implement(self, request, plan):
        self.requests.append(request.objective)
        if len(self.requests) == 1:
            return Implementation(edits=(self._wrong_edit(),), explanation="First draft has a bug")
        wrong = DemoProvider.new_expression.replace("left + right", "left * right")
        return Implementation(
            edits=(self._edit(wrong, DemoProvider.new_expression),),
            explanation="Fix multiplication after receiving regression output",
        )


class FixAfterReviewExecutor(DemoProvider):
    def __init__(self):
        self.requests = []

    def implement(self, request, plan):
        self.requests.append(request.objective)
        if len(self.requests) == 1:
            return super().implement(request, plan)
        old = DemoProvider.new_expression
        new = old.replace("    return left + right", "    # Preserve signed inputs.\n    return left + right")
        from core.models import FileEdit
        return Implementation((FileEdit("calculator.py", old, new),), "Address review finding")


class RejectOnceReviewer(DemoProvider):
    def __init__(self):
        self.calls = 0

    def review(self, request, plan, implementation, diff, tests):
        self.calls += 1
        if self.calls == 1:
            return Review(False, ("Document signed input behavior",))
        return super().review(request, plan, implementation, diff, tests)


class UnsafeExecutor(DemoProvider):
    def implement(self, request, plan):
        from core.models import FileEdit
        return Implementation(
            edits=(FileEdit("../outside.py", "x", "y"),),
            explanation="Deliberately unsafe path",
        )


class WorkflowEngineTests(unittest.TestCase):
    def run_engine(self, executor=None, reviewer=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        workspace_root = root / "workspace"
        git = GitTools(workspace_root)
        task_id = "task123"
        repository = git.initialize_fixture(FIXTURE, Path(task_id) / "repo")
        context = TaskContext(root / "state.sqlite3")
        self.addCleanup(context.close)
        provider = DemoProvider()
        engine = WorkflowEngine(
            context, git, SafeRunner(workspace_root, timeout_seconds=5),
            provider, executor or provider, reviewer or provider,
        )
        request = TaskRequest("Fix calculator addition and add a regression test", str(repository), task_id)
        result = engine.run(request)
        return result, context, git, repository

    def test_success_runs_regression_and_reviews_isolated_change(self):
        result, context, git, repository = self.run_engine()
        self.assertEqual(result["status"], "succeeded", result["report"])
        self.assertTrue(result["branch"].startswith("agent/"))
        worktree = Path(result["worktree"])
        self.assertIn("return left + right", (worktree / "calculator.py").read_text(encoding="utf-8"))
        self.assertIn("return left - right", (repository / "calculator.py").read_text(encoding="utf-8"))
        self.assertTrue(all(step.status == StepStatus.SUCCEEDED for step in context.get_steps("task123")))

    def test_failing_regression_is_persisted_with_reason(self):
        executor = WrongExecutor()
        result, context, _git, _repository = self.run_engine(executor)
        self.assertEqual(result["status"], "failed")
        self.assertIn("tests failed", result["report"])
        tests_step = context.get_step("task123", "tests")
        self.assertEqual(tests_step.status, StepStatus.FAILED)
        self.assertIn("Traceback", tests_step.reason)
        self.assertEqual(context.get_task("task123").status, StepStatus.FAILED)
        self.assertEqual(executor.calls, WorkflowEngine.MAX_ATTEMPTS)
        self.assertEqual(context.get_step("task123", "tests_attempt_3").status, StepStatus.FAILED)

    def test_test_failure_is_sent_back_and_repaired_within_attempt_limit(self):
        executor = FixAfterFeedbackExecutor()
        result, context, _git, _repository = self.run_engine(executor)
        self.assertEqual(result["status"], "succeeded", result["report"])
        self.assertEqual(len(executor.requests), 2)
        self.assertIn("Repair feedback", executor.requests[1])
        self.assertIn("Traceback", executor.requests[1])
        self.assertEqual(context.get_step("task123", "tests_attempt_1").status, StepStatus.FAILED)
        self.assertEqual(context.get_step("task123", "tests_attempt_2").status, StepStatus.SUCCEEDED)

    def test_reviewer_findings_are_sent_back_to_executor(self):
        executor = FixAfterReviewExecutor()
        reviewer = RejectOnceReviewer()
        result, context, _git, _repository = self.run_engine(executor, reviewer)
        self.assertEqual(result["status"], "succeeded", result["report"])
        self.assertEqual(reviewer.calls, 2)
        self.assertIn("independent review rejected", executor.requests[1])
        self.assertIn("Document signed input behavior", executor.requests[1])
        self.assertEqual(context.get_step("task123", "review_attempt_1").status, StepStatus.FAILED)
        self.assertEqual(context.get_step("task123", "review_attempt_2").status, StepStatus.SUCCEEDED)

    def test_executor_cannot_edit_outside_worktree(self):
        result, context, _git, _repository = self.run_engine(UnsafeExecutor())
        self.assertEqual(result["status"], "failed")
        implementation = context.get_step("task123", "implementation")
        self.assertEqual(implementation.status, StepStatus.FAILED)
        self.assertIn("Unsafe edit path", implementation.reason)


if __name__ == "__main__":
    unittest.main()
