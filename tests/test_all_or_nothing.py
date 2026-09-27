"""Issue #49: a failed compile leaves the owned directories untouched.

User story 17 and half of ADR 0009: emission is all-or-nothing, so a
half-written artifact set can never be mistaken for a real, reviewable
change. Every case here compiles a good estate *first*, so there is real
output to preserve -- the state that actually matters, and the one a
never-compiled checkout can't exercise.

`run_reverie` asserts the same property for every failing run in the suite
(see `conftest.owned_output`), so these cases are the deliberate,
per-phase statement of a guarantee the seam already enforces everywhere.
Each one also pins *which* phase failed: a case that started passing
because the compile broke somewhere else would otherwise still look green.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import assert_diagnostic, owned_output, run_reverie


def _compiled(fixture_dir):
    """A successfully compiled estate, plus its owned-directory bytes."""

    source = fixture_dir("layered")
    result = run_reverie("compile", str(source))
    assert result.returncode == 0, result.stderr

    before = owned_output(source)
    # The guarantee is meaningless if there is nothing to protect.
    assert "host_vars/host1.yml" in before
    assert "inventory/hosts.yml" in before
    return source, before


def _failed_compile(source, before, expected_id: str) -> None:
    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, expected_id)
    assert owned_output(source) == before


def test_a_configure_failure_leaves_the_owned_directories_untouched(fixture_dir):
    source, before = _compiled(fixture_dir)
    config = source / "reverie.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace('layout: "{{ host.dc }}"', 'layout: "/dublin"'),
        encoding="utf-8",
        newline="",
    )

    _failed_compile(source, before, "configure.malformed_layout")


def test_an_enumerate_failure_leaves_the_owned_directories_untouched(fixture_dir):
    source, before = _compiled(fixture_dir)
    # A role fact no layer file answers. `layout` reads `dc`, not `role`,
    # so this is a missing layer file and nothing else.
    host = source / "hosts" / "dublin" / "host1.yml"
    host.write_text("dc: dublin\nrole: nonexistent\n", encoding="utf-8", newline="")

    _failed_compile(source, before, "enumerate.missing_layer_file")


def test_a_load_failure_leaves_the_owned_directories_untouched(fixture_dir):
    source, before = _compiled(fixture_dir)
    (source / "roles" / "web.yml").write_text("port: [80\n", encoding="utf-8", newline="")

    _failed_compile(source, before, "load.invalid_yaml")


def test_a_validate_failure_leaves_the_owned_directories_untouched(fixture_dir):
    source, before = _compiled(fixture_dir)
    config = source / "reverie.yml"
    config.write_text(
        config.read_text(encoding="utf-8") + "merge:\n  no_such_key: deep\n",
        encoding="utf-8",
        newline="",
    )

    _failed_compile(source, before, "validate.pattern_matches_nothing")


@pytest.mark.story(17)
def test_an_emit_failure_leaves_the_owned_directories_untouched(fixture_dir):
    source, before = _compiled(fixture_dir)
    # The phase where a write and a failure sit closest together: the
    # compile gets all the way to emit with a complete, correct artifact
    # set in hand, and must still write none of it.
    foreign = source / "host_vars" / "notes.yml"
    foreign.write_text("hand written\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    assert_diagnostic(json.loads(result.stderr), "emit.foreign_file", file=str(foreign))
    # The unmanaged file survives (it is never a cleanup target), and
    # nothing the compiler owns was rewritten around it.
    assert foreign.read_text(encoding="utf-8") == "hand written\n"
    assert owned_output(source) == {**before, "host_vars/notes.yml": b"hand written\n"}


def test_a_failure_writes_nothing_into_a_never_compiled_estate(fixture_dir):
    source = fixture_dir("layered")
    config = source / "reverie.yml"
    config.write_text(
        config.read_text(encoding="utf-8") + "merge:\n  no_such_key: deep\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    # Not even an empty owned directory: the compiler creates them only
    # once it is certain it will fill them.
    assert owned_output(source) == {}
    assert not (source / "host_vars").exists()
    assert not (source / "inventory").exists()
