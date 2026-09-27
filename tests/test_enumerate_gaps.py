"""Issue #43: the remaining `enumerate.*` closed-list conditions."""

from __future__ import annotations

import json

import pytest
import yaml

from tests.conftest import assert_diagnostic, run_reverie


def test_non_scalar_fact_in_a_chain_template_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("layered")
    (source / "hosts" / "dublin" / "host1.yml").write_text(
        "dc: dublin\nrole:\n  - web\n  - api\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.non_scalar_fact", host="host1", key_path="role")


def test_fact_value_carrying_a_separator_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("layered")
    (source / "hosts" / "dublin" / "host1.yml").write_text(
        "dc: dublin\nrole: web/frontend\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.illegal_fact_value", host="host1", key_path="role")


def test_fact_value_of_a_relative_path_token_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("layered")
    (source / "hosts" / "dublin" / "host1.yml").write_text(
        'dc: dublin\nrole: ".."\n', encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.illegal_fact_value", host="host1", key_path="role")


def test_chain_address_climbing_out_of_the_root_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("layered")
    (source / "reverie.yml").write_text(
        'layout: "{{ host.dc }}"\n'
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "../elsewhere/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "enumerate.address_escapes_root",
        host="host1",
        pattern="../elsewhere/{{ host.role }}.yml",
    )


def test_host_walking_no_layers_at_all_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text('layout: ""\nchain: []\n', encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.host_walks_no_layers", host="host1")


def test_a_defaults_floor_alone_is_enough_to_walk(fixture_dir):
    # The floor counts as a layer beneath the host -- `chain: []` plus a
    # floor is a legitimate, if minimal, hierarchy.
    source = fixture_dir("minimal")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr


@pytest.mark.story(32)
def test_a_layer_file_no_chain_ever_addresses_is_legitimate(fixture_dir):
    """Issue #51, user story 32 -- the permissive half of the asymmetry.

    An addressed-but-missing layer file is always an error; a layer file
    nothing addresses is normal, because pre-provisioning a site ahead of
    its first host is legitimate. The error half is covered above, and
    `enumerate.orphan_layer_file` sits in the deleted-ids list -- but that
    guards the *id*, not the behaviour, so the permissive half is stated
    here directly.
    """

    source = fixture_dir("layered")
    clean = run_reverie("compile", str(source))
    assert clean.returncode == 0, clean.stderr

    (source / "dcs" / "paris.yml").write_text("region: elsewhere\n", encoding="utf-8", newline="")
    (source / "roles" / "database.yml").write_text("port: 5432\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    # Byte-identical to the run without them, artifact and diagnostics
    # both: the orphans provoke no error, no warning of their own, and
    # contribute nothing to the host that walked past them. (This estate
    # already warns about undeclared chain facts -- the point is that the
    # orphans add nothing to what it already said.)
    assert result.stderr == clean.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    assert artifact["reverie"] == {"dc": "dublin", "role": "web", "env": "prod", "region": "emea", "port": 80}
