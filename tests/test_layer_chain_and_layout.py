"""Issue #32: a real, ordered, multi-entry chain, plus `layout:` validation."""

from __future__ import annotations

import json

import yaml

from tests.conftest import assert_diagnostic, run_reverie


def test_multi_entry_chain_resolves_general_to_specific(fixture_dir):
    source = fixture_dir("layered")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    assert artifact["reverie"] == {
        "env": "prod",
        "region": "emea",
        "port": 80,
        "dc": "dublin",
        "role": "web",
    }
    assert artifact["reverie_meta"]["layers"] == [
        "defaults/common.yml",
        "dcs/dublin.yml",
        "roles/web.yml",
        "hosts/dublin/host1.yml",
    ]


def test_host_filed_in_wrong_layout_position_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("layered")
    wrong = source / "hosts" / "london"
    wrong.mkdir()
    (wrong / "host1.yml").write_text("dc: dublin\nrole: web\n", encoding="utf-8", newline="")
    (source / "hosts" / "dublin" / "host1.yml").unlink()
    (source / "hosts" / "dublin").rmdir()

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.host_layout_violation", host="host1")


def test_unknown_namespace_in_chain_template_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: ["teams/{{ layer.team }}.yml"]\ndefaults: defaults/common.yml\n',
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "configure.chain_template_unknown_namespace",
        file=str(source / "reverie.yml"),
        line=2,
    )


def test_nested_reference_in_chain_template_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: ["teams/{{ host.team.name }}.yml"]\ndefaults: defaults/common.yml\n',
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "configure.chain_template_nested_reference",
        file=str(source / "reverie.yml"),
        line=2,
    )


def test_illegal_expression_in_chain_template_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: ["teams/{{ host. }}.yml"]\ndefaults: defaults/common.yml\n',
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "configure.chain_template_illegal_expression",
        file=str(source / "reverie.yml"),
        line=2,
    )


def test_unbalanced_braces_in_chain_template_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: ["teams/{{ host.team }.yml"]\ndefaults: defaults/common.yml\n',
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "configure.chain_template_illegal_expression",
        file=str(source / "reverie.yml"),
        line=2,
    )
