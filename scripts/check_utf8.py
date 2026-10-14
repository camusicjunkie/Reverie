"""Fails when a tracked Markdown, YAML or Python file is not valid UTF-8.

Ruff reads Python only; a stray cp1252 byte in CONTEXT.md (issue #71) went
unnoticed until review. Run from .githooks/pre-commit and CI, in the repo
root. The message names each file and the byte offset of the first bad byte.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SUFFIXES = {".md", ".yml", ".yaml", ".py"}


def main() -> int:
    listing = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout.decode("utf-8")
    failures = []
    for name in filter(None, listing.split("\0")):
        path = Path(name)
        if path.suffix not in SUFFIXES or not path.is_file():
            continue
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            failures.append(f"{name}: invalid UTF-8 at byte offset {error.start}")
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
