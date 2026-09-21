from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixture_dir(tmp_path):
    """Copy a named fixture tree into an isolated tmp dir and return its path.

    Compiling writes host_vars/ and inventory/ into the source tree, so
    tests must never run against the checked-in fixtures directly.
    """

    counter = iter(range(1_000_000))

    def _copy(name: str) -> Path:
        dest = tmp_path / f"{name}-{next(counter)}"
        shutil.copytree(FIXTURES_DIR / name, dest)
        return dest

    return _copy


def run_reverie(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Drive the real CLI through the process boundary (the one test seam)."""

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "reverie", *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
