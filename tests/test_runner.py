import tempfile
import unittest
from pathlib import Path
import sys

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


if __name__ == "__main__":
    unittest.main()
