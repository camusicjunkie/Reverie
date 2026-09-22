"""Issue #40: `reverie.merge_plan.bind` -- the one binding decision shared
between `resolve` (executes it) and `validate` (inspects it), exercised
directly against literal inputs rather than through a full compile."""

from __future__ import annotations

from reverie import merge_plan
from reverie.phases.configure import MergePolicy
from reverie.yaml_io import Remove


def test_no_declared_policy_falls_back_to_the_ambient_strategy():
    decision = merge_plan.bind("port", [8080, 9090], merge_policies=[], ambient_strategy="first")

    assert decision.policy is None
    assert decision.strategy == "first"
    assert decision.applied is True
    assert decision.shape == merge_plan.MISMATCH
    assert decision.effective == [8080, 9090]


def test_declared_policy_wins_over_the_ambient_strategy():
    policy = MergePolicy(pattern="settings", strategy="shallow")
    decision = merge_plan.bind(
        "settings", [{"a": 1}, {"b": 2}], merge_policies=[policy], ambient_strategy="deep"
    )

    assert decision.policy is policy
    assert decision.strategy == "shallow"
    assert decision.shape == merge_plan.MAP
    assert decision.applied is True
    # `shallow`'s children fall back to `first`, not `shallow` itself.
    assert decision.children_ambient == "first"


def test_deep_strategy_propagates_itself_to_children():
    policy = MergePolicy(pattern="nested", strategy="deep")
    decision = merge_plan.bind(
        "nested", [{"a": 1}, {"b": 2}], merge_policies=[policy], ambient_strategy="first"
    )

    assert decision.children_ambient == "deep"


def test_map_strategy_against_non_map_values_falls_back_to_most_specific_wins():
    policy = MergePolicy(pattern="port", strategy="deep")
    decision = merge_plan.bind("port", [80, 8080], merge_policies=[policy], ambient_strategy="first")

    assert decision.strategy == "deep"
    assert decision.shape == merge_plan.MISMATCH
    assert decision.applied is False
    # A mismatch never propagates the declared strategy to children.
    assert decision.children_ambient == "first"


def test_list_strategy_against_a_scalar_shape_mismatches():
    policy = MergePolicy(pattern="dc", strategy="unique")
    decision = merge_plan.bind("dc", ["dublin", "paris"], merge_policies=[policy], ambient_strategy="first")

    assert decision.shape == merge_plan.MISMATCH
    assert decision.applied is False


def test_list_strategy_shape_splits_plain_from_list_of_maps():
    policy = MergePolicy(pattern="tags", strategy="unique")
    plain = merge_plan.bind("tags", [["a"], ["b"]], merge_policies=[policy], ambient_strategy="first")
    assert plain.shape == merge_plan.LIST_PLAIN
    assert plain.applied is True

    of_maps = merge_plan.bind(
        "groups",
        [[{"name": "a"}], [{"name": "b"}]],
        merge_policies=[MergePolicy(pattern="groups", strategy="unique_tuple", tuple_keys=("name",))],
        ambient_strategy="first",
    )
    assert of_maps.shape == merge_plan.LIST_OF_MAPS
    assert of_maps.applied is True


def test_all_contributions_removed_binds_to_absent():
    decision = merge_plan.bind(
        "port", [Remove(80), Remove(9090)], merge_policies=[], ambient_strategy="first"
    )

    assert decision.shape == merge_plan.ABSENT
    assert decision.applied is False
    assert decision.effective == []


def test_a_later_remove_clears_earlier_contributions_but_not_a_still_later_value():
    decision = merge_plan.bind(
        "port", [80, Remove(80), 9090], merge_policies=[], ambient_strategy="first"
    )

    assert decision.shape != merge_plan.ABSENT
    assert decision.effective == [9090]


def test_bind_never_raises_on_a_malformed_declaration():
    # `bind` has no diagnostics of its own to raise (ADR 0009) -- a
    # strategy string outside the closed set would be a `configure`-phase
    # concern, never reachable here, but `bind` still shouldn't choke on
    # arbitrary input since it never validates the policy it's handed.
    policy = MergePolicy(pattern="x", strategy="deep")
    decision = merge_plan.bind("x", [], merge_policies=[policy], ambient_strategy="first")

    assert decision.shape == merge_plan.ABSENT
    assert decision.applied is False
