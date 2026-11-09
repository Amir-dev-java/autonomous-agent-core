"""Dependency-free TOML configuration with project-root containment."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class WorkflowConfig:
    database: Path
    workspace_root: Path
    command_timeout_seconds: float = 30
    max_output_bytes: int = 65536


def load_config(path: str | Path | None = None) -> WorkflowConfig:
    config_path = Path(path) if path else PROJECT_ROOT / "config.toml"
    config_path = config_path.resolve()
    if not config_path.is_relative_to(PROJECT_ROOT):
        raise ValueError(f"Configuration file must stay inside project: {config_path}")
    data = tomllib.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    workflow = data.get("workflow", {})

    def contained(value: str, fallback: str) -> Path:
        candidate = (PROJECT_ROOT / value if value else PROJECT_ROOT / fallback).resolve()
        if not candidate.is_relative_to(PROJECT_ROOT):
            raise ValueError(f"Configured path must stay inside project: {candidate}")
        return candidate

    timeout = float(workflow.get("command_timeout_seconds", 30))
    output_limit = int(workflow.get("max_output_bytes", 65536))
    if not 0 < timeout <= 3600:
        raise ValueError("command_timeout_seconds must be between 0 and 3600")
    if not 0 < output_limit <= 16 * 1024 * 1024:
        raise ValueError("max_output_bytes must be between 1 and 16777216")
    return WorkflowConfig(
        database=contained(str(workflow.get("database", "")), ".autonomous-eng.sqlite3"),
        workspace_root=contained(str(workflow.get("workspace_root", "")), "workspaces"),
        command_timeout_seconds=timeout,
        max_output_bytes=output_limit,
    )
