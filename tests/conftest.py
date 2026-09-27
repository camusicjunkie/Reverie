from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from reverie.spec_registry import (
    covered_user_stories,
    error_conditions,
    implemented_error_conditions,
    user_stories,
)

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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "story(*numbers): the user story (spec/user-stories.yml) this case argues for.",
    )


def _declared_stories(session: pytest.Session) -> set[int]:
    """Every story number the collected tests declare via `@pytest.mark.story`."""

    declared: set[int] = set()
    for item in session.items:
        for marker in item.iter_markers(name="story"):
            declared.update(marker.args)
    return declared


def _report(session: pytest.Session, message: str) -> None:
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminal is not None:
        terminal.write_line(message, red=True)
    session.exitstatus = 1


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if exitstatus != 0 or not _is_full_test_run(session):
        return

    missing = set(implemented_error_conditions()) - _asserted_ids
    if missing:
        _report(session, f"registry ids marked implemented with no fixture case: {sorted(missing)}")

    # The same rule one level up, over user stories (issue #52). Weaker
    # than the id check by construction: a marker is a claim, where an
    # asserted id is evidence -- a story is prose, so nothing can be
    # compared against it (see the note in spec/user-stories.yml). What it
    # does catch is the case the conformance audit found, a story with no
    # test at all.
    declared = _declared_stories(session)
    registry = user_stories()

    uncovered = set(covered_user_stories()) - declared
    if uncovered:
        _report(session, f"user stories marked covered with no test declaring them: {sorted(uncovered)}")

    unmarked = {number for number in declared - set(covered_user_stories()) if number in registry}
    if unmarked:
        _report(
            session,
            "user stories a test declares but the registry does not mark covered "
            f"(set `covered: true`): {sorted(unmarked)}",
        )

    unknown = declared - set(registry)
    if unknown:
        _report(session, f"tests declare story numbers that are not registered: {sorted(unknown)}")


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


# The two directories the compiler owns and may write to (CONTEXT.md
# "Owned directory") -- the whole of what a failed compile must leave alone.
OWNED_DIRECTORIES = ("host_vars", "inventory")


def owned_output(source: Path) -> dict[str, bytes]:
    """Every file under `source`'s owned directories, keyed by relative path.

    The bytes, not a parse: what a failed compile must leave untouched is
    the file as committed, byte for byte.
    """

    snapshot: dict[str, bytes] = {}
    for directory in OWNED_DIRECTORIES:
        root = source / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                snapshot[str(path.relative_to(source)).replace("\\", "/")] = path.read_bytes()
    return snapshot


def _source_argument(args: tuple[str, ...]) -> Path | None:
    """The source tree among `args`, if one is both named and present.

    Every invocation of either verb takes `<source>` as its first
    positional, so the first argument naming a directory that holds a
    `reverie.yml` is it. A configure-phase case that points at a missing
    directory, or at one with no `reverie.yml`, simply yields None -- there
    is no owned directory to protect in that case anyway.
    """

    for arg in args:
        candidate = Path(arg)
        if candidate.is_dir() and (candidate / "reverie.yml").exists():
            return candidate
    return None


def run_reverie(
    *args: str, cwd: Path | None = None, check_output_unchanged: bool = True
) -> subprocess.CompletedProcess:
    """Drive the real CLI through the process boundary (the one test seam).

    A run that *fails* additionally has emission's all-or-nothing guarantee
    asserted for it: the owned directories must come out byte-identical to
    how they went in (user story 17, ADR 0009). That check lives here, on
    the seam every test already goes through, so a newly added error case
    inherits it instead of having to remember it -- the same reason
    `assert_diagnostic` holds every diagnostic to its registry field set
    rather than leaving each test to spell it out.

    `check_output_unchanged=False` opts out, for a case that deliberately
    expects a partial write. Nothing needs it today.
    """

    source = _source_argument(args) if check_output_unchanged else None
    before = owned_output(source) if source is not None else None

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "reverie", *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )

    if before is not None and result.returncode != 0:
        after = owned_output(source)
        if after != before:
            appeared_or_vanished = sorted(set(before) ^ set(after))
            rewritten = sorted(p for p in before if p in after and before[p] != after[p])
            raise AssertionError(
                "a failed compile must leave the owned directories byte-identical (ADR 0009) -- "
                f"appeared or vanished: {appeared_or_vanished}, rewritten: {rewritten}"
            )

    return result
