"""Issue #61: `reverie.path_scan` -- the second named traversal of a host's
layer data, exercised directly against literal layer data as `test_keypath`,
`test_merge_plan` and `test_merge_walk` do for the other shared primitives.

What these cases pin is what the scan *sees*: every key path every layer
holds, winner or not, merged or not -- and the two places it deliberately
differs from the merge walk, being broader than it (a shadowed policy's
path still counts) and narrower inside a list (only a `deep_tuple` fold
gives an element's keys a key path).
"""

from __future__ import annotations

import pytest

from reverie import merge_walk, path_scan
from reverie.phases.configure import MergePolicy
from reverie.yaml_io import Remove
from tests.conftest import host_merges, loaded_host


def scan(*layers: dict, policies: list[MergePolicy] | None = None) -> list[path_scan.Entry]:
    return list(path_scan.scan(loaded_host(*layers), policies or []))


def paths(entries: list[path_scan.Entry]) -> list[str]:
    return [entry.key_path for entry in entries]


def test_every_key_of_one_layer_is_an_entry():
    entries = scan({"port": 8080, "role": "db"})

    assert paths(entries) == ["port", "role"]
    assert [entry.value for entry in entries] == [8080, "db"]


def test_a_map_is_descended_into_whatever_strategy_would_bind_there():
    # No policy, so the merge walk stops at `settings` under `first` -- the
    # scan keeps going, which is the whole point of it.
    entries = scan({"settings": {"a": 1}})

    assert paths(entries) == ["settings", "settings/a"]


def test_a_path_a_losing_layer_alone_holds_is_still_an_entry():
    entries = scan({"port": 8080}, {"port": 9090})

    assert [(entry.layer.address, entry.value) for entry in entries] == [
        ("layer0", 8080),
        ("layer1", 9090),
    ]


def test_layers_come_most_general_first_each_in_written_order():
    entries = scan({"a": 1}, {"b": 2, "a": 3})

    assert [(e.layer.address, e.key_path) for e in entries] == [
        ("layer0", "a"),
        ("layer1", "b"),
        ("layer1", "a"),
    ]


@pytest.mark.parametrize("strategy", ["append", "unique", "unique_tuple"])
def test_only_deep_tuple_gives_an_elements_keys_a_key_path(strategy):
    # Under every other list strategy the list itself is the deepest entry:
    # nothing is merged inside its elements, so their keys address nothing.
    policy = MergePolicy(pattern="groups", strategy=strategy, tuple_keys=("name",))
    entries = scan({"groups": [{"name": "admins", "shell": "zsh"}]}, policies=[policy])

    assert paths(entries) == ["groups"]


def test_a_deep_tuple_elements_keys_hang_from_the_lists_own_key_path():
    policy = MergePolicy(pattern="groups", strategy="deep_tuple", tuple_keys=("name",))
    entries = scan(
        {"groups": [{"name": "admins", "shell": "zsh"}]},
        policies=[policy],
    )

    assert paths(entries) == ["groups", "groups/name", "groups/shell"]


def test_one_layers_elements_pool_at_one_key_path_there_is_no_element_identity():
    # Per layer there is no cross-layer matching to do, so two elements'
    # keys land at the same path rather than being told apart.
    policy = MergePolicy(pattern="groups", strategy="deep_tuple", tuple_keys=("name",))
    entries = scan(
        {"groups": [{"name": "admins", "m": 1}, {"name": "users", "m": 2}]},
        policies=[policy],
    )

    assert paths(entries) == ["groups", "groups/name", "groups/m", "groups/name", "groups/m"]


def test_a_removed_element_contributes_a_match_and_nothing_inside_it():
    policy = MergePolicy(pattern="groups", strategy="deep_tuple", tuple_keys=("name",))
    entries = scan(
        {"groups": [Remove({"name": "admins", "shell": "zsh"})]},
        policies=[policy],
    )

    assert paths(entries) == ["groups"]


def test_a_removed_map_key_is_an_entry_carrying_the_remove_itself():
    entries = scan({"port": Remove(None)})

    [entry] = entries
    assert entry.key_path == "port"
    assert isinstance(entry.value, Remove)


def test_the_fold_rule_follows_the_policy_that_wins_the_key_path():
    # `groups` is matched by both; the more specific pattern decides, and
    # deciding it is `merge_plan`'s job, not the scan's.
    policies = [
        MergePolicy(pattern="**", strategy="append"),
        MergePolicy(pattern="groups", strategy="deep_tuple", tuple_keys=("name",)),
    ]
    entries = scan({"groups": [{"name": "admins"}]}, policies=policies)

    assert paths(entries) == ["groups", "groups/name"]


def test_values_pool_by_key_path_across_every_layer_in_scan_order():
    pooled = path_scan.values_by_key_path(scan({"port": 8080}, {"port": 9090, "role": "db"}))

    assert pooled == {"port": [8080, 9090], "role": ["db"]}


def test_the_scan_is_broader_than_the_walk_and_that_difference_is_contract():
    """A policy shadowed under an ancestor's `first` binds to nothing, so
    the walk never reaches its key path -- and `validate` must still report
    it as a strategy that never applies, not as a pattern matching nothing
    (see the module docstring). Only the scan can say the pattern was
    touched, which is why the two traversals stay separate."""

    policy = MergePolicy(pattern="settings/tags", strategy="append")
    layers = ({"settings": {"tags": ["a"]}}, {"settings": {"tags": ["b"]}})

    walked = merge_walk.merges(host_merges(*layers, policies=[policy]).merges)
    assert [merge.key_path for merge in walked] == ["settings"]

    assert "settings/tags" in paths(scan(*layers, policies=[policy]))
