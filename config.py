"""Dependency-free TOML configuration with project-root containment."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class WorkflowConfig:
    database: Path
    workspace_root: Path
    command_timeout_seconds: float = 30
    max_output_bytes: int = 65536
    provider: str = "ollama"
    model: str = "qwen2.5-coder:7b"
    model_base_url: str = "http://127.0.0.1:11434"
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765


def load_config(path: str | Path | None = None) -> WorkflowConfig:
    config_path = Path(path) if path else PROJECT_ROOT / "config.toml"
    config_path = config_path.resolve()
    if not config_path.is_relative_to(PROJECT_ROOT):
        raise ValueError(f"Configuration file must stay inside project: {config_path}")
    data = tomllib.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    workflow = data.get("workflow", {})
    provider = data.get("provider", {})

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
    port = int(workflow.get("dashboard_port", 8765))
    if not 0 < port < 65536:
        raise ValueError("dashboard_port must be between 1 and 65535")
    provider_name = str(provider.get("name", "ollama")).lower()
    if provider_name not in {"ollama", "demo"}:
        raise ValueError("provider.name must be 'ollama' or 'demo'")
    model_url = str(provider.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
    parsed_model_url = urlsplit(model_url)
    if (parsed_model_url.scheme != "http" or parsed_model_url.hostname not in
            {"127.0.0.1", "localhost", "::1"} or parsed_model_url.username or
            parsed_model_url.password or parsed_model_url.path not in {"", "/"}):
        raise ValueError("provider.base_url must point to a local Ollama service")
    return WorkflowConfig(
        database=contained(str(workflow.get("database", "")), ".autonomous-eng.sqlite3"),
        workspace_root=contained(str(workflow.get("workspace_root", "")), "workspaces"),
        command_timeout_seconds=timeout,
        max_output_bytes=output_limit,
        provider=str(provider.get("name", "ollama")).lower(),
        model=str(provider.get("model", "qwen2.5-coder:7b")),
        model_base_url=model_url,
        dashboard_host=str(workflow.get("dashboard_host", "127.0.0.1")),
        dashboard_port=port,
    )
