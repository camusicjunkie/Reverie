"""Issue #42: the remaining `load.*` closed-list conditions.

`load.forbidden_alias` lives with the other parse-time rejections in
tests/test_serialisation.py, the dedicated serialisation family.
"""

from __future__ import annotations

import json

from tests.conftest import assert_diagnostic, run_reverie


def _write_layer(source, text: str) -> None:
    (source / "defaults" / "common.yml").write_text(text, encoding="utf-8", newline="")


def test_duplicate_key_in_a_mapping_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    _write_layer(source, "site: dublin\nsite: paris\n")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "load.duplicate_key",
        file=str(source / "defaults" / "common.yml"),
        line=2,
    )


def test_non_string_key_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    _write_layer(source, "site: dublin\nports:\n  80: http\n")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "load.non_string_key",
        file=str(source / "defaults" / "common.yml"),
        line=3,
    )


def test_key_containing_the_path_separator_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    _write_layer(source, "site: dublin\nfiles/items: []\n")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "load.key_contains_separator",
        file=str(source / "defaults" / "common.yml"),
        line=2,
    )


def test_unbalanced_deferred_jinja_in_a_value_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    _write_layer(source, "site: dublin\ngreeting: \"hello {{ ansible_hostname \"\n")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "load.malformed_deferred_template",
        file=str(source / "defaults" / "common.yml"),
        line=2,
    )


def test_balanced_deferred_jinja_passes_through_untouched(fixture_dir):
    import yaml

    source = fixture_dir("minimal")
    _write_layer(source, "site: dublin\ngreeting: \"hello {{ ansible_hostname }}\"\n")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    assert artifact["reverie"]["greeting"] == "hello {{ ansible_hostname }}"


def test_multiple_documents_in_one_file_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    _write_layer(source, "site: dublin\n---\nsite: paris\n")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "load.multiple_documents",
        file=str(source / "defaults" / "common.yml"),
        line=2,
    )


def test_reserved_top_level_name_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    _write_layer(source, "site: dublin\nreverie_meta:\n  spec_version: 1\n")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "load.reserved_name_key",
        file=str(source / "defaults" / "common.yml"),
        line=2,
    )


def test_reserved_name_below_the_top_level_is_fine(fixture_dir):
    import yaml

    source = fixture_dir("minimal")
    _write_layer(source, "site: dublin\nnested:\n  reverie: yes-please\n")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    assert artifact["reverie"]["nested"] == {"reverie": "yes-please"}


def test_illegal_fact_name_in_a_host_file_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "hosts" / "host1.yml").write_text("data-centre: dublin\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "load.illegal_fact_name",
        file=str(source / "hosts" / "host1.yml"),
        line=1,
    )


def test_the_fact_name_rule_applies_to_host_files_only(fixture_dir):
    # A layer file's keys are data, not facts the chain can substitute --
    # the identifier grammar binds to the host layer alone.
    import yaml

    source = fixture_dir("minimal")
    _write_layer(source, "site: dublin\ndata-centre: dublin\n")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    assert artifact["reverie"]["data-centre"] == "dublin"


def test_two_host_files_with_the_same_stem_is_a_load_error(fixture_dir):
    # Both files sit in a layout-legal position for their own `dc` fact --
    # the collision is purely one of identity, which is the filename stem.
    source = fixture_dir("merge_lists_multi_host")
    (source / "hosts" / "dublin" / "host2.yml").write_text(
        "dc: dublin\nrole: api\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "load.duplicate_host_name")
