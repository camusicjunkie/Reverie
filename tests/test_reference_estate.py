"""Issue #45: the reference estate -- the largest conformance case.

Eight invented hosts spread across two environments, two teams, two sites,
four roles and an optional tier layer, so the estate exercises realistic
composition rather than one isolated rule: a six-entry chain over a
defaults floor, a non-empty layout, merge policies at four specificities
over two subtrees, both flavours of list-of-maps merge, `!remove` of both
a map key and a list element (one of them from a host file's own data, so
the estate covers issue #46), `!vault` and `!secret` under a declared
`secrets:` path, a policy addressed inside a `deep_tuple`-merged element
(issue #47), deferred Jinja riding through inert, and inventory grouping
over six facts.

A passing case throughout -- it asserts no diagnostics, so the registry's
fixture-coverage check is untouched.
"""

from __future__ import annotations

import yaml

from tests.conftest import run_reverie

HOSTS = [
    "del-da-db02",
    "del-pl-pull01",
    "pat-da-db01",
    "pat-pl-dhcp01",
    "pat-pl-fs01",
    "stg-da-db01",
    "stg-pl-dhcp01",
    "stg-pl-fs01",
]

# The floor's `!vault` scalar, as a plain reader of the artifact sees it.
ADMIN_PASSWORD = "ADMIN_CIPHERTEXT"

# The floor's `!secret` address, as emit translates it for the declared backend.
JOIN_PASSWORD = (
    "{{ lookup('community.hashi_vault.vault_kv2_get', "
    "'estate/domain-join#password', mount_point='secret') }}"
)

# Deferred Jinja inside a data value -- inert literal text, never parsed.
CREDENTIAL = "{{ reverie.domain_admin_password }}"
DESCRIPTION = "{{ reverie.role }} in {{ reverie.env }}"

ESTATE_WIDE = {
    "domain_fqdn": "reverie.test",
    "domain_admin_password": ADMIN_PASSWORD,
    "domain_join_password": JOIN_PASSWORD,
    "description": DESCRIPTION,
    "baseline": "server",
}

