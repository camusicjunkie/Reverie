"""Issue #37: inventory generation -- groups, ansible_host, and their
cross-checks against the chain and against `hosts/` itself."""

from __future__ import annotations

import json

import yaml

from tests.conftest import assert_diagnostic, run_reverie


def test_declared_group_facts_produce_one_group_per_distinct_value(fixture_dir):
    source = fixture_dir("inventory")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    inventory = yaml.safe_load((source / "inventory" / "hosts.yml").read_text(encoding="utf-8"))
    assert inventory == {
        "all": {
            "hosts": {
                "host1": {"ansible_host": "10.0.0.1"},
                "host2": {"ansible_host": "10.0.0.2"},
            },
            "children": {
                "env_prod": {"hosts": {"host1": None}},
                "env_staging": {"hosts": {"host2": None}},
                "svc_web": {"hosts": {"host1": None, "host2": None}},
            },
        }
    }
    assert not (source / "group_vars").exists()


def test_host_missing_declared_ansible_host_fact_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("inventory")
    (source / "hosts" / "host2.yml").write_text("env: staging\nrole: web\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.missing_ansible_host_fact")
    assert not (source / "inventory").exists()


def test_null_ansible_host_fact_is_treated_as_missing_not_stringified(fixture_dir):
    source = fixture_dir("inventory")
    (source / "hosts" / "host2.yml").write_text("env: staging\nrole: web\nip:\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.missing_ansible_host_fact")


def test_fact_value_that_is_not_a_legal_group_name_is_rejected(fixture_dir):
    source = fixture_dir("inventory")
    (source / "hosts" / "host1.yml").write_text("env: prod-1\nrole: web\nip: 10.0.0.1\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.illegal_group_name", host="host1", fact="env", value="prod-1")


def test_emitted_group_name_colliding_with_a_host_name_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("inventory")
    (source / "hosts" / "svc_web.yml").write_text("env: dev\nrole: web\nip: 10.0.0.3\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.group_host_name_collision")


def test_two_facts_producing_the_same_group_name_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("inventory")
    (source / "reverie.yml").write_text(
        "layout: \"\"\nchain: []\ndefaults: defaults/common.yml\n"
        "inventory:\n  groups:\n    - env\n    - fact: role\n      prefix: env_\n",
        encoding="utf-8",
        newline="",
    )
    (source / "hosts" / "host1.yml").write_text("env: prod\nrole: x\nip: 10.0.0.1\n", encoding="utf-8", newline="")
    (source / "hosts" / "host2.yml").write_text("env: y\nrole: prod\nip: 10.0.0.2\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.group_name_collision")


def test_declared_group_fact_with_zero_hosts_having_it_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("inventory")
    (source / "reverie.yml").write_text(
        "layout: \"\"\nchain: []\ndefaults: defaults/common.yml\n"
        "inventory:\n  ansible_host: ip\n  groups:\n    - env\n    - team\n"
        "    - fact: role\n      prefix: svc_\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.ungrounded_group_fact")


def test_chain_fact_never_declared_in_inventory_groups_warns_not_errors(fixture_dir):
    source = fixture_dir("layered")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    warnings = json.loads(result.stderr) if result.stderr else []
    assert any(w["id"] == "enumerate.undeclared_chain_fact" for w in warnings)
    assert (source / "host_vars" / "host1.yml").is_file()


def test_layout_only_fact_never_declared_in_inventory_groups_also_warns(fixture_dir):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(
        'layout: "{{ host.team }}"\nchain: []\ndefaults: defaults/common.yml\n', encoding="utf-8", newline=""
    )
    (source / "hosts" / "host1.yml").write_text("team: x\n", encoding="utf-8", newline="")
    (source / "hosts" / "x").mkdir()
    (source / "hosts" / "x" / "host1.yml").write_text("team: x\n", encoding="utf-8", newline="")
    (source / "hosts" / "host1.yml").unlink()

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    warnings = json.loads(result.stderr) if result.stderr else []
    assert any(w["id"] == "enumerate.undeclared_chain_fact" for w in warnings)
