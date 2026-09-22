"""Issue #35: `!vault`-tagged scalars and the plaintext secret guardrail."""

from __future__ import annotations

import json

import yaml

from tests.conftest import assert_diagnostic, run_reverie


class _VaultAwareLoader(yaml.SafeLoader):
    """A plain YAML 1.1 loader (ADR 0008's target dialect) that also
    recognises `!vault`, returning its raw scalar content as a plain str
    -- exactly what an unwitting reader of the artifact sees."""


_VaultAwareLoader.add_constructor(
    "!vault", lambda loader, node: loader.construct_scalar(node)
)


def _load_artifact(path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_VaultAwareLoader)


def test_vault_scalar_passes_through_untouched(fixture_dir):
    source = fixture_dir("merge")
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\n"
        "nested: {a: {x: 99}, c: 3}\n"
        "port: !vault ENCRYPTED_BLOB_ONE\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact_text = (source / "host_vars" / "host1.yml").read_text(encoding="utf-8")
    assert "!vault 'ENCRYPTED_BLOB_ONE'" in artifact_text
    artifact = _load_artifact(source / "host_vars" / "host1.yml")
    assert artifact["reverie"]["port"] == "ENCRYPTED_BLOB_ONE"


def test_vault_scalar_merges_under_override(fixture_dir):
    # `first` (most-specific-wins) with no explicit policy at this path.
    source = fixture_dir("merge")
    (source / "defaults" / "common.yml").write_text(
        "env: prod\nsettings: {region: emea, timeout: 30}\nnested: {a: {x: 1}, b: 2}\n"
        "port: !vault GENERAL_SECRET\n",
        encoding="utf-8",
        newline="",
    )
    (source / "dcs" / "dublin.yml").write_text(
        "settings: {region: dublin-region}\nnested: {a: {y: 2}}\n"
        "port: !vault SPECIFIC_SECRET\n",
        encoding="utf-8",
        newline="",
    )
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = _load_artifact(source / "host_vars" / "host1.yml")
    assert artifact["reverie"]["port"] == "SPECIFIC_SECRET"


def test_vault_scalar_merges_under_deep(fixture_dir):
    source = fixture_dir("merge")
    (source / "reverie.yml").write_text(
        "layout: \"{{ host.dc }}\"\n"
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "roles/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  nested: deep\n",
        encoding="utf-8",
        newline="",
    )
    (source / "defaults" / "common.yml").write_text(
        "env: prod\nsettings: {region: emea, timeout: 30}\nnested: {secret: !vault GENERAL_SECRET, b: 2}\n"
        "port: 80\n",
        encoding="utf-8",
        newline="",
    )
    (source / "dcs" / "dublin.yml").write_text("settings: {region: dublin-region}\n", encoding="utf-8", newline="")
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {c: 3}\nport: 8080\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = _load_artifact(source / "host_vars" / "host1.yml")
    # `nested` deep-merges -- the untouched `secret` key from the defaults
    # floor survives alongside the more specific layers' other keys.
    assert artifact["reverie"]["nested"]["secret"] == "GENERAL_SECRET"


def test_vault_scalar_merges_under_append(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "dcs" / "dublin.yml").write_text(
        "members: [!vault SECRET_MEMBER]\ntags: [y, z]\n"
        "groups:\n"
        "  - name: admins\n"
        "    perms: [write]\n"
        "contacts:\n"
        "  - name: alice\n"
        "    role: sre\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    artifact = _load_artifact(source / "host_vars" / "host1.yml")
    assert "SECRET_MEMBER" in artifact["reverie"]["members"]


def test_vault_scalar_under_unique_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "dcs" / "dublin.yml").write_text("tags: [!vault SECRET_TAG, z]\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.secret_not_comparable", key_path="tags")


def test_vault_scalar_under_tuple_key_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge_lists")
    (source / "defaults" / "common.yml").write_text(
        "members: [alpha, beta]\ntags: [x, y]\nfeatures: [a, b]\n"
        "contacts:\n"
        "  - name: alice\n"
        "    role: eng\n"
        "  - name: bob\n"
        "    role: pm\n"
        "groups:\n"
        "  - name: !vault SECRET_NAME\n"
        "    perms: [read]\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.secret_not_comparable", key_path="groups")


def test_declared_secret_key_with_plaintext_value_is_a_validate_error(fixture_dir):
    source = fixture_dir("merge")
    (source / "reverie.yml").write_text(
        "layout: \"{{ host.dc }}\"\n"
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "roles/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n"
        "secrets:\n"
        "  - port\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "validate.secret_is_plaintext", layer=str(source / "defaults" / "common.yml"))


def test_declared_secret_key_checked_over_every_layer_not_just_the_winner(fixture_dir):
    # `port` wins from roles/web.yml (8080, plaintext) -- dcs/dublin.yml
    # never even declares `port`, so the only other plaintext contributor
    # is the defaults floor, a non-winning layer.
    source = fixture_dir("merge")
    (source / "reverie.yml").write_text(
        "layout: \"{{ host.dc }}\"\n"
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "roles/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n"
        "secrets:\n"
        "  - port\n",
        encoding="utf-8",
        newline="",
    )
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\nport: !vault WEB_SECRET\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    # The winning layer (roles/web.yml) is correctly `!vault`-tagged; only
    # the non-winning defaults floor's plaintext `port: 80` is flagged.
    assert_diagnostic(diagnostics, "validate.secret_is_plaintext", layer=str(source / "defaults" / "common.yml"))
    assert sum(1 for d in diagnostics if d["id"] == "validate.secret_is_plaintext") == 1


def test_secret_is_plaintext_diagnostic_never_carries_the_value(fixture_dir):
    source = fixture_dir("merge")
    (source / "reverie.yml").write_text(
        "layout: \"{{ host.dc }}\"\n"
        "chain:\n"
        '  - "dcs/{{ host.dc }}.yml"\n'
        '  - "roles/{{ host.role }}.yml"\n'
        "defaults: defaults/common.yml\n"
        "secrets:\n"
        "  - port\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    # assert_diagnostic asserts the field set matches the registry's
    # declared fields exactly -- `[layer]`, so a `value` field would fail.
    match = assert_diagnostic(diagnostics, "validate.secret_is_plaintext")
    assert "value" not in match


def test_whole_file_tagged_vault_is_rejected(fixture_dir):
    source = fixture_dir("merge")
    (source / "roles" / "web.yml").write_text(
        "!vault\nsettings: {timeout: 60}\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics,
        "load.value_out_of_domain",
        file=str(source / "roles" / "web.yml"),
        kind="vault_not_scalar",
    )