EXPECTED = {
    "pat-pl-fs01": {
        **ESTATE_WIDE,
        "env": "production",
        "team": "platforms",
        "site": "patch",
        "role": "fileserver",
        "tier": "core",
        "addr": "10.20.0.11",
        "monitoring": "prometheus",
        "syslog_target": "logs.patch.reverie.test",
        "admin_users": ["svc_oncall", "svc_platforms", "svc_baseline"],
        "windows_features": ["FS-DFS-Namespace", "FS-Resource-Manager", "NET-Framework-45-Core"],
        "tagging": {"owner": "platforms", "policy_version": "2.0", "tier": "core"},
        "computer_settings": {
            "audit": True,
            "monitoring_agent": "full",
            "patch_window": "sunday-0200",
            "time_zone": "W. Europe Standard Time",
        },
        "files_and_folders": {
            "items": [
                {"path": "C:\\Shares", "type": "directory"},
                {"path": "C:\\Estate\\production", "type": "directory"},
                {"path": "C:\\Estate", "type": "directory"},
            ]
        },
        # `local_groups/groups/members` is declared `append` *inside* the
        # elements `deep_tuple` folds together, so the role's membership
        # accumulates onto the floor's rather than replacing it -- while
        # `credential`, undeclared, is a plain most-specific-wins contest.
        "local_groups": {
            "groups": [
                {
                    "name": "Administrators",
                    "members": ["SG-FileServer-Admins", "SG-Estate-Admins"],
                    "credential": CREDENTIAL,
                },
                {"name": "Backup Operators", "members": ["SG-Backup-Operators"]},
            ]
        },
    },
    # No `tier` fact at all: the optional chain entry is skipped, so nothing
    # contributes `tagging/tier` or `computer_settings/monitoring_agent`.
    "pat-pl-dhcp01": {
        **ESTATE_WIDE,
        "env": "production",
        "team": "platforms",
        "site": "patch",
        "role": "dhcp",
        "addr": "10.20.0.12",
        "monitoring": "prometheus",
        "syslog_target": "logs.patch.reverie.test",
        "admin_users": ["svc_platforms", "svc_baseline"],
        "windows_features": ["DHCP", "NET-Framework-45-Core"],
        "tagging": {"owner": "platforms", "policy_version": "2.0"},
        "computer_settings": {
            "audit": True,
            "dhcp_authorized": True,
            "patch_window": "sunday-0200",
            "time_zone": "W. Europe Standard Time",
        },
        "files_and_folders": {
            "items": [
                {"path": "C:\\Estate\\production", "type": "directory"},
                {"path": "C:\\Estate", "type": "directory"},
            ]
        },
        "local_groups": {
            "groups": [
                {
                    "name": "Administrators",
                    "members": ["SG-Estate-Admins"],
                    "credential": CREDENTIAL,
                }
            ]
        },
    },
    # A deldin host: `syslog_target` is `!remove`d at the site layer, so the
    # floor's estate-wide value resolves away entirely.
    "del-pl-pull01": {
        **ESTATE_WIDE,
        "env": "production",
        "team": "platforms",
        "site": "deldin",
        "role": "pullserver",
        "tier": "core",
        "addr": "10.20.1.13",
        "monitoring": "prometheus",
        "admin_users": ["svc_oncall", "svc_platforms", "svc_baseline"],
        # The host file's own `!remove` takes the console feature back out
        # of what its role layer installs (issue #46).
        "windows_features": ["Web-Server", "NET-Framework-45-Core"],
        "tagging": {"owner": "platforms", "policy_version": "2.0", "tier": "core"},
        "computer_settings": {
            "audit": True,
            "monitoring_agent": "full",
            "patch_window": "sunday-0200",
            "time_zone": "GMT Standard Time",
        },
        "files_and_folders": {
            "items": [
                {"path": "C:\\inetpub\\wwwroot", "type": "directory"},
                {"path": "C:\\Estate\\production", "type": "directory"},
                {"path": "C:\\Estate", "type": "directory"},
            ]
        },
        "local_groups": {
            "groups": [
                {
                    "name": "Administrators",
                    "members": ["SG-Estate-Admins"],
                    "credential": CREDENTIAL,
                }
            ]
        },
    },
    "pat-da-db01": {
        **ESTATE_WIDE,
        "env": "production",
        "team": "data",
        "site": "patch",
        "role": "database",
        "tier": "core",
        "addr": "10.20.0.21",
        "monitoring": "prometheus",
        "syslog_target": "logs.patch.reverie.test",
        "admin_users": ["svc_oncall", "svc_dba", "svc_data", "svc_baseline"],
        # The role restates the floor's own prerequisite: `unique` keeps one.
        "windows_features": ["NET-Framework-45-Core", "NET-WCF-TCP-PortSharing45"],
        "tagging": {"owner": "data", "policy_version": "2.0", "tier": "core"},
        "computer_settings": {
            "audit": True,
            "monitoring_agent": "full",
            "patch_window": "sunday-0200",
            "time_zone": "W. Europe Standard Time",
        },
        # `C:\Estate` matched the floor's element on `path` under
        # `unique_tuple`, so the role's whole element survives -- `acl` and
        # all -- and the floor's is dropped rather than folded in.
        "files_and_folders": {
            "items": [
                {"path": "C:\\Data", "type": "directory"},
                {"path": "C:\\Estate", "type": "directory", "acl": "dba"},
                {"path": "C:\\Estate\\production", "type": "directory"},
            ]
        },
        "local_groups": {
            "groups": [
                {
                    "name": "Administrators",
                    "members": ["SG-DBA-Admins", "SG-Data-Admins", "SG-Estate-Admins"],
                    "credential": CREDENTIAL,
                }
            ]
        },
    },
    "del-da-db02": {
        **ESTATE_WIDE,
        "env": "production",
        "team": "data",
        "site": "deldin",
        "role": "database",
        "addr": "10.20.1.22",
        "monitoring": "prometheus",
        "admin_users": ["svc_dba", "svc_data", "svc_baseline"],
        "windows_features": ["NET-Framework-45-Core", "NET-WCF-TCP-PortSharing45"],
        "tagging": {"owner": "data", "policy_version": "2.0"},
        "computer_settings": {
            "audit": True,
            "patch_window": "sunday-0200",
            "time_zone": "GMT Standard Time",
        },
        "files_and_folders": {
            "items": [
                {"path": "C:\\Data", "type": "directory"},
                {"path": "C:\\Estate", "type": "directory", "acl": "dba"},
                {"path": "C:\\Estate\\production", "type": "directory"},
            ]
        },
        "local_groups": {
            "groups": [
                {
                    "name": "Administrators",
                    "members": ["SG-DBA-Admins", "SG-Data-Admins", "SG-Estate-Admins"],
                    "credential": CREDENTIAL,
                }
            ]
        },
    },
    # An edge-tier host: the tier layer `!remove`s the floor's framework
    # feature, so it leaves `windows_features` rather than being overridden.
    "stg-pl-fs01": {
        **ESTATE_WIDE,
        "env": "staging",
        "team": "platforms",
        "site": "deldin",
        "role": "fileserver",
        "tier": "edge",
        "addr": "10.30.1.11",
        "monitoring": "none",
        "admin_users": ["svc_platforms", "svc_baseline"],
        "windows_features": ["FS-DFS-Namespace", "FS-Resource-Manager"],
        "tagging": {"owner": "platforms", "policy_version": "2.0", "tier": "edge"},
        "computer_settings": {
            "audit": True,
            "monitoring_agent": "light",
            "patch_window": "daily-0100",
            "time_zone": "GMT Standard Time",
        },
        "files_and_folders": {
            "items": [
                {"path": "C:\\Shares", "type": "directory"},
                {"path": "C:\\Estate\\staging", "type": "directory"},
                {"path": "C:\\Estate", "type": "directory"},
            ]
        },
        "local_groups": {
            "groups": [
                {
                    "name": "Administrators",
                    "members": ["SG-FileServer-Admins", "SG-Estate-Admins"],
                    "credential": CREDENTIAL,
                },
                {"name": "Backup Operators", "members": ["SG-Backup-Operators"]},
            ]
        },
    },
    "stg-pl-dhcp01": {
        **ESTATE_WIDE,
        "env": "staging",
        "team": "platforms",
        "site": "patch",
        "role": "dhcp",
        "tier": "edge",
        "addr": "10.30.0.12",
        "monitoring": "none",
        "syslog_target": "logs.patch.reverie.test",
        "admin_users": ["svc_platforms", "svc_baseline"],
        "windows_features": ["DHCP"],
        "tagging": {"owner": "platforms", "policy_version": "2.0", "tier": "edge"},
        "computer_settings": {
            "audit": True,
            "dhcp_authorized": True,
            "monitoring_agent": "light",
            "patch_window": "daily-0100",
            "time_zone": "W. Europe Standard Time",
        },
        "files_and_folders": {
            "items": [
                {"path": "C:\\Estate\\staging", "type": "directory"},
                {"path": "C:\\Estate", "type": "directory"},
            ]
        },
        "local_groups": {
            "groups": [
                {
                    "name": "Administrators",
                    "members": ["SG-Estate-Admins"],
                    "credential": CREDENTIAL,
                }
            ]
        },
    },
    # No tier: the floor's framework feature is never removed here, so the
    # same role resolves differently than it does on an edge-tier host.
    "stg-da-db01": {
        **ESTATE_WIDE,
        "env": "staging",
        "team": "data",
        "site": "patch",
        "role": "database",
        "addr": "10.30.0.21",
        "monitoring": "none",
        "syslog_target": "logs.patch.reverie.test",
        "admin_users": ["svc_dba", "svc_data", "svc_baseline"],
        "windows_features": ["NET-Framework-45-Core", "NET-WCF-TCP-PortSharing45"],
        "tagging": {"owner": "data", "policy_version": "2.0"},
        "computer_settings": {
            "audit": True,
            "patch_window": "daily-0100",
            "time_zone": "W. Europe Standard Time",
        },
        "files_and_folders": {
            "items": [
                {"path": "C:\\Data", "type": "directory"},
                {"path": "C:\\Estate", "type": "directory", "acl": "dba"},
                {"path": "C:\\Estate\\staging", "type": "directory"},
            ]
        },
        "local_groups": {
            "groups": [
                {
                    "name": "Administrators",
                    "members": ["SG-DBA-Admins", "SG-Data-Admins", "SG-Estate-Admins"],
                    "credential": CREDENTIAL,
                }
            ]
        },
    },
}

