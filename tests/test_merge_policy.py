"""Issue #33: the `merge:` block and its scalar/map strategies."""

from __future__ import annotations

import json

import yaml

from tests.conftest import assert_diagnostic, run_reverie


def test_scalar_and_map_strategies_resolve_correctly(fixture_dir):
    source = fixture_dir("merge")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    assert artifact["reverie"] == {
        "env": "prod",
        "settings": {"region": "dublin-region", "timeout": 60},
        "nested": {"a": {"x": 99, "y": 2}, "b": 2, "c": 3},
        "port": 8080,
        "dc": "dublin",
        "role": "web",
    }


def test_more_specific_declared_policy_wins_over_ancestor_strategy(fixture_dir):
    source = fixture_dir("merge")
    (source / "reverie.yml").write_text(
        "layout: \"{{ host.dc }}\"\n"
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "roles/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  settings: shallow\n"
        "  nested: deep\n"
        "  nested/a: first\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    # roles/web.yml is the most specific layer defining nested/a ({x: 99}) --
    # under an explicit `first` at that exact path, dcs's {y: 2} never merges in.
    assert artifact["reverie"]["nested"]["a"] == {"x": 99}


def test_remove_deletes_key_defined_by_a_more_general_layer(fixture_dir):
    source = fixture_dir("layered")
    (source / "roles" / "web.yml").write_text("region: !remove\nport: 80\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    assert artifact["reverie"] == {"env": "prod", "port": 80, "dc": "dublin", "role": "web"}


def test_remove_targeting_only_a_more_specific_layer_is_a_validate_error(fixture_dir):
    source = fixture_dir("layered")
    (source / "roles" / "web.yml").write_text("port: !remove\n", encoding="utf-8", newline="")
    (source / "hosts" / "dublin" / "host1.yml").write_text(
        "dc: dublin\nrole: web\nport: 999\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.remove_matches_nothing")


def test_declared_strategy_never_applying_to_a_scalar_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge")
    (source / "reverie.yml").write_text(
        "layout: \"{{ host.dc }}\"\n"
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "roles/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  settings: shallow\n"
        "  nested: deep\n"
        "  port: deep\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.strategy_never_applies", key_path="port")


def test_pattern_matching_nothing_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge")
    (source / "reverie.yml").write_text(
        "layout: \"{{ host.dc }}\"\n"
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "roles/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  settings: shallow\n"
        "  nested: deep\n"
        "  does_not_exist: first\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.pattern_matches_nothing", pattern="does_not_exist")


def test_unknown_strategy_name_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: []\ndefaults: defaults/common.yml\nmerge:\n  site: bogus\n',
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "configure.unknown_strategy",
        file=str(source / "reverie.yml"),
        key_path="site",
        strategy="bogus",
    )


def test_missing_strategy_entry_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: []\ndefaults: defaults/common.yml\nmerge:\n  site: {}\n',
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics, "configure.missing_strategy", file=str(source / "reverie.yml"), key_path="site"
    )


def test_ambiguous_equally_specific_declarations_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: []\ndefaults: defaults/common.yml\n'
        "merge:\n"
        "  a/*: first\n"
        "  '*/b': shallow\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics, "configure.ambiguous_specificity", file=str(source / "reverie.yml"), key_path="a/*"
    )


def test_ambiguous_specificity_detected_across_double_star_patterns(fixture_dir):
    # "a/**" and "**/b" both score (1 literal, 0 stars) against the
    # concrete path "a/b" -- a tie that a purely structural, no-`**`
    # comparison would miss.
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: []\ndefaults: defaults/common.yml\n'
        "merge:\n"
        "  a/**: first\n"
        "  '**/b': shallow\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics, "configure.ambiguous_specificity", file=str(source / "reverie.yml"), key_path="a/**"
    )


def test_no_double_star_entry_falls_back_to_first(fixture_dir):
    # `port` in the "merge" fixture is covered by no declared pattern at
    # all -- it resolves under the implied `**: first`, taking the most
    # specific layer's value outright.
    source = fixture_dir("merge")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    assert artifact["reverie"]["port"] == 8080
