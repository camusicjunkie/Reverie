"""The one binding decision `resolve` and `validate` each need for a key
path (issue #40): which policy wins, what strategy is actually in effect
(including ambient-strategy inheritance), whether the contributing values'
shape matches that strategy, and whether the strategy therefore applied.

Previously this question was answered twice, independently: `resolve`
computed it to execute the merge, and `validate` computed a cruder version
of it -- via raw key-path text flattened across every host -- to check for
policies that never actually bind. Flattening across hosts meant a policy
that mis-shapes on only one host in a multi-host estate was invisible,
since another host's correctly-shaped contribution would mask it. Both now
read their decisions from `merge_walk`, which binds through this module
once per merge (issues #53, #56).

This module answers the question and nothing more: it never raises (every
error condition stays scoped to exactly one phase, per ADR 0009), and it
never executes a merge -- `resolve` still owns turning `effective` into a
merged value, `validate` still owns turning a decision into a diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence, TypeVar

from reverie import keypath, list_merge
from reverie.phases.configure import MergePolicy
from reverie.yaml_io import Remove

MAP_STRATEGIES = ("shallow", "deep")

_Contribution = TypeVar("_Contribution")

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
    # Non-`!remove` contributions, most-general to most-specific -- what
    # the merge actually operates on, and what `merge_walk` recurses into
    # to reach the merges beneath this one.
    effective: list[Any]
    # The ambient strategy this key path's children inherit, per
    # CONTEXT.md "Strategy": `deep` propagates itself, everything else
    # (including a mismatched `deep`) falls back to `first`.
    children_ambient: str

    @property
    def folds_elements_as_maps(self) -> bool:
        """Whether this merge folds its matched list elements as maps, at
        the list's own key path (CONTEXT.md "Element group").

        The one place the fold rule is derived. Both traversals of a
        host's layer data read it here -- `merge_walk` to recurse into a
        fold's interior, the **path scan** to give the keys inside those
        elements the key paths `resolve` will merge them at -- so the
        divergence issues #47 and #48 recorded cannot come back through
        a second copy of the rule (issue #61).
        """

        return self.applied and list_merge.merges_elements_as_maps(self.strategy)


def effective_contributions(
    contributions: Sequence[_Contribution],
    value_of: Callable[[_Contribution], Any] = lambda contribution: contribution,
) -> list[_Contribution]:
    """The contributions a merge actually operates on: everything after the
    last `!remove`, most-general to most-specific.

    A `!remove` clears every more general contribution at the key path and
    holds no position of its own (CONTEXT.md "!remove"), so what survives
    is always a suffix of what was contributed -- empty when the most
    specific contribution was itself a `!remove`.

    `value_of` exists because `merge_walk` applies the same rule to
    contributions paired with the layer behind each one, where `bind` sees
    bare values: one rule, two shapes of input.
    """

    effective: list[_Contribution] = []
    for contribution in contributions:
        if isinstance(value_of(contribution), Remove):
            effective = []
        else:
            effective.append(contribution)
    return effective


def bind(
    key_path: str,
    contributions: list[Any],
    merge_policies: list[MergePolicy],
    ambient_strategy: str,
) -> BindingDecision:
    """The binding decision for one key path, given its per-layer
    contributions (general to specific, `!remove` included)."""

    effective = effective_contributions(contributions)

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