EXPECTED_INVENTORY = {
    "all": {
        "hosts": {
            "del-da-db02": {"ansible_host": "10.20.1.22"},
            "del-pl-pull01": {"ansible_host": "10.20.1.13"},
            "pat-da-db01": {"ansible_host": "10.20.0.21"},
            "pat-pl-dhcp01": {"ansible_host": "10.20.0.12"},
            "pat-pl-fs01": {"ansible_host": "10.20.0.11"},
            "stg-da-db01": {"ansible_host": "10.30.0.21"},
            "stg-pl-dhcp01": {"ansible_host": "10.30.0.12"},
            "stg-pl-fs01": {"ansible_host": "10.30.1.11"},
        },
        "children": {
            "env_production": {
                "hosts": {
                    "del-da-db02": None,
                    "del-pl-pull01": None,
                    "pat-da-db01": None,
                    "pat-pl-dhcp01": None,
                    "pat-pl-fs01": None,
                }
            },
            "env_staging": {
                "hosts": {"stg-da-db01": None, "stg-pl-dhcp01": None, "stg-pl-fs01": None}
            },
            "team_platforms": {
                "hosts": {
                    "del-pl-pull01": None,
                    "pat-pl-dhcp01": None,
                    "pat-pl-fs01": None,
                    "stg-pl-dhcp01": None,
                    "stg-pl-fs01": None,
                }
            },
            "team_data": {
                "hosts": {"del-da-db02": None, "pat-da-db01": None, "stg-da-db01": None}
            },
            "site_patch": {
                "hosts": {
                    "pat-da-db01": None,
                    "pat-pl-dhcp01": None,
                    "pat-pl-fs01": None,
                    "stg-da-db01": None,
                    "stg-pl-dhcp01": None,
                }
            },
            "site_deldin": {
                "hosts": {"del-da-db02": None, "del-pl-pull01": None, "stg-pl-fs01": None}
            },
            # The one declared `prefix:` -- `role` groups as `svc_<value>`
            # rather than the default `<fact>_<value>`.
            "svc_fileserver": {"hosts": {"pat-pl-fs01": None, "stg-pl-fs01": None}},
            "svc_dhcp": {"hosts": {"pat-pl-dhcp01": None, "stg-pl-dhcp01": None}},
            "svc_pullserver": {"hosts": {"del-pl-pull01": None}},
            "svc_database": {
                "hosts": {"del-da-db02": None, "pat-da-db01": None, "stg-da-db01": None}
            },
            # Three hosts carry no `tier` fact at all, so they join neither
            # tier group -- an optional layer's absence is visible here too.
            "tier_core": {
                "hosts": {"del-pl-pull01": None, "pat-da-db01": None, "pat-pl-fs01": None}
            },
            "tier_edge": {"hosts": {"stg-pl-dhcp01": None, "stg-pl-fs01": None}},
            "baseline_server": {"hosts": {host: None for host in HOSTS}},
        },
    }
}


