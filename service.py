"""Construct and run isolated engineering tasks for CLI and dashboard callers."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from config import WorkflowConfig
from core.context import TaskContext
from core.engine import WorkflowEngine
from core.models import TaskRequest
from roles.demo import DemoProvider
from roles.ollama import OllamaProvider
from tools.git_tools import GitTools
from tools.runner import SafeRunner


class WorkflowService:
    def __init__(self, config: WorkflowConfig, workers: int = 2) -> None:
        self.config = config
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="agent-task")

    def submit(self, objective: str, repository: str) -> str:
        task_id = uuid.uuid4().hex[:12]
        self._executor.submit(self.run, TaskRequest(objective, repository, task_id))
        return task_id

    def run(self, request: TaskRequest) -> dict[str, object]:
        if self.config.provider == "demo":
            provider = DemoProvider()
        elif self.config.provider == "ollama":
            provider = OllamaProvider(self.config.model, self.config.model_base_url)
        else:
            raise ValueError(f"Unsupported local provider: {self.config.provider}")
        git = GitTools(self.config.workspace_root)
        runner = SafeRunner(
            self.config.workspace_root, self.config.command_timeout_seconds,
            self.config.max_output_bytes,
        )
        with TaskContext(self.config.database) as context:
            engine = WorkflowEngine(context, git, runner, provider, provider, provider)
            return engine.run(request)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
