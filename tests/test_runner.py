import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

from tools.runner import RunnerError, SafeRunner


class SafeRunnerTests(unittest.TestCase):
    def test_rejects_unknown_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RunnerError, "not allowed"):
                SafeRunner(temp).run("powershell", temp)

    def test_rejects_working_directory_outside_root(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            with self.assertRaisesRegex(RunnerError, "outside allowed root"):
                SafeRunner(root).run("unit", outside)

    def test_rejects_invalid_resource_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                SafeRunner(temp, timeout_seconds=0)

    def test_times_out_long_running_test_process(self):
        original = SafeRunner.PROFILES
        try:
            SafeRunner.PROFILES = {**original, "_test_timeout": (sys.executable, "-c", "import time; time.sleep(5)")}
            with tempfile.TemporaryDirectory() as temp:
                result = SafeRunner(temp, timeout_seconds=0.1).run("_test_timeout", temp)
                self.assertFalse(result.passed)
                self.assertIn("Timed out", result.stderr)
        finally:
            SafeRunner.PROFILES = original

    def test_caps_captured_process_output(self):
        original = SafeRunner.PROFILES
        try:
            SafeRunner.PROFILES = {**original, "_test_output": (sys.executable, "-c", "print('x' * 5000)")}
            with tempfile.TemporaryDirectory() as temp:
                result = SafeRunner(temp, max_output_bytes=128).run("_test_output", temp)
                self.assertLessEqual(len(result.stdout.encode("utf-8")), 128)
        finally:
            SafeRunner.PROFILES = original

    def test_pytest_profile_is_registered_and_missing_dependency_is_reported(self):
        self.assertEqual(SafeRunner.PROFILES["pytest"][:3], (sys.executable, "-m", "pytest"))
        with tempfile.TemporaryDirectory() as temp, patch("tools.runner.importlib.util.find_spec", return_value=None):
            result = SafeRunner(temp).run("pytest", temp)
        self.assertFalse(result.passed)
        self.assertIn("pytest is not installed", result.stderr)

    def test_java_profiles_are_fixed_and_offline(self):
        self.assertIn("--offline", SafeRunner.PROFILES["maven"])
        self.assertEqual(SafeRunner.PROFILES["maven"][-1], "test")
        self.assertIn("--offline", SafeRunner.PROFILES["gradle"])
        self.assertEqual(SafeRunner.PROFILES["gradle"][-1], "test")

    def test_missing_maven_is_reported_without_shell_fallback(self):
        with tempfile.TemporaryDirectory() as temp, patch("tools.runner.shutil.which", return_value=None):
            result = SafeRunner(temp).run("maven", temp)
        self.assertFalse(result.passed)
        self.assertEqual(result.returncode, 127)
        self.assertIn("not installed", result.stderr)

    def test_runner_does_not_forward_arbitrary_environment_secrets(self):
        profile = "_test_clean_environment"
        original = SafeRunner.PROFILES
        try:
            SafeRunner.PROFILES = {
                **original,
                profile: (sys.executable, "-c", "import os; print(os.getenv('AGENT_TEST_SECRET', 'missing'))"),
            }
            with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"AGENT_TEST_SECRET": "secret"}):
                result = SafeRunner(temp).run(profile, temp)
            self.assertTrue(result.passed, result.stderr)
            self.assertEqual(result.stdout.strip(), "missing")
        finally:
            SafeRunner.PROFILES = original


if __name__ == "__main__":
    unittest.main()
