"""House conventions no linter rule covers, checked mechanically.

Python source is ASCII: prose writes `--` for a dash and `...` for an
ellipsis. Markdown and YAML under docs/ and spec/ are out of scope.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_TREES = ("reverie", "scripts", "tests")


def _python_files() -> list[Path]:
    return sorted(path for tree in PYTHON_TREES for path in (REPO_ROOT / tree).rglob("*.py"))


def test_python_source_is_ascii():
    offenders = []
    for path in _python_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.isascii():
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, "non-ASCII in Python source -- write `--` and `...`:\n" + "\n".join(offenders)
