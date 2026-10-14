"""scripts/check_utf8.py fails on a tracked text file that is not UTF-8 (issue #71).

Ruff reads Python only, so a stray cp1252 byte in CONTEXT.md went unnoticed.
The seam is the script's CLI, run inside a throwaway git repository.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_utf8.py"


def _check(tmp_path: Path, files: dict[str, bytes]):
    # Under the pre-commit hook git exports GIT_INDEX_FILE and friends; left in
    # place they would point this throwaway repo's git calls at the real index.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)
    for name, data in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, env=env)
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True, env=env)


def test_clean_tree_passes(tmp_path):
    result = _check(tmp_path, {"a.md": b"caf\xc3\xa9 \xe2\x80\x94 ok", "b.yml": b"k: v\n"})
    assert result.returncode == 0, result.stderr


def test_bad_byte_in_markdown_names_file_and_offset(tmp_path):
    result = _check(tmp_path, {"CONTEXT.md": b"ab \x97 cd"})
    assert result.returncode == 1
    assert "CONTEXT.md" in result.stderr
    assert "offset 3" in result.stderr


def test_bad_byte_in_yaml_and_python_is_caught(tmp_path):
    result = _check(tmp_path, {"x.yml": b"k: \xff\n", "sub/y.py": b"# \x97\n"})
    assert result.returncode == 1
    assert "x.yml" in result.stderr
    assert "y.py" in result.stderr


def test_other_file_types_are_ignored(tmp_path):
    result = _check(tmp_path, {"blob.bin": b"\xff\xfe"})
    assert result.returncode == 0, result.stderr
