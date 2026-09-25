"""Issue #41: the remaining `configure.*` closed-list conditions.

Every case drives the real CLI (the one test seam) and asserts the exact
diagnostic set, per the conformance fixture shape.
"""

from __future__ import annotations

import json

from tests.conftest import assert_diagnostic, run_reverie


def test_rsop_without_a_host_argument_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")

    result = run_reverie("rsop", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.missing_host_argument")


def test_output_flag_on_compile_is_a_configure_error(fixture_dir, tmp_path):
    source = fixture_dir("minimal")

    result = run_reverie("compile", str(source), "--output", str(tmp_path / "out.yml"))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.unexpected_output_flag")


def test_tuple_strategy_without_tuple_keys_is_a_configure_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "reverie.yml").write_text(
        'layout: "{{ host.dc }}"\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  groups:\n"
        "    strategy: deep_tuple\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "configure.missing_tuple_keys",
        file=str(source / "reverie.yml"),
        key_path="groups",
    )


def test_tuple_keys_under_a_non_tuple_strategy_is_a_configure_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "reverie.yml").write_text(
        'layout: "{{ host.dc }}"\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  members:\n"
        "    strategy: append\n"
        "    tuple_keys: [name]\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "configure.unexpected_tuple_keys",
        file=str(source / "reverie.yml"),
        key_path="members",
    )


def test_unknown_key_in_a_merge_entry_is_a_configure_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "reverie.yml").write_text(
        'layout: "{{ host.dc }}"\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  members:\n"
        "    strategy: append\n"
        "    on_conflict: explode\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "configure.unknown_entry_key",
        file=str(source / "reverie.yml"),
        key="on_conflict",
    )


def test_defaults_floor_in_a_missing_directory_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: []\ndefaults: floor/common.yml\n', encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics, "configure.missing_defaults_directory", file=str(source / "reverie.yml")
    )


def test_defaults_file_missing_from_an_existing_directory_is_an_enumerate_error(fixture_dir):
    # The asymmetry the two conditions split on: a declared floor whose
    # directory exists but whose file doesn't is an ordinary
    # addressed-but-absent layer, not a malformed reverie.yml.
    source = fixture_dir("minimal")
    (source / "defaults" / "common.yml").unlink()

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "enumerate.missing_layer_file",
        host="host1",
        chain_entry="defaults/common.yml",
        rendered_address="defaults/common.yml",
    )
