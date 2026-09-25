"""Issue #46: one of Reverie's own tags in a host file costs only itself.

A host file is a layer like any other, so it may carry `!remove`,
`!vault`, or `!secret`. `enumerate` reads a host's facts through a
deliberately permissive parse that runs before `load`, and that parse used
to be a plain `yaml.safe_load` -- so any tag anywhere in the file threw
away *every* fact on it and buried the real fault under a cascade of
`enumerate.missing_host_fact`.

The settled behaviour, asserted here:

- A tagged value no chain entry or layout references is none of
  enumerate's business; every other fact on the file stays available.
- A tagged value a chain or layout template *does* reference has no
  segment to render, so it reports `enumerate.non_scalar_fact` -- the
  same condition a map- or list-valued fact reports, alone, with no
  cascade beside it.
- A tagged value `inventory:` references is treated as absent, the way a
  null-valued fact already is: no group is keyed on it, and an
  `ansible_host` fact reports `enumerate.missing_ansible_host_fact`.
- A host file that genuinely can't be parsed still yields no facts, and
  now says so exactly once, as `load.invalid_yaml`.

The reference estate covers the passing `!remove` case end to end; these
are the focused cases, and the diagnostics.
"""

from __future__ import annotations

import json

import yaml

from tests.conftest import assert_diagnostic, run_reverie


class _VaultLoader(yaml.SafeLoader):
    """Reads an artifact's `!vault` scalar back as its raw text."""


_VaultLoader.add_constructor("!vault", lambda loader, node: loader.construct_scalar(node))


def _artifact(path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_VaultLoader)


def test_a_tagged_fact_no_template_references_leaves_every_other_fact_readable(fixture_dir):
    source = fixture_dir("layered")
    (source / "hosts" / "dublin" / "host1.yml").write_text(
        "dc: dublin\nrole: web\nlocal_admin_password: !vault ENCRYPTED\n",
        encoding="utf-8",
        newline="",
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    # `dc` and `role` both still routed: the host walked its full chain.
    artifact = _artifact(source / "host_vars" / "host1.yml")
    assert artifact["reverie_meta"]["layers"] == [
        "defaults/common.yml",
        "dcs/dublin.yml",
        "roles/web.yml",
        "hosts/dublin/host1.yml",
    ]
    assert artifact["reverie"]["local_admin_password"] == "ENCRYPTED"


def test_a_chain_template_pointing_at_a_tagged_fact_reports_one_condition(fixture_dir):
    source = fixture_dir("layered")
    (source / "hosts" / "dublin" / "host1.yml").write_text(
        "dc: dublin\nrole: !vault ENCRYPTED\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.non_scalar_fact", host="host1", key_path="role")
    # The one fault, not a cascade: `dc` rendered fine and says nothing.
    assert len(diagnostics) == 1, diagnostics


def test_a_layout_template_pointing_at_a_tagged_fact_reports_the_same_condition(fixture_dir):
    source = fixture_dir("layered")
    (source / "reverie.yml").write_text(
        'layout: "{{ host.dc }}"\nchain: []\ndefaults: defaults/common.yml\n',
        encoding="utf-8",
        newline="",
    )
    (source / "hosts" / "dublin" / "host1.yml").write_text(
        "dc: !secret estate/dc#name\nrole: web\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.non_scalar_fact", host="host1", key_path="dc")
    # Reported once, and never as a layout violation: nothing was rendered
    # to compare the host's position against.
    assert len(diagnostics) == 1, diagnostics


def test_a_removal_tag_on_a_routing_fact_is_unusable_the_same_way(fixture_dir):
    # `!remove` is a match marker, not a value -- as unusable in a path
    # segment as the two opaque tags, and reported identically.
    source = fixture_dir("layered")
    (source / "hosts" / "dublin" / "host1.yml").write_text(
        "dc: dublin\nrole: !remove web\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.non_scalar_fact", host="host1", key_path="role")
    assert len(diagnostics) == 1, diagnostics


def test_a_tagged_ansible_host_fact_is_absent_rather_than_stringified(fixture_dir):
    source = fixture_dir("inventory")
    (source / "hosts" / "host1.yml").write_text(
        "env: prod\nrole: web\nip: !vault ENCRYPTED\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    assert_diagnostic(diagnostics, "enumerate.missing_ansible_host_fact")
    assert len(diagnostics) == 1, diagnostics


def test_a_tagged_group_fact_keys_no_group(fixture_dir):
    source = fixture_dir("inventory")
    (source / "hosts" / "host1.yml").write_text(
        "env: !vault ENCRYPTED\nrole: web\nip: 10.0.0.1\n", encoding="utf-8", newline=""
    )

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    inventory = yaml.safe_load((source / "inventory" / "hosts.yml").read_text(encoding="utf-8"))
    children = inventory["all"]["children"]
    # No `env_ENCRYPTED`, and no group at all for host1's env -- the fact
    # stays grounded by host2, and host1 keeps every other membership.
    assert sorted(children) == ["env_staging", "svc_web"]
    assert children["env_staging"]["hosts"] == {"host2": None}
    assert children["svc_web"]["hosts"] == {"host1": None, "host2": None}
    assert inventory["all"]["hosts"]["host1"] == {"ansible_host": "10.0.0.1"}


def test_an_unparseable_host_file_reports_only_the_parse_failure(fixture_dir):
    source = fixture_dir("layered")
    host_file = source / "hosts" / "dublin" / "host1.yml"
    host_file.write_text("dc: [dublin\nrole: web\n", encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0
    diagnostics = json.loads(result.stderr)
    # `enumerate` stays silent about a file it couldn't read, so the fault
    # a reader sees is the parse failure rather than six facts reported
    # missing from a file that declares them.
    assert_diagnostic(diagnostics, "load.invalid_yaml", file=str(host_file))
    assert len(diagnostics) == 1, diagnostics
