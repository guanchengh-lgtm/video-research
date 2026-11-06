"""Code files stay under 1000 lines; check_file_length.py enforces it."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "tools" / "check_file_length.py"
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def check(root, *args):
    return subprocess.run(
        [sys.executable, str(CHECK), "--root", str(root), *args],
        capture_output=True,
        text=True,
        env=ENV,
        check=False,
    )


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, env=ENV)


class FileLengthCap(unittest.TestCase):
    def repo_with(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        subprocess.run(["git", "-C", tmp.name, "init", "-q"], check=True, env=ENV)
        for name, text in files.items():
            Path(tmp.name, name).write_text(text)
        subprocess.run(["git", "-C", tmp.name, "add", "-A"], check=True, env=ENV)
        return tmp.name

    def committed_repo(self, files):
        root = self.repo_with(files)
        self.commit(root)
        git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
        return root

    @staticmethod
    def commit(root):
        git(root, "add", "-A")
        git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")

    @staticmethod
    def lines(n):
        return "".join(f"x = {i}\n" for i in range(n))

    def test_a_999_line_file_passes(self):
        self.assertEqual(check(self.repo_with({"m.py": self.lines(999)})).returncode, 0)

    def test_a_1000_line_file_fails(self):
        result = check(self.repo_with({"m.py": self.lines(1000)}))
        self.assertEqual(result.returncode, 1)
        self.assertIn("m.py: 1000 lines", result.stderr)

    def test_a_frozen_file_may_not_grow(self):
        root = self.repo_with(
            {"m.py": self.lines(1201), ".file-length-baseline": "freeze m.py 1200\n"}
        )
        result = check(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("frozen at 1200 lines, now 1201", result.stderr)

    def test_a_frozen_file_that_shrinks_passes_with_a_note(self):
        root = self.committed_repo(
            {"m.py": self.lines(1100), ".file-length-baseline": "freeze m.py 1200\n"}
        )
        result = check(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("shrank to 1100 lines", result.stderr)

    def test_a_frozen_file_under_the_cap_passes_with_a_note_to_remove_it(self):
        root = self.committed_repo(
            {"m.py": self.lines(999), ".file-length-baseline": "freeze m.py 1200\n"}
        )
        result = check(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("remove its freeze line", result.stderr)

    def test_a_raised_freeze_count_is_refused(self):
        root = self.committed_repo(
            {"m.py": self.lines(1200), ".file-length-baseline": "freeze m.py 1200\n"}
        )
        Path(root, "m.py").write_text(self.lines(1300))
        Path(root, ".file-length-baseline").write_text("freeze m.py 1300\n")
        result = check(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("raised from 1200 to 1300", result.stderr)

    def test_a_new_freeze_line_is_refused(self):
        root = self.committed_repo({"m.py": self.lines(10), ".file-length-baseline": ""})
        Path(root, "m.py").write_text(self.lines(1100))
        Path(root, ".file-length-baseline").write_text("freeze m.py 1100\n")
        result = check(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("new freeze line 'freeze m.py 1100'", result.stderr)

    def test_a_new_exclude_line_is_refused(self):
        root = self.committed_repo({"m.py": self.lines(10), ".file-length-baseline": ""})
        Path(root, "m.py").write_text(self.lines(1100))
        Path(root, ".file-length-baseline").write_text("exclude m.py\n")
        result = check(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("new exclude line 'exclude m.py'", result.stderr)

    def test_the_baseline_is_compared_with_the_merge_base_not_the_main_tip(self):
        root = self.committed_repo(
            {"m.py": self.lines(1200), ".file-length-baseline": "freeze m.py 1200\n"}
        )
        git(root, "checkout", "-qb", "work")
        Path(root, "n.py").write_text("y = 1\n")
        self.commit(root)
        git(root, "checkout", "-q", "-")
        Path(root, "m.py").write_text(self.lines(1100))
        Path(root, ".file-length-baseline").write_text("freeze m.py 1100\n")
        self.commit(root)
        git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(root, "checkout", "-q", "work")
        result = check(root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_without_a_default_branch_the_widening_check_is_skipped_visibly(self):
        root = self.repo_with(
            {"m.py": self.lines(1100), ".file-length-baseline": "freeze m.py 1100\n"}
        )
        self.commit(root)
        result = check(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("refusal skipped", result.stderr)

    def test_an_inherited_git_dir_does_not_redirect_the_check(self):
        root = self.repo_with({"m.py": self.lines(1000)})
        other = self.repo_with({"far.py": self.lines(10)})
        result = subprocess.run(
            [sys.executable, str(CHECK), "--root", root],
            capture_output=True,
            text=True,
            env={**ENV, "GIT_DIR": str(Path(other, ".git"))},
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_this_repository_is_within_the_cap(self):
        result = check(ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
