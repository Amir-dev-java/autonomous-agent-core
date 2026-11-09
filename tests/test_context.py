import tempfile
import unittest
from pathlib import Path

from core.context import TaskContext
from core.models import StepStatus
from config import load_config


class TaskContextTests(unittest.TestCase):
    def test_task_and_steps_survive_reopening_database(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "state.sqlite3"
            with TaskContext(database) as context:
                task = context.create_task("t1", "fix bug", "repo")
                self.assertEqual(task.status, StepStatus.PENDING)
                context.record_step("t1", "plan", StepStatus.RUNNING)
                context.record_step(
                    "t1", "plan", StepStatus.SUCCEEDED,
                    payload={"step_count": 2},
                )
                context.set_task_status("t1", StepStatus.SUCCEEDED, "done")

            with TaskContext(database) as reopened:
                self.assertEqual(reopened.get_task("t1").status, StepStatus.SUCCEEDED)
                step = reopened.get_step("t1", "plan")
                self.assertEqual(step.payload, {"step_count": 2})
                self.assertIsNotNone(step.finished_at)

    def test_unknown_task_is_reported(self):
        with TaskContext(":memory:") as context:
            with self.assertRaisesRegex(KeyError, "Unknown task"):
                context.set_task_status("missing", StepStatus.FAILED)

    def test_config_rejects_paths_outside_project(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "external.toml"
            config.write_text("[workflow]\ndatabase = './db.sqlite3'\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must stay inside project"):
                load_config(config)


if __name__ == "__main__":
    unittest.main()
