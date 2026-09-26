"""Issue #48: RSOP records for the key paths a `deep_tuple` fold merges.

A record is keyed by an RSOP address (CONTEXT.md "RSOP address"): a key
path, with an *element selector* appended to any segment naming a list
whose elements a `deep_tuple` fold merged. The selector names the element
by its declared `tuple_keys`, so two element groups contributing the same
key address distinctly and neither depends on merge order.

The policy a record reports is still looked up by plain key path -- the
selector is addressing, never something a `merge:` pattern has to spell.
"""

from __future__ import annotations

import re

import yaml

from reverie.spec_registry import contributor_outcomes, rsop_vocabulary
from tests.conftest import run_reverie


class _RsopLoader(yaml.SafeLoader):
    """Reads the RSOP document as an unwitting reader sees it: the two
    surviving tags return their raw scalar content as a plain str."""


for _tag in ("!vault", "!secret"):
    _RsopLoader.add_constructor(_tag, lambda loader, node: loader.construct_scalar(node))


def _rsop(source, host: str = "host1") -> dict:
    result = run_reverie("rsop", str(source), host)
    assert result.returncode == 0, result.stderr
    return yaml.load(result.stdout, Loader=_RsopLoader)["rsop"]


def _with_merge(source, *lines: str) -> None:
    """Append policy lines to the fixture's own `merge:` block, which is
    its last -- the same seam `test_nested_policy_in_tuple_merge` uses."""

    config = source / "reverie.yml"
    config.write_text(
        config.read_text(encoding="utf-8") + "".join(f"  {line}\n" for line in lines),
        encoding="utf-8",
        newline="",
    )


def test_every_key_a_deep_tuple_fold_merges_gets_its_own_record(fixture_dir):
    source = fixture_dir("merge_lists")

    rsop = _rsop(source)

    # The "admins" element is contributed by all three layers, so the fold
    # visits each of its keys -- and each visit is a real merge decision
    # with its own contributors, addressed inside the element it happened in.
    assert rsop["groups[name=admins]/name"]["value"] == "admins"
    assert rsop["groups[name=admins]/perms"]["value"] == ["write"]
    assert rsop["groups[name=admins]/region"]["value"] == "dublin"

    perms = rsop["groups[name=admins]/perms"]
    # No policy is declared inside the list, so `perms` inherits the fold's
    # ambient `first`: a plain most-specific-wins contest between the two
    # layers that contributed one.
    assert perms["policy"] == {"strategy": "first", "pattern": None}
    assert perms["contributors"] == [
        {"layer": "dcs/dublin.yml", "value": ["write"], "outcome": "won"},
        {"layer": "defaults/common.yml", "value": ["read"], "outcome": "overridden"},
    ]

    # The list's own record is unchanged -- it still carries the whole
    # merged value, and the element records sit beside it, not inside it.
    assert rsop["groups"]["value"] == [
        {"name": "admins", "perms": ["write"], "region": "dublin"},
        {"name": "users", "perms": ["read"]},
    ]


def test_two_element_groups_contributing_the_same_key_do_not_collide(fixture_dir):
    source = fixture_dir("merge_lists")
    # dcs/dublin.yml now contributes to *both* of the floor's groups, so
    # both are folded and both fold a `perms` -- one key path, two merges.
    (source / "dcs" / "dublin.yml").write_text(
        "groups:\n"
        "  - name: admins\n"
        "    perms: [write]\n"
        "  - name: users\n"
        "    perms: [list]\n",
        encoding="utf-8",
        newline="",
    )

    rsop = _rsop(source)

    assert rsop["groups[name=admins]/perms"]["value"] == ["write"]
    assert rsop["groups[name=users]/perms"]["value"] == ["list"]
    assert [c["layer"] for c in rsop["groups[name=users]/perms"]["contributors"]] == [
        "dcs/dublin.yml",
        "defaults/common.yml",
    ]


def test_a_lone_element_is_never_folded_so_gains_no_records(fixture_dir):
    source = fixture_dir("merge_lists")

    rsop = _rsop(source)

    # "users" is the floor's alone: nothing matched it, so it survives whole
    # and no merge ever happens inside it -- exactly as `resolve` and
    # `validate` both already treat a group of one.
    assert "groups[name=users]/perms" not in rsop
    assert not [address for address in rsop if address.startswith("groups[name=users]")]


def test_a_unique_tuple_list_gains_no_element_records(fixture_dir):
    source = fixture_dir("merge_lists")

    rsop = _rsop(source)

    # `unique_tuple` keeps the more specific element whole, so nothing is
    # merged inside one and there is nothing to attribute.
    assert rsop["contacts"]["policy"]["strategy"] == "unique_tuple"
    assert not [address for address in rsop if address.startswith("contacts[")]


def test_a_record_inside_a_fold_reports_its_policy_by_plain_key_path(fixture_dir):
    source = fixture_dir("merge_lists")
    _with_merge(source, "groups/perms: append")

    rsop = _rsop(source)

    perms = rsop["groups[name=admins]/perms"]
    # Addressed per element, governed by the one pattern the author wrote:
    # a selector is never part of a `merge:` key path.
    assert perms["policy"] == {"strategy": "append", "pattern": "groups/perms"}
    assert perms["value"] == ["write", "read"]
    assert {c["outcome"] for c in perms["contributors"]} == {"merged"}


