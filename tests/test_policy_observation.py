"""Issue #56: one declared merge policy's verdict, as one thing.

`validate` judges a policy by what the shared merge walk was seen to do
with it. These cases drive `PolicyObservation` directly -- feeding it the
merges a small host performs, exactly as `validate` does -- and assert the
conditions it reports, including the precedence between them. That
precedence is contract: it used to live in the `elif` ordering of a
five-branch cascade a screen away from the evidence it read.
"""

from __future__ import annotations

from reverie import merge_walk
from reverie.phases import validate
from reverie.phases.configure import MergePolicy
from tests.conftest import host_merges


def observed(policy: MergePolicy, *layers: dict, matched: bool = True) -> validate.PolicyObservation:
    """The observation `validate` would build for `policy` over one host.

    `matched` stands in for the raw per-layer path scan, which answers
    "does any layer touch this pattern at all" and is deliberately broader
    than the merges the walk performs.
    """

    observation = validate.PolicyObservation(policy=policy)
    if matched:
        observation.saw_path_match()
    for merge in merge_walk.merges(host_merges(*layers, policies=[policy]).merges):
        if merge.decision.policy is policy:
            observation.saw_merge(merge)
    return observation


def ids(observation: validate.PolicyObservation) -> list[str]:
    return [id for id, _fields in observation.conditions()]


def test_a_pattern_no_layer_touches_reports_only_that():
    policy = MergePolicy(pattern="nowhere/**", strategy="deep")
    observation = observed(policy, {"users": {"a": 1}}, matched=False)

    assert ids(observation) == ["validate.pattern_matches_nothing"]


def test_a_matched_pattern_reports_its_pattern_with_the_diagnostic():
    policy = MergePolicy(pattern="nowhere/**", strategy="deep")
    conditions = dict(observed(policy, {"users": {"a": 1}}, matched=False).conditions())

    assert conditions["validate.pattern_matches_nothing"] == {"pattern": "nowhere/**"}


def test_a_map_strategy_that_wins_against_a_map_reports_nothing():
    policy = MergePolicy(pattern="users", strategy="deep")
    observation = observed(policy, {"users": {"a": 1}}, {"users": {"b": 2}})

    assert ids(observation) == []


def test_a_map_strategy_that_never_meets_a_map_never_applies():
    policy = MergePolicy(pattern="users", strategy="deep")
    observation = observed(policy, {"users": [1, 2]})

    assert ids(observation) == ["validate.strategy_never_applies"]


def test_a_plain_list_strategy_meeting_only_list_of_maps_never_applies():
    """`append`/`unique` bind to a list of maps -- the merge runs -- but that
    is not the shape the policy was declared for, and it reports as such."""

    policy = MergePolicy(pattern="rules", strategy="unique")
    observation = observed(policy, {"rules": [{"name": "a"}]})

    assert ids(observation) == ["validate.strategy_never_applies"]


def test_a_tuple_strategy_meeting_only_a_plain_list_reports_the_specific_fault():
    """The tuple exemption: `non_map_in_tuple_merge` is the finding, and it
    displaces `strategy_never_applies` rather than joining it."""

    policy = MergePolicy(pattern="ports", strategy="deep_tuple", tuple_keys=("name",))
    observation = observed(policy, {"ports": [80, 443]})

    assert ids(observation) == ["validate.non_map_in_tuple_merge"]


def test_a_tuple_strategy_folding_maps_that_lack_a_declared_key():
    policy = MergePolicy(pattern="rules", strategy="deep_tuple", tuple_keys=("name",))
    observation = observed(policy, {"rules": [{"port": 80}]}, {"rules": [{"name": "web"}]})

    assert ids(observation) == ["validate.missing_tuple_key"]


def test_a_tuple_strategy_that_folds_cleanly_reports_nothing():
    policy = MergePolicy(pattern="rules", strategy="deep_tuple", tuple_keys=("name",))
    observation = observed(
        policy, {"rules": [{"name": "web", "port": 80}]}, {"rules": [{"name": "web", "tls": True}]}
    )

    assert ids(observation) == []


def test_first_is_total_so_it_never_reports_a_strategy_that_never_applies():
    policy = MergePolicy(pattern="port", strategy="first")
    observation = observed(policy, {"port": 8080})

    assert ids(observation) == []


def test_a_vault_comparison_is_reported_beside_the_verdict_it_does_not_displace():
    policy = MergePolicy(pattern="rules", strategy="unique")
    observation = observed(policy, {"rules": [{"name": "a"}]})
    observation.saw_vault_comparison()

    assert ids(observation) == ["validate.secret_not_comparable", "validate.strategy_never_applies"]
    assert dict(observation.conditions())["validate.secret_not_comparable"] == {"key_path": "rules"}
