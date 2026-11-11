"""Command-profile runner with workspace containment and bounded output."""

from __future__ import annotations

import os
import importlib.util
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from core.models import TestResult


class RunnerError(RuntimeError):
    pass


class SafeRunner:
    PROFILES = {
        "unit": (sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"),
        "pytest": (sys.executable, "-m", "pytest", "-q"),
        "maven": ("mvn", "--offline", "--batch-mode", "test"),
        "gradle": ("gradle", "--offline", "--no-daemon", "test"),
        "demo_regression": (
            sys.executable, "-m", "unittest", "discover", "-s", "tests",
            "-p", "test_regression.py", "-v",
        ),
    }

    def __init__(self, workspace_root: str | Path, timeout_seconds: float = 30,
                 max_output_bytes: int = 65536) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        if timeout_seconds <= 0 or max_output_bytes <= 0:
            raise ValueError("timeout and output limit must be positive")

    def run(self, profile: str, cwd: str | Path) -> TestResult:
        command = self.PROFILES.get(profile)
        if command is None:
            raise RunnerError(f"Command profile is not allowed: {profile}")
        directory = Path(cwd).resolve()
        if not directory.is_relative_to(self.workspace_root):
            raise RunnerError(f"Working directory is outside allowed root: {directory}")
        if not directory.is_dir():
            raise RunnerError(f"Working directory does not exist: {directory}")

        if profile == "pytest" and importlib.util.find_spec("pytest") is None:
            return TestResult(
                False, 127, "", "pytest is not installed in the configured Python environment",
                command,
            )
        if command[0] not in {sys.executable, "python", "python3"}:
            executable = shutil.which(command[0])
            if executable is None:
                return TestResult(
                    False, 127, "", f"Required test tool '{command[0]}' is not installed", command,
                )
            command = (executable, *command[1:])

        env = {"PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
            env["TEMP"] = os.environ.get("TEMP", "")
            env["TMP"] = os.environ.get("TMP", "")
        env["PATH"] = os.environ.get("PATH", "")
        try:
            process = subprocess.Popen(
                command, cwd=directory, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, env=env,
                close_fds=True,
                **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}),
            )
        except OSError as exc:
            return TestResult(False, 127, "", f"Could not start test tool: {exc}", command)
        captured = {"stdout": bytearray(), "stderr": bytearray()}

        def drain(pipe, key: str) -> None:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    return
                remaining = max(0, self.max_output_bytes - len(captured[key]))
                if remaining:
                    captured[key].extend(chunk[:remaining])

        threads = [
            threading.Thread(target=drain, args=(process.stdout, "stdout"), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            returncode = process.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            returncode = process.wait()
        for thread in threads:
            thread.join(timeout=2)
        process.stdout.close()
        process.stderr.close()
        stdout = bytes(captured["stdout"]).decode("utf-8", errors="replace")
        stderr = bytes(captured["stderr"]).decode("utf-8", errors="replace")
        if timed_out:
            stderr = (stderr + "\n" if stderr else "") + f"Timed out after {self.timeout_seconds:g} seconds"
            returncode = -1
        return TestResult(
            passed=returncode == 0, returncode=returncode, stdout=stdout,
            stderr=stderr, command=command,
        )