class _TagAwareLoader(yaml.SafeLoader):
    """A plain YAML 1.1 loader that also recognises `!vault`, returning its
    raw scalar content as a plain str -- exactly what an unwitting reader
    of the artifact sees. `!secret` needs no constructor: emit translates
    every address to a `lookup()` call, so no `!secret` tag survives."""


_TagAwareLoader.add_constructor("!vault", lambda loader, node: loader.construct_scalar(node))


class _RsopLoader(_TagAwareLoader):
    """`!secret` addresses do survive into the RSOP document (unredacted,
    since they're addresses), so reading one needs a constructor the
    artifact loader doesn't."""


_RsopLoader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))


def _load(path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_TagAwareLoader)


def _load_rsop(text: str) -> dict:
    return yaml.load(text, Loader=_RsopLoader)["rsop"]


def _compiled(fixture_dir):
    source = fixture_dir("reference_estate")
    result = run_reverie("compile", str(source))
    assert result.returncode == 0, result.stderr
    return source


def test_estate_compiles_to_one_artifact_per_host_plus_an_inventory(fixture_dir):
    source = _compiled(fixture_dir)

    assert sorted(p.name for p in (source / "host_vars").iterdir()) == [f"{host}.yml" for host in HOSTS]
    assert sorted(p.name for p in (source / "inventory").iterdir()) == ["hosts.yml"]


