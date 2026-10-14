"""scripts/check_utf8.py fails on a tracked text file that is not UTF-8 (issue #71).

The cp1252 rationale lives in scripts/check_utf8.py. The seam is the script's
CLI, run inside a throwaway git repository.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_utf8.py"


def _env() -> dict[str, str]:
    # Under the pre-commit hook git exports GIT_INDEX_FILE and friends; left in
    # place they would point this throwaway repo's git calls at the real index.
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, env=_env())


def _run_script(repo: Path):
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True, env=_env())


def _stage_and_run_script_in_throwaway_repo(tmp_path: Path, files: dict[str, bytes]):
    _git(tmp_path, "init", "-q")
    for name, data in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _git(tmp_path, "add", "-A")
    return _run_script(tmp_path)


def test_clean_tree_passes(tmp_path):
    result = _stage_and_run_script_in_throwaway_repo(
        tmp_path, {"a.md": b"caf\xc3\xa9 \xe2\x80\x94 ok", "b.yml": b"k: v\n"}
    )
    assert result.returncode == 0, result.stderr


def test_bad_byte_in_markdown_names_file_and_offset(tmp_path):
    result = _stage_and_run_script_in_throwaway_repo(tmp_path, {"CONTEXT.md": b"ab \x97 cd"})
    assert result.returncode == 1
    assert "CONTEXT.md: invalid UTF-8 at byte offset 3" in result.stderr


def test_bad_byte_in_yaml_and_python_is_caught(tmp_path):
    result = _stage_and_run_script_in_throwaway_repo(
        tmp_path, {"x.yml": b"k: \xff\n", "z.yaml": b"k: \xfe\n", "sub/y.py": b"# \x97\n"}
    )
    assert result.returncode == 1
    assert "x.yml" in result.stderr
    assert "z.yaml" in result.stderr
    assert "y.py" in result.stderr


def test_other_file_types_are_ignored(tmp_path):
    result = _stage_and_run_script_in_throwaway_repo(tmp_path, {"blob.bin": b"\xff\xfe"})
    assert result.returncode == 0, result.stderr


def test_checks_the_staged_blob_not_the_working_copy(tmp_path):
    # The hook runs before the commit, so what matters is the index.
    _stage_and_run_script_in_throwaway_repo(tmp_path, {"CONTEXT.md": b"ab \x97 cd"})
    (tmp_path / "CONTEXT.md").write_bytes(b"fixed but not staged")

    result = _run_script(tmp_path)

    assert result.returncode == 1
    assert "CONTEXT.md: invalid UTF-8 at byte offset 3" in result.stderr


def test_fixed_and_staged_file_passes(tmp_path):
    _stage_and_run_script_in_throwaway_repo(tmp_path, {"CONTEXT.md": b"ab \x97 cd"})
    (tmp_path / "CONTEXT.md").write_bytes(b"fixed")
    _git(tmp_path, "add", "CONTEXT.md")

    assert _run_script(tmp_path).returncode == 0
