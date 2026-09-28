"""Issue #53: `reverie.merge_walk` -- the one traversal every consumer of a
host's merges shares, exercised directly against literal layer data rather
than through a full compile (as `test_keypath` and `test_merge_plan` do for
the other two shared primitives).

What these cases pin is the *order and shape* of the stream: which merges a
host performs, at which key path, under which ambient strategy, filed at
which RSOP address, and from which layer each contribution came. What the
merges resolve *to* is `resolve`'s business and is asserted through the
conformance fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reverie import merge_plan, merge_walk
from reverie.phases.configure import MergePolicy
from reverie.phases.enumerate import LayerRef
from reverie.phases.load import LoadedHost
from reverie.yaml_io import Remove


def host(*layers: dict) -> LoadedHost:
    """A loaded host over `layers`, most general first, addressed `layer0`..."""

    return LoadedHost(
        name="h1",
        layers=[
            (LayerRef(address=f"layer{index}", path=Path(f"layer{index}.yml")), data)
            for index, data in enumerate(layers)
        ],
    )


def walk(*layers: dict, policies: list[MergePolicy] | None = None) -> list[merge_walk.Merge]:
    """Every merge the host performs, flattened in the order it performs them."""

    return list(merge_walk.merges(merge_walk.walk(host(*layers), policies or [])))


def paths(merges: list[merge_walk.Merge]) -> list[str]:
    return [merge.key_path for merge in merges]


def test_a_host_with_one_layer_still_merges_every_key_it_touches():
    merges = walk({"port": 8080, "role": "db"})

    assert paths(merges) == ["port", "role"]
    assert [merge.kind for merge in merges] == [merge_walk.MOST_SPECIFIC_WINS] * 2


def test_keys_come_in_first_contribution_order_across_layers():
    merges = walk({"a": 1, "b": 2}, {"b": 3, "c": 4})

    assert paths(merges) == ["a", "b", "c"]


def test_a_merge_carries_the_layer_behind_each_contribution():
    [merge] = walk({"port": 8080}, {"port": 9090})

    assert [(c.layer.address, c.value) for c in merge.contributions] == [
        ("layer0", 8080),
        ("layer1", 9090),
    ]
    assert merge.effective == merge.contributions


def test_a_remove_clears_the_more_general_contributions_it_reaches():
    [merge] = walk({"port": 8080}, {"port": Remove(None)})

    assert merge.kind == merge_walk.REMOVED
    assert merge.effective == ()
    # The cleared contribution is still on the merge -- RSOP attributes it.
    assert [c.layer.address for c in merge.contributions] == ["layer0", "layer1"]


def test_an_unmerged_map_is_a_leaf_nothing_recurses_into():
    merges = walk({"settings": {"a": 1}}, {"settings": {"b": 2}})

    assert paths(merges) == ["settings"]
    assert merges[0].kind == merge_walk.MOST_SPECIFIC_WINS


def test_a_map_strategy_recurses_into_its_children():
    policy = MergePolicy(pattern="settings", strategy="shallow")
    merges = walk({"settings": {"a": 1}}, {"settings": {"b": 2}}, policies=[policy])

    assert paths(merges) == ["settings", "settings/a", "settings/b"]
    assert merges[0].kind == merge_walk.MAP
    # `shallow`'s children inherit `first`, so they are leaves themselves.
    assert [merge.decision.strategy for merge in merges[1:]] == ["first", "first"]


def test_deep_propagates_itself_down_the_whole_subtree():
    policy = MergePolicy(pattern="settings", strategy="deep")
    merges = walk(
        {"settings": {"nested": {"a": 1}}},
        {"settings": {"nested": {"b": 2}}},
        policies=[policy],
    )

    assert paths(merges) == ["settings", "settings/nested", "settings/nested/a", "settings/nested/b"]
    assert [merge.decision.strategy for merge in merges[:2]] == ["deep", "deep"]


def test_a_map_strategy_meeting_a_non_map_recurses_into_nothing():
    policy = MergePolicy(pattern="settings", strategy="deep")
    merges = walk({"settings": {"a": 1}}, {"settings": "scalar"}, policies=[policy])

    assert paths(merges) == ["settings"]
    assert merges[0].kind == merge_walk.MOST_SPECIFIC_WINS
    assert merges[0].decision.shape == merge_plan.MISMATCH


def test_a_plain_list_strategy_yields_one_element_per_group_and_merges_nothing_inside():
    policy = MergePolicy(pattern="tags", strategy="append")
    [merge] = walk({"tags": ["a"]}, {"tags": ["b"]}, policies=[policy])

    assert merge.kind == merge_walk.LIST
    assert [[c.value for c in element.contributions] for element in merge.elements] == [["b"], ["a"]]
    assert all(element.interior == () for element in merge.elements)
    assert all(element.selector is None for element in merge.elements)


def test_a_deep_tuple_fold_merges_a_matched_group_at_the_lists_own_key_path():
    policy = MergePolicy(pattern="groups", strategy="deep_tuple", tuple_keys=("name",))
    merges = walk(
        {"groups": [{"name": "admins", "members": ["a"]}]},
        {"groups": [{"name": "admins", "members": ["b"]}]},
        policies=[policy],
    )

    assert paths(merges) == ["groups", "groups/name", "groups/members"]
    assert merges[0].kind == merge_walk.LIST
    # The fold is a map merge under ambient `first`, group most-general-first.
    assert [c.value for c in merges[2].contributions] == [["a"], ["b"]]
    assert merges[2].decision.strategy == "first"


def test_a_group_of_one_is_never_merged_so_nothing_inside_it_is_walked():
    policy = MergePolicy(pattern="groups", strategy="deep_tuple", tuple_keys=("name",))
    merges = walk(
        {"groups": [{"name": "admins", "members": ["a"]}]},
        {"groups": [{"name": "users", "members": ["b"]}]},
        policies=[policy],
    )

    assert paths(merges) == ["groups"]
    assert [element.interior for element in merges[0].elements] == [(), ()]


def test_a_fold_interior_is_addressed_by_element_selector_not_by_key_path_alone():
    policy = MergePolicy(pattern="groups", strategy="deep_tuple", tuple_keys=("name",))
    merges = walk(
        {"groups": [{"name": "admins", "m": 1}, {"name": "users", "m": 2}]},
        {"groups": [{"name": "admins", "m": 3}, {"name": "users", "m": 4}]},
        policies=[policy],
    )

    # Two groups contribute the same key path; only the address tells them apart.
    assert paths(merges) == ["groups", "groups/name", "groups/m", "groups/name", "groups/m"]
    selectors = [step for merge in merges for step in merge.address if not isinstance(step, str)]
    assert [(s.tuple_keys, s.element["name"]) for s in selectors] == [
        (("name",), "admins"),
        (("name",), "admins"),
        (("name",), "users"),
        (("name",), "users"),
    ]
    assert [merge.address[0] for merge in merges] == ["groups"] * 5


def test_a_nested_policy_inside_a_fold_binds_at_the_lists_key_path():
    policies = [
        MergePolicy(pattern="groups", strategy="deep_tuple", tuple_keys=("name",)),
        MergePolicy(pattern="groups/members", strategy="append"),
    ]
    merges = walk(
        {"groups": [{"name": "admins", "members": ["a"]}]},
        {"groups": [{"name": "admins", "members": ["b"]}]},
        policies=policies,
    )

    members = next(merge for merge in merges if merge.key_path == "groups/members")
    assert members.decision.strategy == "append"
    assert members.kind == merge_walk.LIST


def test_every_merge_names_the_key_it_merges():
    policy = MergePolicy(pattern="settings", strategy="deep")
    merges = walk({"settings": {"nested": {"a": 1}}}, policies=[policy])

    assert [merge.key for merge in merges] == ["settings", "nested", "a"]


def test_the_stream_is_pre_order_every_merge_before_the_merges_beneath_it():
    policy = MergePolicy(pattern="**", strategy="deep")
    merges = walk({"a": {"b": {"c": 1}}, "d": {"e": 2}}, policies=[policy])

    assert paths(merges) == ["a", "a/b", "a/b/c", "d", "d/e"]


@pytest.mark.parametrize("strategy", ["unique", "unique_tuple"])
def test_only_deep_tuple_ever_walks_inside_an_element(strategy):
    policy = MergePolicy(pattern="groups", strategy=strategy, tuple_keys=("name",))
    [merge] = walk(
        {"groups": [{"name": "admins", "m": 1}]},
        {"groups": [{"name": "admins", "m": 2}]},
        policies=[policy],
    )

    assert merge.kind == merge_walk.LIST
    # `unique` compares whole elements, so these two never even match --
    # but under either strategy nothing beneath an element is merged.
    assert all(element.interior == () for element in merge.elements)
    assert all(element.selector is None for element in merge.elements)
