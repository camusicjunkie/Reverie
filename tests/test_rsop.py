"""Issue #38: the `reverie rsop` verb -- per-host provenance document."""

from __future__ import annotations

import json

import pytest
import yaml

from reverie import merge_walk, rsop
from reverie.phases import resolve
from reverie.phases.configure import MergePolicy
from reverie.yaml_io import Remove
from tests.conftest import assert_diagnostic, loaded_host, run_reverie


class _TagAwareLoader(yaml.SafeLoader):
    """A plain YAML 1.1 loader that also recognises `!vault`/`!secret`,
    returning their raw scalar content as a plain str -- exactly what an
    unwitting reader of the RSOP document sees."""


_TagAwareLoader.add_constructor("!vault", lambda loader, node: loader.construct_scalar(node))
_TagAwareLoader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))


def _load_rsop(text: str) -> dict:
    return yaml.load(text, Loader=_TagAwareLoader)


def _run_rsop(source, host: str, *extra: str):
    result = run_reverie("rsop", str(source), host, *extra)
    return result


def test_rsop_document_covers_every_key_path_with_correct_values(fixture_dir):
    source = fixture_dir("merge")

    result = _run_rsop(source, "host1")

    assert result.returncode == 0, result.stderr
    document = _load_rsop(result.stdout)
    assert document["rsop_meta"]["host"] == "host1"
    rsop = document["rsop"]

    assert rsop["env"]["value"] == "prod"
    assert rsop["settings"]["value"] == {"region": "dublin-region", "timeout": 60}
    assert rsop["settings/region"]["value"] == "dublin-region"
    assert rsop["settings/timeout"]["value"] == 60
    assert rsop["nested"]["value"] == {"a": {"x": 99, "y": 2}, "b": 2, "c": 3}
    assert rsop["nested/a"]["value"] == {"x": 99, "y": 2}
    assert rsop["nested/a/x"]["value"] == 99
    assert rsop["nested/a/y"]["value"] == 2
    assert rsop["port"]["value"] == 8080
    assert rsop["dc"]["value"] == "dublin"
    assert rsop["role"]["value"] == "web"

    for record in rsop.values():
        assert sum(key in record for key in ("value", "redacted", "removed")) == 1


@pytest.mark.story(25)
def test_rsop_records_carry_policy_and_ordered_contributors(fixture_dir):
    source = fixture_dir("merge")

    result = _run_rsop(source, "host1")

    assert result.returncode == 0, result.stderr
    rsop = _load_rsop(result.stdout)["rsop"]

    settings = rsop["settings"]
    assert settings["policy"] == {"strategy": "shallow", "pattern": "settings"}
    assert [c["layer"] for c in settings["contributors"]] == [
        "roles/web.yml",
        "dcs/dublin.yml",
        "defaults/common.yml",
    ]
    assert {c["outcome"] for c in settings["contributors"]} == {"merged"}

    port = rsop["port"]
    assert port["policy"] == {"strategy": "first", "pattern": None}
    contributors_by_layer = {c["layer"]: c for c in port["contributors"]}
    assert contributors_by_layer["roles/web.yml"]["outcome"] == "won"
    assert contributors_by_layer["defaults/common.yml"]["outcome"] == "overridden"

    # nested/a/x: `deep` is ambient here (no explicit policy), but both
    # contributions are plain ints -- a shape mismatch falls back to
    # most-specific-wins, same as `resolve`.
    nested_a_x = rsop["nested/a/x"]
    assert nested_a_x["policy"] == {"strategy": "deep", "pattern": None}
    contributors_by_layer = {c["layer"]: c for c in nested_a_x["contributors"]}
    assert contributors_by_layer["roles/web.yml"]["outcome"] == "won"
    assert contributors_by_layer["defaults/common.yml"]["outcome"] == "overridden"


def test_rsop_list_strategies_merge_to_the_same_value_as_compile(fixture_dir):
    source = fixture_dir("merge_lists")

    result = _run_rsop(source, "host1")

    assert result.returncode == 0, result.stderr
    rsop = _load_rsop(result.stdout)["rsop"]

    assert rsop["members"]["value"] == ["delta", "gamma", "alpha", "beta"]
    assert rsop["members"]["policy"] == {"strategy": "append", "pattern": "members"}
    assert {c["outcome"] for c in rsop["members"]["contributors"]} == {"merged"}

    assert rsop["tags"]["value"] == ["z", "w", "y", "x"]

    assert rsop["groups"]["value"] == [
        {"name": "admins", "perms": ["write"], "region": "dublin"},
        {"name": "users", "perms": ["read"]},
    ]
    assert rsop["groups"]["policy"] == {"strategy": "deep_tuple", "pattern": "groups"}
    assert {c["outcome"] for c in rsop["groups"]["contributors"]} == {"merged"}

    assert rsop["contacts"]["value"] == [
        {"name": "carol", "role": "lead"},
        {"name": "alice", "role": "sre"},
        {"name": "bob", "role": "pm"},
    ]
    assert rsop["contacts"]["policy"] == {"strategy": "unique_tuple", "pattern": "contacts"}


def test_rsop_reports_a_key_removed_by_a_more_specific_layer(fixture_dir):
    source = fixture_dir("layered")
    (source / "roles" / "web.yml").write_text("region: !remove\nport: 80\n", encoding="utf-8", newline="")

    result = _run_rsop(source, "host1")

    assert result.returncode == 0, result.stderr
    rsop = _load_rsop(result.stdout)["rsop"]

    region = rsop["region"]
    assert region["removed"] is True
    assert "value" not in region
    contributors_by_layer = {c["layer"]: c for c in region["contributors"]}
    assert contributors_by_layer["roles/web.yml"]["outcome"] == "removed"
    assert contributors_by_layer["dcs/dublin.yml"]["outcome"] == "overridden"
    assert contributors_by_layer["dcs/dublin.yml"]["value"] == "emea"


