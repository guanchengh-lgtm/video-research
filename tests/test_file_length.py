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


class FileLengthCap(unittest.TestCase):
    def repo_with(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        subprocess.run(["git", "-C", tmp.name, "init", "-q"], check=True, env=ENV)
        for name, text in files.items():
            Path(tmp.name, name).write_text(text)
        subprocess.run(["git", "-C", tmp.name, "add", "-A"], check=True, env=ENV)
        return tmp.name

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

    def test_a_frozen_file_that_shrinks_must_record_its_new_count(self):
        root = self.repo_with(
            {"m.py": self.lines(1100), ".file-length-baseline": "freeze m.py 1200\n"}
        )
        result = check(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("record it as 'freeze m.py 1100'", result.stderr)

    def test_a_frozen_entry_under_the_cap_is_stale(self):
        root = self.repo_with(
            {"m.py": self.lines(999), ".file-length-baseline": "freeze m.py 1200\n"}
        )
        result = check(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("frozen entry is stale", result.stderr)

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