def test_every_host_resolves_to_its_full_expected_data(fixture_dir):
    source = _compiled(fixture_dir)

    for host in HOSTS:
        artifact = _load(source / "host_vars" / f"{host}.yml")
        assert artifact["reverie"] == EXPECTED[host], host


def test_every_artifact_records_the_layers_its_host_walked(fixture_dir):
    source = _compiled(fixture_dir)

    # The optional tier entry is the only chain slot a host may skip, so
    # the walked-layer list is eight long with a tier and seven without.
    assert _load(source / "host_vars" / "pat-pl-fs01.yml")["reverie_meta"]["layers"] == [
        "defaults/common.yml",
        "teams/platforms.yml",
        "envs/production.yml",
        "sites/patch.yml",
        "roles/fileserver.yml",
        "tiers/core.yml",
        "baselines/server.yml",
        "hosts/production/platforms/pat-pl-fs01.yml",
    ]
    assert _load(source / "host_vars" / "pat-pl-dhcp01.yml")["reverie_meta"]["layers"] == [
        "defaults/common.yml",
        "teams/platforms.yml",
        "envs/production.yml",
        "sites/patch.yml",
        "roles/dhcp.yml",
        "baselines/server.yml",
        "hosts/production/platforms/pat-pl-dhcp01.yml",
    ]


def test_inventory_groups_membership_and_ansible_host(fixture_dir):
    source = _compiled(fixture_dir)

    inventory = _load(source / "inventory" / "hosts.yml")

    assert inventory == EXPECTED_INVENTORY
    assert not (source / "group_vars").exists()


def test_recompiling_the_same_estate_is_byte_identical(fixture_dir):
    source = _compiled(fixture_dir)
    generated = sorted((source / "host_vars").iterdir()) + sorted((source / "inventory").iterdir())
    before = {path.name: path.read_bytes() for path in generated}

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    after = {path.name: path.read_bytes() for path in generated}
    assert after == before


