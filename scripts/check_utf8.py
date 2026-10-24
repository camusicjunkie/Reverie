"""Fails when a tracked Markdown, YAML or Python file is not valid UTF-8.

Ruff reads Python only, so a stray cp1252 byte (an em dash saved as 0x97) in
CONTEXT.md (issue #71) went unnoticed until review. Run from
.githooks/pre-commit and CI, in the repo root. The message names each file and
the byte offset of the first bad byte.

It reads each file's blob from the index, not the working copy: the hook runs
before the commit, so the staged bytes are what would land. In CI's clean
checkout the index equals the working tree, so the result is the same.

A tracked file that is modified but not staged is therefore not checked at
commit time, and that is deliberate: its working-copy bytes are not part of
the commit, so a bad byte there cannot land. If it is staged later the hook
checks it then, and CI checks every checked-out file in any case.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

SUFFIXES = {".md", ".yml", ".yaml", ".py"}


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def main() -> int:
    entries = _git("ls-files", "-s", "-z").decode("utf-8").split("\0")
    seen = set()
    failures = []
    for entry in filter(None, entries):
        meta, name = entry.split("\t", 1)
        mode, sha, _stage = meta.split()
        if mode == "160000" or name in seen or PurePosixPath(name).suffix not in SUFFIXES:
            continue
        seen.add(name)  # an unmerged path is listed once per stage; check the first
        try:
            _git("cat-file", "blob", sha).decode("utf-8")
        except UnicodeDecodeError as error:
            failures.append(f"{name}: invalid UTF-8 at byte offset {error.start}")
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
