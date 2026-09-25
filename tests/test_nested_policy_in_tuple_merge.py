"""Issue #47: a merge policy addressed inside a `deep_tuple`-merged list.

`deep_tuple` folds each matched general-layer element into the kept one via
a normal map merge, at the list's own key path -- so a policy declared under
that path (`groups/perms`) governs a real merge `resolve` performs. These
cases pin that `validate` sees the same key paths, that the distinction
against `unique_tuple` (where no such merge happens) is kept, and that a
nested policy is still validated against the shape it meets.
"""

from __future__ import annotations

import json

import yaml

from tests.conftest import assert_diagnostic, run_reverie


def _with_merge(source, *extra_lines: str) -> None:
    """Append `extra_lines` to the fixture's own `merge:` block.

    Appended to what the fixture actually declares -- `merge:` is its last
    block -- rather than to a copy of it, so these cases can't drift from
    the policies the fixture's other tests exercise.
    """

    config = source / "reverie.yml"
    config.write_text(
        config.read_text(encoding="utf-8") + "".join(f"  {line}\n" for line in extra_lines),
        encoding="utf-8",
        newline="",
    )


def test_policy_inside_a_deep_tuple_element_compiles_and_takes_effect(fixture_dir):
    source = fixture_dir("merge_lists")
    _with_merge(source, "groups/perms: append")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    # The "admins" element is contributed by all three layers, so the
    # nested `append` governs the fold: dcs/dublin.yml's [write] ahead of
    # the floor's [read]. "users" is the floor's alone -- nothing matched
    # it, so it survives whole and its `perms` is never merged at all.
    assert artifact["reverie"]["groups"] == [
        {"name": "admins", "perms": ["write", "read"], "region": "dublin"},
        {"name": "users", "perms": ["read"]},
    ]


def test_the_fold_is_one_merge_over_every_matched_layer_at_once(fixture_dir):
    source = fixture_dir("merge_lists")
    # The most specific contributor to "admins" removes `perms` outright.
    (source / "roles" / "web.yml").write_text(
        "groups:\n  - name: admins\n    region: dublin\n    perms: !remove\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    # A `!remove` reaches every more general contributor to the element, not
    # just the next one down: neither dcs/dublin.yml's nor the floor's
    # `perms` survives it.
    assert artifact["reverie"]["groups"] == [
        {"name": "admins", "region": "dublin"},
        {"name": "users", "perms": ["read"]},
    ]


def test_policy_inside_a_unique_tuple_element_is_still_reported_as_matching_nothing(fixture_dir):
    source = fixture_dir("merge_lists")
    _with_merge(source, "contacts/role: append")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    # `unique_tuple` keeps the more specific element whole -- no map merge
    # happens beneath it, so nothing ever addresses a path inside one.
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.pattern_matches_nothing", pattern="contacts/role")


def test_policy_inside_deep_tuple_elements_that_never_match_reports_as_never_applying(fixture_dir):
    source = fixture_dir("merge_lists")
    _with_merge(source, "groups/perms: append")
    # Every layer now names a different group, so no two elements ever
    # match and nothing is ever folded.
    (source / "dcs" / "dublin.yml").write_text(
        "groups:\n  - name: dublin-only\n    perms: [write]\n", encoding="utf-8", newline=""
    )
    (source / "roles" / "web.yml").write_text(
        "groups:\n  - name: web-only\n    perms: [write]\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    # The path is text some layer touches, so it isn't "matches nothing" --
    # it's a policy that governs no merge, the same verdict an unreachable
    # policy under a shadowed map ancestor gets.
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.strategy_never_applies", key_path="groups/perms")


def test_mis_shaped_policy_inside_a_deep_tuple_element_is_still_reported(fixture_dir):
    source = fixture_dir("merge_lists")
    _with_merge(source, "groups/perms: shallow")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    # The path is reachable now, so it isn't "matches nothing" -- but a map
    # strategy can never bind to the list `perms` actually holds.
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.strategy_never_applies", key_path="groups/perms")
    assert not any(d["id"] == "validate.pattern_matches_nothing" for d in diagnostics), diagnostics
