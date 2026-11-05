#!/usr/bin/env python3
"""Fail when a tracked code file has 1000 lines or more.

The baseline file (default .file-length-baseline) holds two kinds of lines:
  exclude <glob>          a generated or vendored code file this check skips
  freeze <path> <lines>   an existing offender; it may shrink, never grow
A frozen entry must equal the file's current count, so every shrink is recorded
and the list only gets shorter. New entries are a reviewed hand edit.
"""

import argparse
import fnmatch
import os
import subprocess
import sys

LIMIT = 1000
BAD_LINE = "expected 'exclude <glob>' or 'freeze <path> <lines>'"
CODE_EXTENSIONS = {
    ".py",
    ".sh",
    ".bash",
    ".zsh",
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".pine",
    ".lua",
    ".pl",
    ".jq",
    ".awk",
    ".ps1",
    ".sql",
}
# A git hook in a linked worktree exports these, and they override `git -C`.
GIT_POINTERS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)


def git_env():
    return {k: v for k, v in os.environ.items() if k not in GIT_POINTERS}


def count_lines(data):
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def is_code(path, head):
    ext = os.path.splitext(path)[1].lower()
    if ext in CODE_EXTENSIONS:
        return True
    return ext == "" and head.startswith(b"#!")


def read_baseline(path):
    excludes, frozen = [], {}
    if not os.path.exists(path):
        return excludes, frozen
    with open(path, encoding="utf-8") as fh:
        for number, raw in enumerate(fh, 1):
            parts = raw.split("#", 1)[0].split()
            if not parts:
                continue
            if parts[0] == "exclude" and len(parts) == 2:
                excludes.append(parts[1])
            elif parts[0] == "freeze" and len(parts) == 3 and parts[2].isdigit():
                frozen[parts[1]] = int(parts[2])
            else:
                sys.exit(f"{path}:{number}: {BAD_LINE}")
    return excludes, frozen


def tracked_code_files(root, excludes):
    out = subprocess.run(
        ["git", "-C", root, "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        env=git_env(),
    ).stdout
    for rel in out.decode("utf-8", "surrogateescape").split("\0"):
        full = os.path.join(root, rel)
        if not rel or os.path.islink(full) or not os.path.isfile(full):
            continue
        if any(fnmatch.fnmatchcase(rel, glob) for glob in excludes):
            continue
        with open(full, "rb") as fh:
            data = fh.read()
        if is_code(rel, data[:2]):
            yield rel, count_lines(data)


def problems(counts, frozen, baseline):
    for rel, lines in sorted(counts.items()):
        if rel not in frozen and lines >= LIMIT:
            yield f"{rel}: {lines} lines; code files must stay under {LIMIT}"
    for rel, recorded in sorted(frozen.items()):
        lines = counts.get(rel)
        if lines is None or lines < LIMIT:
            yield f"{rel}: frozen entry is stale; remove it from {baseline}"
        elif lines > recorded:
            yield f"{rel}: frozen at {recorded} lines, now {lines}; it may not grow"
        elif lines < recorded:
            yield f"{rel}: shrank to {lines} lines; record it as 'freeze {rel} {lines}'"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--baseline", default=".file-length-baseline")
    parser.add_argument(
        "--print-baseline",
        action="store_true",
        help="print freeze lines for today's offenders, once",
    )
    args = parser.parse_args()
    excludes, frozen = read_baseline(os.path.join(args.root, args.baseline))
    counts = dict(tracked_code_files(args.root, excludes))

    if args.print_baseline:
        if frozen:
            sys.exit(f"{args.baseline} already freezes files; edit it by hand")
        for rel, lines in sorted(counts.items()):
            if lines >= LIMIT:
                print(f"freeze {rel} {lines}")
        return 0

    errors = list(problems(counts, frozen, args.baseline))
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
