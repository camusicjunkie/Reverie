from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from reverie.spec_registry import error_conditions, implemented_error_conditions

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Ids asserted via assert_diagnostic() during this test session -- the
# "every registry id needs a fixture case" mechanical check (issue #31)
# compares this against implemented_error_conditions() at session end.
_asserted_ids: set[str] = set()


def assert_diagnostic(diagnostics: list[dict], id: str, **expected_fields) -> dict:
    """Assert a diagnostic with `id` is present and matches the registry exactly.

    Looks up `id` in spec/error-conditions.yml, fails if it isn't registered,
    fails if the diagnostic's field set (everything but id/phase) doesn't
    exactly match the registry's declared field set for that id, and checks
    any `expected_fields` values. Records `id` as fixture-covered.
    """

    registry = error_conditions()
    assert id in registry, f"{id} is not a registered error condition (spec/error-conditions.yml)"

    match = next((d for d in diagnostics if d["id"] == id), None)
    assert match is not None, f"no diagnostic with id {id!r} found in {diagnostics!r}"

    actual_fields = set(match) - {"id", "phase"}
    declared_fields = set(registry[id]["fields"])
    assert actual_fields == declared_fields, (
        f"{id}: diagnostic fields {sorted(actual_fields)} != "
        f"registry-declared fields {sorted(declared_fields)}"
    )

    for key, value in expected_fields.items():
        assert match.get(key) == value, f"{id}.{key}: expected {value!r}, got {match.get(key)!r}"

    _asserted_ids.add(id)
    return match


def _is_full_test_run(session: pytest.Session) -> bool:
    """Whether this session collected every test module under tests/.

    A single-file run, `-k`/`-m` filter, or CI shard only asserts a subset
    of ids -- the "every implemented id has a fixture" check would then
    report ids as missing that a full run does cover, so it only applies
    when the whole suite ran.
    """

    config = session.config
    if config.option.keyword or config.option.markexpr:
        return False

    all_test_files = {p.resolve() for p in Path(__file__).resolve().parent.rglob("test_*.py")}
    collected_files = {Path(item.fspath).resolve() for item in session.items}
    return all_test_files <= collected_files


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if exitstatus != 0 or not _is_full_test_run(session):
        return
    missing = set(implemented_error_conditions()) - _asserted_ids
    if missing:
        terminal = session.config.pluginmanager.get_plugin("terminalreporter")
        if terminal is not None:
            terminal.write_line(
                f"registry ids marked implemented with no fixture case: {sorted(missing)}",
                red=True,
            )
        session.exitstatus = 1


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
