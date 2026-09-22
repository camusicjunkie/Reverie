"""The one binding decision `resolve` and `validate` each need for a key
path (issue #40): which policy wins, what strategy is actually in effect
(including ambient-strategy inheritance), whether the contributing values'
shape matches that strategy, and whether the strategy therefore applied.

Previously this question was answered twice, independently: `resolve`
computed it to execute the merge, and `validate` computed a cruder version
of it -- via raw key-path text flattened across every host -- to check for
policies that never actually bind. Flattening across hosts meant a policy
that mis-shapes on only one host in a multi-host estate was invisible,
since another host's correctly-shaped contribution would mask it.

This module answers the question and nothing more: it never raises (every
error condition stays scoped to exactly one phase, per ADR 0009), and it
never executes a merge -- `resolve` still owns turning `effective` into a
merged value, `validate` still owns turning a decision into a diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reverie import keypath, list_merge
from reverie.phases.configure import MergePolicy
from reverie.yaml_io import Remove

MAP_STRATEGIES = ("shallow", "deep")

# Shape verdicts. "absent" means every contribution was `!remove`d away --
# there is nothing left to bind a strategy to at all.
ABSENT = "absent"
MAP = "map"
LIST_PLAIN = "list_plain"
LIST_OF_MAPS = "list_of_maps"
MISMATCH = "mismatch"


@dataclass(frozen=True)
class BindingDecision:
    key_path: str
    policy: MergePolicy | None
    strategy: str
    shape: str
    applied: bool
    # Non-`!remove` contributions, most-general to most-specific -- what a
    # caller merges (resolve) or recurses into (validate) next.
    effective: list[Any]
    # The ambient strategy this key path's children inherit, per
    # CONTEXT.md "Strategy": `deep` propagates itself, everything else
    # (including a mismatched `deep`) falls back to `first`.
    children_ambient: str


def bind(
    key_path: str,
    contributions: list[Any],
    merge_policies: list[MergePolicy],
    ambient_strategy: str,
) -> BindingDecision:
    """The binding decision for one key path, given its per-layer
    contributions (general to specific, `!remove` included)."""

    effective: list[Any] = []
    for value in contributions:
        if isinstance(value, Remove):
            effective = []
        else:
            effective.append(value)

    policy = keypath.winner(merge_policies, key_path)
    strategy = policy.strategy if policy else ambient_strategy

    if not effective:
        shape = ABSENT
    elif all(isinstance(v, dict) for v in effective):
        shape = MAP
    elif all(isinstance(v, list) for v in effective):
        shape = LIST_OF_MAPS if list_merge.has_map_element(effective) else LIST_PLAIN
    else:
        shape = MISMATCH

    if strategy in MAP_STRATEGIES:
        applied = shape == MAP
    elif strategy in list_merge.LIST_STRATEGIES:
        applied = shape in (LIST_PLAIN, LIST_OF_MAPS)
    else:  # `first`: total on every shape.
        applied = shape != ABSENT

    children_ambient = "deep" if (applied and strategy == "deep") else "first"

    return BindingDecision(
        key_path=key_path,
        policy=policy,
        strategy=strategy,
        shape=shape,
        applied=applied,
        effective=effective,
        children_ambient=children_ambient,
    )
