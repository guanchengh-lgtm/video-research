"""The behavior suite for the check lives with its canonical copy in
fleet-infrastructure (tests/test_file_length.py); this repository only runs it.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "tools" / "check_file_length.py"
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def test_this_repository_is_within_the_cap():
    result = subprocess.run(
        [sys.executable, str(CHECK), "--root", str(ROOT)],
        capture_output=True,
        text=True,
        env=ENV,
        check=False,
    )
    assert result.returncode == 0, result.stderr
