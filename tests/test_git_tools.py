import tempfile
import unittest
from pathlib import Path

from tools.git_tools import GitToolError, GitTools


class GitToolsTests(unittest.TestCase):
    def test_creates_separate_worktree_and_reports_branch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "source"
            fixture.mkdir()
            (fixture / "sample.py").write_text("value = 1\n", encoding="utf-8")
            git = GitTools(root / "workspace")
            repo = git.initialize_fixture(fixture, "repo")
            worktree = git.create_worktree(repo, "worktrees/task1", "agent/task1")
            self.assertEqual(git.branch_name(worktree), "agent/task1")
            self.assertEqual(git.status(worktree), "")

    def test_rejects_branch_name_outside_agent_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "source"
            fixture.mkdir()
            (fixture / "sample.py").write_text("value = 1\n", encoding="utf-8")
            git = GitTools(root / "workspace")
            repo = git.initialize_fixture(fixture, "repo")
            with self.assertRaisesRegex(GitToolError, "Invalid isolated branch"):
                git.create_worktree(repo, "worktrees/task1", "main")


if __name__ == "__main__":
    unittest.main()
