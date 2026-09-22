"""Issue #34: merge policy list strategies and shape classification."""

from __future__ import annotations

import json

import yaml

from tests.conftest import assert_diagnostic, run_reverie


def test_append_concatenates_most_specific_first_with_no_dedup(fixture_dir):
    source = fixture_dir("merge_lists")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    assert artifact["reverie"]["members"] == ["delta", "gamma", "alpha", "beta"]


def test_unique_keeps_first_occurrence_most_specific_first(fixture_dir):
    source = fixture_dir("merge_lists")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    # roles/web.yml: [z, w]; dcs/dublin.yml: [y, z]; defaults: [x, y] --
    # most-specific-first concatenation is [z, w, y, z, x, y], first
    # occurrence of each survives.
    assert artifact["reverie"]["tags"] == ["z", "w", "y", "x"]


def test_deep_tuple_merges_matched_elements_specific_wins(fixture_dir):
    source = fixture_dir("merge_lists")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    # The "admins" group is declared in all three layers -- deep_tuple
    # folds each match's other fields together, most specific winning
    # conflicts; "users" (defaults only) survives untouched, trailing.
    assert artifact["reverie"]["groups"] == [
        {"name": "admins", "perms": ["write"], "region": "dublin"},
        {"name": "users", "perms": ["read"]},
    ]


def test_unique_tuple_keeps_most_specific_element_whole_no_merge(fixture_dir):
    source = fixture_dir("merge_lists")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    # "alice" is declared in dcs/dublin.yml (role: sre) and defaults
    # (role: eng) -- unique_tuple keeps the most specific whole, no merge.
    assert artifact["reverie"]["contacts"] == [
        {"name": "carol", "role": "lead"},
        {"name": "alice", "role": "sre"},
        {"name": "bob", "role": "pm"},
    ]


def test_remove_on_scalar_list_element_holds_no_position(fixture_dir):
    source = fixture_dir("merge_lists")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    # roles/web.yml's features: [!remove b, c] over defaults' [a, b] --
    # the design tracker's own worked example, restated as a fixture.
    assert artifact["reverie"]["features"] == ["c", "a"]


def test_remove_on_tuple_matched_map_element_deletes_it_from_a_more_general_layer(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "roles" / "web.yml").write_text(
        "members: [delta]\n"
        "tags: [z, w]\n"
        "features: [!remove b, c]\n"
        "groups:\n"
        "  - name: admins\n"
        "    region: dublin\n"
        "  - !remove\n"
        "    name: users\n"
        "contacts:\n"
        "  - name: carol\n"
        "    role: lead\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    # defaults declares both "admins" and "users" -- roles/web.yml removes
    # "users" by tuple key, so only the (merged) "admins" survives.
    assert artifact["reverie"]["groups"] == [{"name": "admins", "perms": ["write"], "region": "dublin"}]


def test_remove_on_list_element_matching_nothing_below_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "roles" / "web.yml").write_text(
        "features: [!remove nonexistent]\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.remove_matches_nothing")


def test_duplicate_element_within_one_layer_under_unique_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "roles" / "web.yml").write_text(
        "tags: [z, z]\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.duplicate_in_layer", file=str(source / "roles" / "web.yml"))


def test_duplicate_in_layer_is_reported_for_every_violating_path_not_just_the_first(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "roles" / "web.yml").write_text(
        "tags: [z, z]\nfeatures: [a, a]\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    duplicate_count = sum(1 for d in diagnostics if d["id"] == "validate.duplicate_in_layer")
    assert duplicate_count == 2, diagnostics
    assert_diagnostic(diagnostics, "validate.duplicate_in_layer", file=str(source / "roles" / "web.yml"))


def test_tuple_strategy_against_a_plain_list_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "reverie.yml").write_text(
        "layout: \"{{ host.dc }}\"\n"
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "roles/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  members:\n"
        "    strategy: unique_tuple\n"
        "    tuple_keys: [name]\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.non_map_in_tuple_merge")


def test_list_strategy_never_applying_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "reverie.yml").write_text(
        "layout: \"{{ host.dc }}\"\n"
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "roles/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  members: append\n"
        "  dc: unique\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.strategy_never_applies", key_path="dc")


def test_shape_classification_any_map_present_makes_list_of_maps(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "defaults" / "common.yml").write_text(
        "contacts: [scalar_entry]\n"
        "groups: []\n"
        "features: [a, b]\n"
        "members: [alpha]\n"
        "tags: [x]\n",
        encoding="utf-8",
        newline="",
    )
    (source / "dcs" / "dublin.yml").write_text("members: []\ntags: []\n", encoding="utf-8", newline="")
    # roles/web.yml still contributes a map element to `contacts` -- a mix
    # of a scalar and a map anywhere in the concatenation is list-of-maps.

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    # The scalar element never matches any tuple_keys-bearing element, so
    # it simply clusters and trails like any other unmatched contribution.
    assert artifact["reverie"]["contacts"] == [{"name": "carol", "role": "lead"}, "scalar_entry"]