@pytest.mark.story(26)
def test_rsop_redacts_vault_value_but_keeps_full_attribution(fixture_dir):
    source = fixture_dir("merge")
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\nport: !vault ENCRYPTED_BLOB\n",
        encoding="utf-8",
        newline="",
    )

    result = _run_rsop(source, "host1")

    assert result.returncode == 0, result.stderr
    assert "ENCRYPTED_BLOB" in result.stdout
    rsop = _load_rsop(result.stdout)["rsop"]

    port = rsop["port"]
    assert port["redacted"] == "vault"
    assert "value" not in port
    contributors_by_layer = {c["layer"]: c for c in port["contributors"]}
    assert contributors_by_layer["roles/web.yml"]["outcome"] == "won"
    assert contributors_by_layer["roles/web.yml"]["value"] == "ENCRYPTED_BLOB"


def test_rsop_shows_secret_address_in_full(fixture_dir):
    source = fixture_dir("merge")
    reverie_yml = source / "reverie.yml"
    reverie_yml.write_text(
        reverie_yml.read_text(encoding="utf-8")
        + "secret_backend:\n  lookup: community.hashi_vault.vault_kv2_get\n  options: {mount_point: secret}\n",
        encoding="utf-8",
        newline="",
    )
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\nnested: {a: {x: 99}, c: 3}\nport: !secret prod/svc#token\n",
        encoding="utf-8",
        newline="",
    )

    result = _run_rsop(source, "host1")

    assert result.returncode == 0, result.stderr
    rsop = _load_rsop(result.stdout)["rsop"]

    port = rsop["port"]
    assert port["value"] == "prod/svc#token"
    assert "redacted" not in port


def test_rsop_unknown_host_is_an_enumerate_error(fixture_dir):
    source = fixture_dir("merge")

    result = _run_rsop(source, "does-not-exist")

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.rsop_host_not_found")


def test_rsop_output_flag_matches_stdout_byte_for_byte_and_carries_no_header(fixture_dir, tmp_path):
    source = fixture_dir("merge")
    stdout_result = _run_rsop(source, "host1")
    assert stdout_result.returncode == 0, stdout_result.stderr

    out_path = tmp_path / "host1-rsop.yml"
    file_result = _run_rsop(source, "host1", "--output", str(out_path))

    assert file_result.returncode == 0, file_result.stderr
    written = out_path.read_bytes()
    assert written == stdout_result.stdout.encode("utf-8")
    assert not written.startswith(b"# Generated by Reverie")


@pytest.mark.story(27)
def test_rsop_output_inside_source_tree_is_a_configure_error(fixture_dir):
    source = fixture_dir("merge")

    result = _run_rsop(source, "host1", "--output", str(source / "rsop.yml"))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(
        diagnostics, "configure.rsop_output_in_estate", path=str(source / "rsop.yml"), tree=str(source)
    )


def test_rsop_output_with_missing_parent_directory_is_a_configure_error(fixture_dir, tmp_path):
    source = fixture_dir("merge")
    missing = tmp_path / "does-not-exist" / "rsop.yml"

    result = _run_rsop(source, "host1", "--output", str(missing))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "configure.rsop_output_parent_missing", path=str(missing))


@pytest.mark.story(28)
def test_rsop_works_without_compile_having_run(fixture_dir):
    source = fixture_dir("merge")

    assert not (source / "host_vars").exists()

    result = _run_rsop(source, "host1")

    assert result.returncode == 0, result.stderr
    assert not (source / "host_vars").exists()
    assert not (source / "inventory").exists()


# Issue #57: RSOP consumes `merge_walk` and keeps no traversal of its own,
# so coverage is no longer a promise this module makes and could break
# (issue #48) -- it is the walk's, by construction. These cases pin that
# construction in place: they are written against literal layer data rather
# than a fixture compile, because the claim is about the walk and the
# records standing in one-to-one correspondence, not about any one estate.


def _walk_and_records(*layers: dict, policies=None):
    host = loaded_host(*layers)
    policies = policies or []
    merges = list(merge_walk.merges(merge_walk.walk(host, policies)))
    return merges, rsop.compute_rsop(host, policies)


def test_every_merge_the_walk_yields_gets_exactly_one_record_and_no_others():
    merges, records = _walk_and_records(
        {"settings": {"region": "eu", "timeout": 30}, "port": 8080},
        {"settings": {"region": "us"}, "extra": [1, 2]},
        policies=[MergePolicy(pattern="settings", strategy="deep")],
    )

    assert len(records) == len(merges)
    assert set(records) == {rsop.render_address(merge.address) for merge in merges}


def test_a_fold_interior_is_covered_because_the_walk_reaches_it_not_because_rsop_looks():
    merges, records = _walk_and_records(
        {"groups": [{"name": "admins", "members": ["alice"]}]},
        {"groups": [{"name": "admins", "members": ["bob"]}]},
        policies=[MergePolicy(pattern="groups", strategy="deep_tuple", tuple_keys=["name"])],
    )

    assert "groups[name=admins]/members" in records
    assert len(records) == len(merges)


def test_a_records_value_is_the_value_resolve_would_emit_for_that_merge():
    merges, records = _walk_and_records(
        {"settings": {"region": "eu", "gone": 1}},
        {"settings": {"region": "us", "gone": Remove(None)}},
        policies=[MergePolicy(pattern="settings", strategy="deep")],
    )

    for merge in merges:
        record = records[rsop.render_address(merge.address)]
        value = resolve.merged_value(merge)
        if value is resolve.ABSENT:
            assert record["removed"] is True
            assert "value" not in record
        else:
            assert record["value"] == value
