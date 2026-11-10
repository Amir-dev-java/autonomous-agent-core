"""Small allowlisted Git operations for isolated workflow worktrees."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


class GitToolError(RuntimeError):
    pass


class GitTools:
    def __init__(self, workspace_root: str | Path, timeout_seconds: float = 20) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout_seconds = timeout_seconds
        self.git = shutil.which("git")
        if self.git is None:
            raise GitToolError("Git executable is unavailable")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.empty_hooks = self.workspace_root / ".empty-hooks"
        self.empty_hooks.mkdir(exist_ok=True)
        self.empty_global_config = self.workspace_root / ".empty-gitconfig"
        self.empty_global_config.touch(exist_ok=True)

    def _run(self, args: tuple[str, ...], cwd: Path) -> str:
        directory = cwd.resolve()
        if not directory.is_relative_to(self.workspace_root):
            raise GitToolError(f"Git working directory is outside allowed root: {directory}")
        try:
            result = subprocess.run(
                (self.git, "-c", f"core.hooksPath={self.empty_hooks}",
                 "-c", f"init.templateDir={self.empty_hooks}", *args),
                cwd=directory, shell=False, check=False,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout_seconds, env=self._git_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise GitToolError(f"Git command timed out after {self.timeout_seconds:g} seconds") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[:4000]
            raise GitToolError(f"Git command failed ({result.returncode}): {detail}")
        return result.stdout

    def _git_env(self) -> dict[str, str]:
        keep = ("PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "TEMP", "TMP")
        env = {key: os.environ[key] for key in keep if key in os.environ}
        env.update({
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(self.empty_global_config),
            "GIT_AUTHOR_NAME": "Autonomous Engineering Demo",
            "GIT_AUTHOR_EMAIL": "demo@example.invalid",
            "GIT_COMMITTER_NAME": "Autonomous Engineering Demo",
            "GIT_COMMITTER_EMAIL": "demo@example.invalid",
        })
        return env

    def initialize_fixture(self, source: str | Path, repository: str | Path) -> Path:
        """Copy the bundled fixture into an isolated local repo and seed one baseline commit."""
        source_path = Path(source).resolve()
        repo_path = Path(repository)
        if not repo_path.is_absolute():
            repo_path = self.workspace_root / repo_path
        repo_path = repo_path.resolve()
        if not repo_path.is_relative_to(self.workspace_root):
            raise GitToolError(f"Fixture repository is outside allowed root: {repo_path}")
        if repo_path.exists() and any(repo_path.iterdir()):
            raise GitToolError(f"Fixture destination must be empty: {repo_path}")
        repo_path.mkdir(parents=True, exist_ok=True)
        for item in source_path.iterdir():
            if item.is_file():
                shutil.copy2(item, repo_path / item.name)
            elif item.is_dir():
                shutil.copytree(item, repo_path / item.name)
        self._run(("init", "--initial-branch=main"), repo_path)
        self._run(("add", "--", "."), repo_path)
        self._run(("commit", "-m", "fixture baseline"), repo_path)
        return repo_path

    def clone_local_repository(self, source: str | Path, destination: str | Path) -> Path:
        """Make an isolated local clone of a user's existing Git repository."""
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_dir() or not (source_path / ".git").exists():
            raise GitToolError(f"Project must be a local Git repository: {source_path}")
        destination_path = Path(destination)
        if not destination_path.is_absolute():
            destination_path = self.workspace_root / destination_path
        destination_path = destination_path.resolve()
        if not destination_path.is_relative_to(self.workspace_root):
            raise GitToolError(f"Clone destination is outside allowed root: {destination_path}")
        if destination_path.exists():
            raise GitToolError(f"Clone destination already exists: {destination_path}")
        source_status = subprocess.run(
            (self.git, "-C", str(source_path), "status", "--porcelain"),
            cwd=self.workspace_root, shell=False, check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds,
            env=self._git_env(),
        )
        if source_status.returncode != 0:
            raise GitToolError("Could not inspect the source repository's working tree")
        if source_status.stdout.strip():
            raise GitToolError(
                "Source repository has uncommitted changes. Commit or stash them before starting a task."
            )
        origin_url = None
        try:
            remote = subprocess.run(
                (self.git, "-C", str(source_path), "remote", "get-url", "origin"),
                cwd=self.workspace_root, shell=False, check=False, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds,
                env=self._git_env(),
            )
            if remote.returncode == 0:
                origin_url = remote.stdout.strip()
        except subprocess.TimeoutExpired as exc:
            raise GitToolError("Timed out while reading the project's GitHub remote") from exc
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(("clone", "--no-hardlinks", "--", str(source_path), str(destination_path)),
                  self.workspace_root)
        if origin_url:
            self._run(("remote", "set-url", "origin", origin_url), destination_path)
        else:
            self._run(("remote", "remove", "origin"), destination_path)
        return destination_path

    def create_worktree(self, repository: str | Path, worktree: str | Path, branch: str) -> Path:
        repo_path = Path(repository).resolve()
        if not repo_path.is_relative_to(self.workspace_root):
            raise GitToolError(f"Repository is outside allowed root: {repo_path}")
        if not re.fullmatch(r"agent/[a-zA-Z0-9._-]{1,80}", branch):
            raise GitToolError(f"Invalid isolated branch name: {branch}")
        worktree_path = Path(worktree)
        if not worktree_path.is_absolute():
            worktree_path = self.workspace_root / worktree_path
        worktree_path = worktree_path.resolve()
        if not worktree_path.is_relative_to(self.workspace_root):
            raise GitToolError(f"Worktree is outside allowed root: {worktree_path}")
        if worktree_path.exists():
            raise GitToolError(f"Worktree destination already exists: {worktree_path}")
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(("worktree", "add", "-b", branch, str(worktree_path), "HEAD"), repo_path)
        return worktree_path

    def status(self, worktree: str | Path) -> str:
        return self._run(("status", "--short"), Path(worktree))

    def diff(self, worktree: str | Path) -> str:
        return self._run(("diff", "--cached", "--no-ext-diff", "--", "."), Path(worktree))

    def stage_paths(self, worktree: str | Path, paths: tuple[str, ...]) -> None:
        if not paths:
            raise GitToolError("No implementation paths to stage")
        for path in paths:
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts or "\\" in path:
                raise GitToolError(f"Invalid file path to stage: {path}")
        self._run(("add", "--", *paths), Path(worktree))

    def push_branch(self, worktree: str | Path, branch: str) -> None:
        if not re.fullmatch(r"agent/[a-zA-Z0-9._-]{1,80}", branch):
            raise GitToolError(f"Invalid isolated branch name: {branch}")
        self._run(("push", "--set-upstream", "origin", branch), Path(worktree))

    def commit_changes(self, worktree: str | Path, message: str) -> str:
        if not message or len(message) > 100:
            raise GitToolError("Commit message must be between 1 and 100 characters")
        self._run(("commit", "-m", message), Path(worktree))
        return self._run(("rev-parse", "--short", "HEAD"), Path(worktree)).strip()

    def branch_name(self, worktree: str | Path) -> str:
        return self._run(("branch", "--show-current"), Path(worktree)).strip()
