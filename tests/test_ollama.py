import tempfile
import unittest
from pathlib import Path

from core.models import Implementation, Plan, TaskRequest, TestResult
from roles.ollama import OllamaProvider


class OllamaReviewerTests(unittest.TestCase):
    def test_review_prompt_excludes_implementer_explanation_and_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = OllamaProvider("local-test", "http://127.0.0.1:11434", rag_database=":memory:")
            captured = {}

            def fake_chat(system, prompt):
                captured["system"] = system
                captured["prompt"] = prompt
                return {"approved": True, "findings": []}

            provider._chat_json = fake_chat
            provider.review(
                TaskRequest("Fix the addition bug", str(Path(temp))),
                Plan("secret planner rationale", ("step",), "unit", ("app.py",)),
                Implementation(explanation="secret implementer rationale"),
                "diff --git a/app.py b/app.py\n+ return left + right",
                TestResult(True, 0, "2 tests passed", "", ("python", "-m", "unittest")),
            )

        prompt = captured["prompt"]
        self.assertIn("Fix the addition bug", prompt)
        self.assertIn("diff --git", prompt)
        self.assertIn("2 tests passed", prompt)
        self.assertNotIn("secret planner rationale", prompt)
        self.assertNotIn("secret implementer rationale", prompt)
        self.assertIn("hidden reasoning", captured["system"])

    def test_planner_accepts_only_registered_test_profiles(self):
        for profile in ("unit", "pytest", "maven", "gradle", "demo_regression"):
            with self.subTest(profile=profile):
                self.assertEqual(OllamaProvider._test_profile({"test_profile": profile}), profile)
        with self.assertRaisesRegex(ValueError, "not registered"):
            OllamaProvider._test_profile({"test_profile": "run-anything"})


if __name__ == "__main__":
    unittest.main()
