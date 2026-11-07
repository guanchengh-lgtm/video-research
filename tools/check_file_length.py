#!/usr/bin/env python3
"""Fail when a tracked code file has 1000 lines or more.

A file that was already at or over 1000 lines at the base may shrink but may not
grow. The base is the merge-base of HEAD with origin/HEAD or origin/main, or
HEAD^1 when that merge-base is HEAD itself, so a push to main checks the commit
it added. A change that must grow such a file first moves one whole part of it
into another file, or deletes dead or duplicated code in it.

The baseline file (default .file-length-baseline) holds only
  exclude <glob>   a code file this check skips, with the reason in a comment
A new exclude line is refused against the baseline at the base. Lines in the
older freeze grammar are ignored at the base, so the first change that deletes
them passes. This file is the canonical copy; other repos carry it byte for byte.
"""

import argparse
import fnmatch
import os
import subprocess
import sys

LIMIT = 1000
BAD_LINE = "expected 'exclude <glob>'"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
NO_BASE = (
    "cannot compare with the default branch: no origin/HEAD or origin/main ref, or no merge-base.\n"
    "  Run 'git fetch origin'. In GitHub Actions, set fetch-depth: 0 on actions/checkout."
)
SPLIT = (
    "  Split it first. In an earlier commit of this change, move one whole part with its own job\n"
    "  (a stage, a sourced library, a class, a test class, a block of rationale comments) into\n"
    "  another file with behavior unchanged, or delete dead or duplicated code in it.\n"
    "  Then make the full change. Do not join lines, cut unrelated lines, or fix fewer sites than\n"
    "  the defect has to make it fit."
)
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


def excludes_in(text):
    out = []
    for raw in text.splitlines():
        parts = raw.split("#", 1)[0].split()
        if len(parts) == 2 and parts[0] == "exclude":
            out.append(parts[1])
    return out


def read_baseline(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for number, raw in enumerate(text.splitlines(), 1):
        parts = raw.split("#", 1)[0].split()
        if parts and not (len(parts) == 2 and parts[0] == "exclude"):
            sys.exit(f"{path}:{number}: {BAD_LINE}")
    return excludes_in(text)


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", root, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=git_env(),
        check=False,
    )
    return result.stdout.decode().strip() if result.returncode == 0 else None


def base_commit(root):
    for ref in ("origin/HEAD", "origin/main"):
        if git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
            base = git(root, "merge-base", "HEAD", ref)
            if base and base == git(root, "rev-parse", "HEAD"):
                return git(root, "rev-parse", "--verify", "--quiet", "HEAD^1") or EMPTY_TREE
            return base
    return None


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


def lines_at(root, base, rel):
    blob = subprocess.run(
        ["git", "-C", root, "show", f"{base}:{rel}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=git_env(),
        check=False,
    )
    return count_lines(blob.stdout) if blob.returncode == 0 else None


def problems(root, base, baseline):
    excludes = read_baseline(os.path.join(root, baseline))
    old = excludes_in(git(root, "show", f"{base}:{baseline}") or "")
    errors = [
        f"new exclude line 'exclude {glob}' is refused"
        for glob in excludes
        if glob not in old
    ]
    for rel, lines in sorted(tracked_code_files(root, excludes)):
        if lines < LIMIT:
            continue
        before = lines_at(root, base, rel)
        if before is None or before < LIMIT:
            errors.append(
                f"{rel}: {lines} lines. Code files must stay under {LIMIT} lines; split it "
                "in this change (a new or renamed path counts as new)."
            )
        elif lines > before:
            errors.append(
                f"{rel}: {lines} lines, {before} at base {base[:7]}. A code file at {LIMIT} "
                f"lines or more may not grow.\n{SPLIT}"
            )
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--baseline", default=".file-length-baseline")
    args = parser.parse_args()
    base = base_commit(args.root)
    if base is None:
        print(NO_BASE, file=sys.stderr)
        return 1
    errors = problems(args.root, base, args.baseline)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