def test_a_selector_names_every_declared_tuple_key_in_declaration_order(fixture_dir):
    source = fixture_dir("merge_lists")
    _with_merge(source, "zones:", "  strategy: deep_tuple", "  tuple_keys: [name, enabled]")
    for layer, ttl in (("defaults/common.yml", 300), ("roles/web.yml", 600)):
        path = source / layer
        path.write_text(
            path.read_text(encoding="utf-8")
            + f"zones:\n  - name: core\n    enabled: true\n    ttl: {ttl}\n",
            encoding="utf-8",
            newline="",
        )

    rsop = _rsop(source)

    # Both keys, in the order `tuple_keys` declares them, and a boolean
    # rendered as YAML writes it rather than as Python spells it.
    assert rsop["zones[name=core,enabled=true]/ttl"]["value"] == 600


def test_a_nested_deep_tuple_fold_nests_its_selectors(fixture_dir):
    source = fixture_dir("merge_lists")
    _with_merge(source, "groups/subgroups:", "  strategy: deep_tuple", "  tuple_keys: [name]")
    for layer, quota in (("defaults/common.yml", 1), ("dcs/dublin.yml", 2)):
        path = source / layer
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "groups:\n  - name: admins\n",
                f"groups:\n  - name: admins\n    subgroups:\n      - name: sre\n        quota: {quota}\n",
                1,
            ),
            encoding="utf-8",
            newline="",
        )

    rsop = _rsop(source)

    assert rsop["groups[name=admins]/subgroups[name=sre]/quota"]["value"] == 2


def _address_pattern() -> re.Pattern[str]:
    """A parser for an RSOP address, built from the declared vocabulary
    rather than from a hand-copied literal.

    A selector value is either single-quoted (`''` escaping an inner
    quote) or a bare run carrying none of the delimiters -- exactly YAML's
    flow-scalar choice, which is what the vocabulary declares.
    """

    vocabulary = rsop_vocabulary()["element_selector"]
    open_, close = re.escape(vocabulary["open"]), re.escape(vocabulary["close"])
    assign, between = re.escape(vocabulary["assign"]), re.escape(vocabulary["between_keys"])
    separator = re.escape(vocabulary["also_quoted_when_containing"])

    quoted = r"'(?:[^']|'')*'"
    bare = f"(?:[^{open_}{close}{assign}{between}{separator}'])+"
    value = f"(?:(?:![a-z]+ )?(?:{quoted}|{bare}))"
    pair = f"{bare}{assign}{value}"
    selector = f"{open_}{pair}(?:{between}{pair})*{close}"
    segment = f"{bare}(?:{selector})?"
    return re.compile(f"{segment}(?:/{segment})*")


def test_every_address_and_outcome_round_trips_through_the_rsop_vocabulary(fixture_dir):
    source = fixture_dir("merge_lists")
    # Tuple keys holding every character the selector grammar reserves, so
    # the round trip is asserted against the hard cases and not just the
    # tidy ones: the two delimiters, the assignment, and the key-path
    # separator that YAML itself has no reason to quote.
    _with_merge(source, "zones:", "  strategy: deep_tuple", "  tuple_keys: [path]")
    for layer, ttl in (("defaults/common.yml", 300), ("roles/web.yml", 600)):
        path = source / layer
        path.write_text(
            path.read_text(encoding="utf-8")
            + f"zones:\n  - path: 'C:\\Shares\\a,b[x]=y'\n    ttl: {ttl}\n",
            encoding="utf-8",
            newline="",
        )
    address = _address_pattern()

    rsop = _rsop(source)

    assert rsop[r"zones[path='C:\Shares\a,b[x]=y']/ttl"]["value"] == 600
    for key, record in rsop.items():
        assert address.fullmatch(key), key
        for contributor in record["contributors"]:
            assert contributor["outcome"] in contributor_outcomes(), contributor
        if "redacted" in record:
            assert record["redacted"] in rsop_vocabulary()["redaction_reasons"]


def test_two_elements_differing_only_inside_a_quoted_tuple_key_stay_distinct(fixture_dir):
    source = fixture_dir("merge_lists")
    _with_merge(source, "zones:", "  strategy: deep_tuple", "  tuple_keys: [name]")
    # Were the delimiters not quoted, `a,b=c` and `a` + `b=c` would be one
    # address -- the collision acceptance forbids, reached by the grammar
    # rather than by luck.
    for layer, ttl in (("defaults/common.yml", 300), ("roles/web.yml", 600)):
        path = source / layer
        path.write_text(
            path.read_text(encoding="utf-8")
            + f"zones:\n  - name: 'a,b=c'\n    ttl: {ttl}\n  - name: a\n    ttl: {ttl}\n",
            encoding="utf-8",
            newline="",
        )

    rsop = _rsop(source)

    assert rsop["zones[name='a,b=c']/ttl"]["value"] == 600
    assert rsop["zones[name=a]/ttl"]["value"] == 600
