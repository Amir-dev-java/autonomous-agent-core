"""Command-line entry point for the local engineering workflow prototype."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from config import PROJECT_ROOT, load_config
from core.context import TaskContext
from core.engine import WorkflowEngine
from core.models import StepStatus, TaskRequest
from roles.demo import DemoProvider
from tools.git_tools import GitTools
from tools.runner import SafeRunner


FIXTURE = PROJECT_ROOT / "fixtures" / "buggy_project"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local semi-automated engineering demo")
    parser.add_argument("--config", help="TOML configuration path (defaults to config.toml if present)")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run the isolated calculator bug-fix scenario")
    demo.add_argument("--objective", default="Fix calculator addition and add a regression test")
    status = commands.add_parser("status", help="Show persisted task and stage status")
    status.add_argument("task_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        with TaskContext(config.database) as context:
            if args.command == "status":
                task = context.get_task(args.task_id)
                steps = context.get_steps(args.task_id)
                print(json.dumps({
                    "task": {"id": task.task_id, "objective": task.objective,
                             "repository": task.repository, "status": task.status.value,
                             "report": task.report},
                    "steps": [{"name": step.name, "status": step.status.value,
                               "reason": step.reason, "payload": step.payload}
                              for step in steps],
                }, ensure_ascii=False, indent=2))
                return 0

            task_id = uuid.uuid4().hex[:12]
            git = GitTools(config.workspace_root)
            repository = git.initialize_fixture(FIXTURE, Path(task_id) / "repo")
            provider = DemoProvider()
            engine = WorkflowEngine(
                context, git,
                SafeRunner(config.workspace_root, config.command_timeout_seconds,
                           config.max_output_bytes),
                provider, provider, provider,
            )
            result = engine.run(TaskRequest(args.objective, str(repository), task_id))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == StepStatus.SUCCEEDED.value else 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "reason": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
