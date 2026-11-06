#!/usr/bin/env python3
"""Fail when a tracked code file has 1000 lines or more.

The baseline file (default .file-length-baseline) holds two kinds of lines:
  exclude <glob>          a generated or vendored code file this check skips
  freeze <path> <lines>   an existing offender; it may shrink, never grow
Compared with the baseline at the merge-base of HEAD and the default branch, a
raised freeze count, a new freeze line or a new exclude line is refused.
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


def parse_baseline(text, name):
    excludes, frozen = [], {}
    for number, raw in enumerate(text.splitlines(), 1):
        parts = raw.split("#", 1)[0].split()
        if not parts:
            continue
        if parts[0] == "exclude" and len(parts) == 2:
            excludes.append(parts[1])
        elif parts[0] == "freeze" and len(parts) == 3 and parts[2].isdigit():
            frozen[parts[1]] = int(parts[2])
        else:
            sys.exit(f"{name}:{number}: {BAD_LINE}")
    return excludes, frozen


def read_baseline(path):
    if not os.path.exists(path):
        return [], {}
    with open(path, encoding="utf-8") as fh:
        return parse_baseline(fh.read(), path)


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", root, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=git_env(),
        check=False,
    )
    return result.stdout.decode("utf-8") if result.returncode == 0 else None


def merge_base_baseline(root, baseline):
    for ref in ("origin/HEAD", "origin/main"):
        if git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
            break
    else:
        return None, "no origin/HEAD or origin/main ref"
    base = git(root, "merge-base", "HEAD", ref)
    if not base:
        return None, f"no merge-base of HEAD and {ref}"
    text = git(root, "show", f"{base.strip()}:{baseline}")
    if text is None:
        return None, f"no {baseline} at the merge-base with {ref}"
    return text, None


def loosened(old, new):
    old_excludes, old_frozen = old
    new_excludes, new_frozen = new
    for glob in new_excludes:
        if glob not in old_excludes:
            yield f"new exclude line 'exclude {glob}' is refused"
    for rel, lines in sorted(new_frozen.items()):
        if rel not in old_frozen:
            yield f"new freeze line 'freeze {rel} {lines}' is refused"
        elif lines > old_frozen[rel]:
            yield f"{rel}: freeze count raised from {old_frozen[rel]} to {lines}; refused"


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


def problems(counts, frozen):
    errors, notes = [], []
    for rel, lines in sorted(counts.items()):
        if rel not in frozen and lines >= LIMIT:
            errors.append(f"{rel}: {lines} lines; code files must stay under {LIMIT}")
    for rel, recorded in sorted(frozen.items()):
        lines = counts.get(rel)
        if lines is None or lines < LIMIT:
            notes.append(f"{rel}: now under {LIMIT} lines; remove its freeze line")
        elif lines > recorded:
            errors.append(
                f"{rel}: frozen at {recorded} lines, now {lines}; it may not grow"
            )
        elif lines < recorded:
            notes.append(
                f"{rel}: shrank to {lines} lines; you may lower its freeze count"
            )
    return errors, notes


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
    current = read_baseline(os.path.join(args.root, args.baseline))
    excludes, frozen = current
    counts = dict(tracked_code_files(args.root, excludes))

    if args.print_baseline:
        if frozen:
            sys.exit(f"{args.baseline} already freezes files; edit it by hand")
        for rel, lines in sorted(counts.items()):
            if lines >= LIMIT:
                print(f"freeze {rel} {lines}")
        return 0

    errors, notes = problems(counts, frozen)
    old_text, unreachable = merge_base_baseline(args.root, args.baseline)
    if unreachable:
        notes.append(f"freeze-raise refusal skipped: {unreachable}")
    else:
        errors += loosened(
            parse_baseline(old_text, f"merge-base:{args.baseline}"), current
        )
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
