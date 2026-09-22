"""Issue #36: `!secret <address>` and the backend contract."""

from __future__ import annotations

import json

import yaml

from tests.conftest import assert_diagnostic, run_reverie


def _add_secret_backend(source, lookup: str = "community.hashi_vault.vault_kv2_get", options: dict | None = None) -> None:
    reverie_yml = source / "reverie.yml"
    text = reverie_yml.read_text(encoding="utf-8")
    block = {"secret_backend": {"lookup": lookup, "options": options or {"mount_point": "secret"}}}
    reverie_yml.write_text(text + yaml.safe_dump(block, sort_keys=False), encoding="utf-8", newline="")


def _load_artifact(path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_secret_translates_to_backend_lookup_at_emit(fixture_dir):
    source = fixture_dir("merge")
    _add_secret_backend(source)
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\n"
        "nested: {a: {x: 99}, c: 3}\n"
        "port: !secret prod/domain-join#password\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = _load_artifact(source / "host_vars" / "host1.yml")
    port = artifact["reverie"]["port"]
    assert port.startswith("{{ lookup(")
    assert port.endswith(") }}")
    assert "community.hashi_vault.vault_kv2_get" in port
    assert "prod/domain-join#password" in port
    assert "mount_point='secret'" in port


def test_secret_address_never_appears_as_ciphertext_or_bare_plaintext(fixture_dir):
    source = fixture_dir("merge")
    _add_secret_backend(source)
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\nport: !secret prod/svc#token\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact_text = (source / "host_vars" / "host1.yml").read_text(encoding="utf-8")
    # The address appears only inside the deferred lookup() call, never as
    # a bare scalar value of its own.
    assert "port: '{{ lookup(" in artifact_text or 'port: "{{ lookup(' in artifact_text


def test_secret_addresses_merge_under_unique(fixture_dir):
    source = fixture_dir("merge_lists")
    _add_secret_backend(source)
    (source / "dcs" / "dublin.yml").write_text(
        "tags: [!secret store/a#x, z]\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = _load_artifact(source / "host_vars" / "host1.yml")
    tags = artifact["reverie"]["tags"]
    assert any("store/a#x" in tag for tag in tags if isinstance(tag, str))


def test_secret_addresses_merge_under_tuple_keys(fixture_dir):
    source = fixture_dir("merge_lists")
    _add_secret_backend(source)
    (source / "defaults" / "common.yml").write_text(
        "members: [alpha, beta]\ntags: [x, y]\nfeatures: [a, b]\n"
        "contacts:\n"
        "  - name: alice\n"
        "    role: eng\n"
        "groups:\n"
        "  - name: !secret store/group#name\n"
        "    perms: [read]\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    # A `!secret` address, unlike `!vault` ciphertext, is meaningfully
    # comparable -- so a tuple-key match against it is not a
    # `validate.secret_not_comparable` error.
    assert result.returncode == 0, result.stderr
    artifact = _load_artifact(source / "host_vars" / "host1.yml")
    names = [group["name"] for group in artifact["reverie"]["groups"]]
    assert any(isinstance(name, str) and "store/group#name" in name for name in names)


def test_secret_with_no_backend_declared_is_a_configure_error(fixture_dir):
    source = fixture_dir("merge")
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\nport: !secret prod/svc#token\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.no_secret_backend")


def test_secret_with_empty_address_is_a_load_error(fixture_dir):
    source = fixture_dir("merge")
    _add_secret_backend(source)
    (source / "roles" / "web.yml").write_text(
        'settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\nport: !secret ""\n',
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "load.empty_secret_address")


def test_bare_secret_tag_with_no_value_is_a_load_error(fixture_dir):
    source = fixture_dir("merge")
    _add_secret_backend(source)
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\nport: !secret\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "load.empty_secret_address")


def test_tag_other_than_closed_three_is_unknown_tag(fixture_dir):
    source = fixture_dir("merge")
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\nport: !store prod/svc#token\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "load.unknown_tag", tag="!store")


def test_declared_secret_key_accepts_secret_tag(fixture_dir):
    source = fixture_dir("merge")
    _add_secret_backend(source)
    (source / "reverie.yml").write_text(
        (source / "reverie.yml").read_text(encoding="utf-8") + "secrets:\n  - port\n",
        encoding="utf-8",
        newline="",
    )
    (source / "defaults" / "common.yml").write_text(
        "env: prod\nsettings: {region: emea, timeout: 30}\nnested: {a: {x: 1}, b: 2}\n"
        "port: !vault GENERAL_SECRET\n",
        encoding="utf-8",
        newline="",
    )
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\nport: !secret prod/svc#token\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