def test_rsop_attributes_every_contributor_to_a_multi_layer_merge(fixture_dir):
    source = _compiled(fixture_dir)

    result = run_reverie("rsop", str(source), "pat-pl-fs01")

    assert result.returncode == 0, result.stderr
    rsop = _load_rsop(result.stdout)

    # `tagging` is contributed by four layers and merged by all four.
    tagging = rsop["tagging"]
    assert tagging["policy"] == {"strategy": "shallow", "pattern": "tagging"}
    assert tagging["contributors"] == [
        {"layer": "baselines/server.yml", "value": {"policy_version": "2.0"}, "outcome": "merged"},
        {"layer": "tiers/core.yml", "value": {"tier": "core"}, "outcome": "merged"},
        {"layer": "teams/platforms.yml", "value": {"owner": "platforms"}, "outcome": "merged"},
        {
            "layer": "defaults/common.yml",
            "value": {"owner": "estate", "policy_version": "1.0"},
            "outcome": "merged",
        },
    ]

    # Under that `shallow`, each child key is a plain most-specific-wins
    # contest -- and the two contests have different winners.
    assert rsop["tagging/owner"]["contributors"] == [
        {"layer": "teams/platforms.yml", "value": "platforms", "outcome": "won"},
        {"layer": "defaults/common.yml", "value": "estate", "outcome": "overridden"},
    ]
    assert rsop["tagging/policy_version"]["contributors"] == [
        {"layer": "baselines/server.yml", "value": "2.0", "outcome": "won"},
        {"layer": "defaults/common.yml", "value": "1.0", "outcome": "overridden"},
    ]

    # A list-of-maps merge reports the same way, and its value matches what
    # `compile` emitted for the same host.
    groups = rsop["local_groups/groups"]
    assert groups["policy"] == {"strategy": "deep_tuple", "pattern": "local_groups/groups"}
    assert [c["layer"] for c in groups["contributors"]] == [
        "baselines/server.yml",
        "roles/fileserver.yml",
        "defaults/common.yml",
    ]
    assert {c["outcome"] for c in groups["contributors"]} == {"merged"}
    assert groups["value"] == EXPECTED["pat-pl-fs01"]["local_groups"]["groups"]

    # And the merges the `deep_tuple` fold performs *inside* that list get
    # their own records, addressed by the element they happened in rather
    # than pooled onto the list's own path (issue #48). This is the record
    # that explains why the Administrators group's membership accumulated.
    administrators = EXPECTED["pat-pl-fs01"]["local_groups"]["groups"][0]
    members = rsop["local_groups/groups[name=Administrators]/members"]
    assert members["policy"] == {"strategy": "append", "pattern": "local_groups/groups/members"}
    assert members["value"] == administrators["members"]
    assert members["contributors"] == [
        {"layer": "roles/fileserver.yml", "value": ["SG-FileServer-Admins"], "outcome": "merged"},
        {"layer": "defaults/common.yml", "value": ["SG-Estate-Admins"], "outcome": "merged"},
    ]

    # `credential`, undeclared, is a plain contest inside the same element --
    # and the baseline is its only contributor.
    credential = rsop["local_groups/groups[name=Administrators]/credential"]
    assert credential["value"] == administrators["credential"]
    assert credential["contributors"] == [
        {"layer": "baselines/server.yml", "value": CREDENTIAL, "outcome": "won"},
    ]

    # "Backup Operators" is the role's alone: a group of one is never
    # folded, so nothing inside it is merged and nothing is attributed.
    assert not [address for address in rsop if address.startswith("local_groups/groups[name=Backup")]

    # `files_and_folders/items` is `unique_tuple` -- the kept element
    # survives whole, so its interior is never a merge either.
    assert not [address for address in rsop if address.startswith("files_and_folders/items[")]


def test_rsop_reports_both_flavours_of_removal(fixture_dir):
    source = _compiled(fixture_dir)

    # A map key removed at the site layer.
    result = run_reverie("rsop", str(source), "del-pl-pull01")
    assert result.returncode == 0, result.stderr
    syslog = _load_rsop(result.stdout)["syslog_target"]
    assert syslog["removed"] is True
    assert "value" not in syslog
    assert syslog["contributors"] == [
        {"layer": "sites/deldin.yml", "value": None, "outcome": "removed"},
        {"layer": "defaults/common.yml", "value": "logs.reverie.test", "outcome": "overridden"},
    ]

    # A list element removed at the tier layer: the key survives, one of
    # its elements doesn't.
    result = run_reverie("rsop", str(source), "stg-pl-fs01")
    assert result.returncode == 0, result.stderr
    features = _load_rsop(result.stdout)["windows_features"]
    assert features["value"] == ["FS-DFS-Namespace", "FS-Resource-Manager"]
    contributors_by_layer = {c["layer"]: c for c in features["contributors"]}
    assert contributors_by_layer["tiers/edge.yml"]["value"] == ["NET-Framework-45-Core"]
    assert contributors_by_layer["defaults/common.yml"]["value"] == ["NET-Framework-45-Core"]


def test_rsop_redacts_the_vault_value_but_shows_the_secret_address(fixture_dir):
    source = _compiled(fixture_dir)

    result = run_reverie("rsop", str(source), "pat-da-db01")

    assert result.returncode == 0, result.stderr
    rsop = _load_rsop(result.stdout)

    admin_password = rsop["domain_admin_password"]
    assert admin_password["redacted"] == "vault"
    assert "value" not in admin_password

    # An address, not material -- shown in full, and never as the backend
    # call the artifact carries.
    join_password = rsop["domain_join_password"]
    assert join_password["value"] == "estate/domain-join#password"
    assert "redacted" not in join_password
