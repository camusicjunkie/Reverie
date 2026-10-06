"""Issue #44: the remaining `validate.*` and `emit.*` closed-list conditions."""

from __future__ import annotations

import json

import pytest

from reverie.errors import PhaseFailed
from reverie.phases import emit as emit_phase
from reverie.phases.configure import SourceConfig
from reverie.phases.enumerate import HostPlan
from reverie.phases.resolve import ResolvedHost
from tests.conftest import assert_diagnostic, run_reverie

_MERGE_REVERIE_YML = (
    'layout: "{{ host.dc }}"\n'
    "chain:\n"
    '  - "dcs/{{ host.dc }}.yml"\n'
    '  - "roles/{{ host.role }}.yml"\n'
    "defaults: defaults/common.yml\n"
)


def test_declared_secret_pattern_matching_nothing_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge")
    (source / "reverie.yml").write_text(
        _MERGE_REVERIE_YML + "secrets:\n  - credentials/**\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics, "validate.secrets_pattern_matches_nothing", pattern="credentials/**"
    )


def test_element_missing_a_declared_tuple_key_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "dcs" / "dublin.yml").write_text(
        "members: [gamma]\n"
        "tags: [y, z]\n"
        "groups:\n"
        "  - perms: [write]\n"
        "contacts:\n"
        "  - name: alice\n"
        "    role: sre\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.missing_tuple_key")


def test_host_resolving_to_no_keys_at_all_is_a_validate_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "defaults" / "common.yml").write_text("{}\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.host_has_no_keys", host="host1")


def test_every_top_level_key_removed_away_also_leaves_no_keys(fixture_dir):
    source = fixture_dir("minimal")
    (source / "hosts" / "host1.yml").write_text("site: !remove\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.host_has_no_keys", host="host1")


def test_duplicate_element_in_the_defaults_floor_is_its_own_condition(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "defaults" / "common.yml").write_text(
        "members: [alpha, beta]\n"
        "tags: [x, y, y]\n"
        "features: [a, b]\n"
        "groups:\n"
        "  - name: admins\n"
        "    perms: [read]\n"
        "  - name: users\n"
        "    perms: [read]\n"
        "contacts:\n"
        "  - name: alice\n"
        "    role: eng\n"
        "  - name: bob\n"
        "    role: pm\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "validate.duplicate_floor_key",
        file=str(source / "defaults" / "common.yml"),
    )
    assert not any(d["id"] == "validate.duplicate_in_layer" for d in diagnostics)


def test_host_set_mismatch_between_resolve_and_emit_is_an_emit_error(tmp_path):
    # The one case driven below the CLI seam rather than through it: the
    # guard is unreachable from a source tree (load.duplicate_host_name
    # catches the only way the sets can diverge), so there is no fixture
    # that could reach it. Asserted here so the registry entry still has a
    # case backing it.
    config = SourceConfig(
        root=tmp_path,
        layout="",
        chain=[],
        defaults=None,
        merge_policies=[],
        secrets=[],
        secret_backend=None,
        inventory_groups=[],
        ansible_host_fact=None,
    )
    plans = [HostPlan(name="host1", file=tmp_path / "hosts" / "host1.yml", layers=[])]
    resolved = [ResolvedHost(name="host2", data={}, layers_walked=[])]

    try:
        emit_phase.emit(config, resolved, plans, {})
    except PhaseFailed as exc:
        diagnostics = [d.to_dict() for d in exc.diagnostics]
    else:
        raise AssertionError("emit did not fail on a mismatched host set")

    assert_diagnostic(diagnostics, "emit.host_set_mismatch")


@pytest.mark.story(19)
def test_two_distinct_conditions_in_one_phase_are_collected_together(fixture_dir):
    """Issue #51, user story 19 -- collect every error within a phase.

    `test_merge_lists` asserts that two instances of *one* condition are
    both reported. This is the case the story is actually about: two
    *different* conditions found in the same phase come back in one run,
    so an author fixes both at once instead of one recompile at a time.
    A premature `raise_if_any()` between checks would regress it.
    """

    source = fixture_dir("merge_lists")
    # A dead policy (nothing at that key path) and a stale !remove (nothing
    # more general to remove) -- different checks, same phase.
    config = source / "reverie.yml"
    config.write_text(
        config.read_text(encoding="utf-8") + "  no_such_key: deep\n", encoding="utf-8", newline=""
    )
    (source / "roles" / "web.yml").write_text(
        "never_defined_anywhere: !remove\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.pattern_matches_nothing", pattern="no_such_key")
    assert_diagnostic(diagnostics, "validate.remove_matches_nothing")
    # Every reported condition belongs to the phase that aborted: the run
    # stops at the boundary, it does not continue into resolve or emit.
    assert {d["phase"] for d in diagnostics} == {"validate"}
