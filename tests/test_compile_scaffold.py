"""Issue #30: the compile scaffold tracer bullet.

Drives the real `reverie compile` CLI through the process boundary against
real fixture directories on disk -- the one seam every later ticket's
tests reuse.
"""

from __future__ import annotations

import json

import yaml

from tests.conftest import assert_diagnostic, run_reverie


def test_minimal_compile_produces_artifact_and_inventory(fixture_dir):
    source = fixture_dir("minimal")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    assert (source / "host_vars" / "host1.yml").is_file()
    assert (source / "inventory" / "hosts.yml").is_file()


def test_artifact_loads_to_expected_typed_values(fixture_dir):
    source = fixture_dir("minimal")
    run_reverie("compile", str(source))

    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))

    assert artifact["reverie"] == {"site": "dublin"}
    assert isinstance(artifact["reverie"]["site"], str)
    meta = artifact["reverie_meta"]
    assert meta["compiler_version"] == "0.1.0"
    assert meta["spec_version"] == "1"
    assert meta["source_digest"].startswith("sha256:")
    assert meta["layers"] == ["defaults/common.yml", "hosts/host1.yml"]
    assert "timestamp" not in json.dumps(meta)

    inventory = yaml.safe_load((source / "inventory" / "hosts.yml").read_text(encoding="utf-8"))
    assert inventory == {"all": {"hosts": {"host1": None}}}


def test_compile_is_byte_for_byte_reproducible(fixture_dir):
    source = fixture_dir("minimal")

    run_reverie("compile", str(source))
    first = (source / "host_vars" / "host1.yml").read_bytes()
    first_inventory = (source / "inventory" / "hosts.yml").read_bytes()

    result = run_reverie("compile", str(source))
    second = (source / "host_vars" / "host1.yml").read_bytes()
    second_inventory = (source / "inventory" / "hosts.yml").read_bytes()

    assert result.returncode == 0, result.stderr
    assert first == second
    assert first_inventory == second_inventory


def test_timestamp_value_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "defaults" / "common.yml").write_text("site: dublin\nstamp: 2024-01-01\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "load.value_out_of_domain", kind="timestamp")
    assert not (source / "host_vars").exists()


def test_nan_value_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "defaults" / "common.yml").write_text("site: dublin\nratio: .nan\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "load.value_out_of_domain", kind="nan_or_infinity")


def test_unmanaged_file_in_output_directory_is_error_not_deleted(fixture_dir):
    source = fixture_dir("minimal")
    host_vars_dir = source / "host_vars"
    host_vars_dir.mkdir()
    hand_authored = host_vars_dir / "host1.yml"
    hand_authored.write_text("hand-authored content\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "emit.foreign_file", file=str(hand_authored))
    assert hand_authored.read_text(encoding="utf-8") == "hand-authored content\n"
    assert not (source / "inventory").exists()


def test_directory_in_owned_directory_is_error_not_ignored(fixture_dir):
    source = fixture_dir("minimal")
    host_vars_dir = source / "host_vars"
    host_vars_dir.mkdir()
    stray_dir = host_vars_dir / "stray"
    stray_dir.mkdir()

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "emit.foreign_file", file=str(stray_dir))
    assert stray_dir.is_dir()


def test_missing_chain_fact_is_distinct_from_missing_layer_file(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: ["teams/{{ host.team }}.yml"]\ndefaults: defaults/common.yml\n',
        encoding="utf-8",
        newline="",
    )
    # hosts/host1.yml declares no "team" fact.

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.missing_host_fact", fact="team")
    assert not any(d["id"] == "enumerate.missing_layer_file" for d in diagnostics)


def test_missing_layer_file_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: ""\nchain: ["teams/none.yml"]\ndefaults: defaults/common.yml\n',
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "enumerate.missing_layer_file",
        host="host1",
        chain_entry="teams/none.yml",
        rendered_address="teams/none.yml",
    )


def test_malformed_yaml_syntax_in_a_layer_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "defaults" / "common.yml").write_text("site: [\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "load.invalid_yaml", file=str(source / "defaults" / "common.yml"))


def test_non_map_layer_document_is_a_load_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "defaults" / "common.yml").write_text("- a\n- b\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "load.document_not_a_map", file=str(source / "defaults" / "common.yml"), line=None)


def test_recompile_after_fixing_failure_matches_fresh_compile(fixture_dir):
    broken = fixture_dir("minimal")
    (broken / "defaults" / "common.yml").write_text("site: dublin\nstamp: 2024-01-01\n", encoding="utf-8", newline="")
    failed = run_reverie("compile", str(broken))
    assert failed.returncode != 0

    (broken / "defaults" / "common.yml").write_text("site: dublin\n", encoding="utf-8", newline="")
    fixed = run_reverie("compile", str(broken))
    assert fixed.returncode == 0, fixed.stderr

    clean = fixture_dir("minimal")
    fresh = run_reverie("compile", str(clean))
    assert fresh.returncode == 0, fresh.stderr

    assert (broken / "host_vars" / "host1.yml").read_bytes() == (clean / "host_vars" / "host1.yml").read_bytes()


def test_missing_source_argument_is_a_configure_error(fixture_dir):
    result = run_reverie("compile")

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.missing_source_argument")


def test_missing_reverie_yml_is_a_configure_error(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = run_reverie("compile", str(empty_dir))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.reverie_yml_not_found", file=str(empty_dir / "reverie.yml"))


def test_malformed_yaml_syntax_in_reverie_yml_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text("layout: [\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.malformed_reverie_yml", file=str(source / "reverie.yml"))


def test_non_map_reverie_yml_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text("- not\n- a\n- map\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "configure.malformed_reverie_yml",
        file=str(source / "reverie.yml"),
        detail="expected a mapping at the document root",
    )


def test_malformed_layout_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text('layout: "/leading-slash"\nchain: []\ndefaults: defaults/common.yml\n', encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.malformed_layout", file=str(source / "reverie.yml"), layout="/leading-slash")


def test_malformed_chain_entry_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text('layout: ""\nchain: [123]\ndefaults: defaults/common.yml\n', encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.malformed_chain_entry", file=str(source / "reverie.yml"), entry=123)


def test_malformed_defaults_is_a_configure_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text('layout: ""\nchain: []\ndefaults: 123\n', encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.malformed_defaults", file=str(source / "reverie.yml"), defaults=123)
