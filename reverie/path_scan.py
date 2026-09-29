"""Every key path a host's layers hold, layer by layer (issue #61).

The second of the two named traversals of a host's layer data, beside the
**merge walk** (`reverie.merge_walk`). The walk answers "which merges does
this host perform, and what does each bind to". This answers a different
question: "does any walked layer touch this key path at all" -- per layer,
winner or not, merged or not.

Four of `validate`'s verdicts rest on that question rather than on a
binding decision: a `!remove` with nothing more general to remove, a
duplicate element inside one layer's own list, a plaintext value at a
declared secret key path, and the path-match evidence behind a
`PolicyObservation`. None of them is about a merge -- a leak in a layer
that loses is still a leak -- so none can be read off the walk.

The scan is deliberately **broader** than the walk, and that is contract,
not accident. A merge policy addressed under an ancestor that `first`
shadows binds to nothing, so the walk never reaches it; the scan still
sees a layer touching its pattern, and the policy is therefore reported as
a strategy that never applies rather than as a pattern matching nothing.
Folding the two traversals into one would change which condition fires.
Two named traversals, side by side, is the intended end state.

One rule they do share is the `deep_tuple` fold: the keys of the map
elements of a `deep_tuple`-declared list hang from the list's own key path
(CONTEXT.md "Key path"), so the scan descends into those elements and only
those. That rule is derived in one place -- `merge_plan.BindingDecision.
folds_elements_as_maps` -- and read here and by the walk, so the scan
cannot drift from what `resolve` actually folds, which is the divergence
class issues #47 and #48 recorded.

The scan is per layer, so it has no cross-layer element matching to do:
the paths inside one layer's elements pool per key path rather than per
element, and the checks over them are correspondingly path-keyed, which
errs towards silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from reverie import merge_plan
from reverie.phases.configure import MergePolicy
from reverie.phases.enumerate import LayerRef
from reverie.phases.load import LoadedHost


@dataclass(frozen=True)
class Entry:
    """One value one layer holds at one key path."""

    layer: LayerRef
    key_path: str
    value: Any


def scan(host: LoadedHost, merge_policies: list[MergePolicy]) -> tuple[Entry, ...]:
    """Every `(layer, key path, value)` `host`'s layers hold.

    In layer order, most general first, and within a layer in the order
    the keys are written -- the order a check that accumulates what more
    general layers defined needs.
    """

    return tuple(
        Entry(layer=layer, key_path=key_path, value=value)
        for layer, layer_data in host.layers
        for key_path, value in _paths(layer_data, merge_policies, "")
    )


def _paths(
    data: dict, merge_policies: list[MergePolicy], prefix: str
) -> list[tuple[str, Any]]:
    """Every (key path, value) pair in one layer's `data`, at every depth.

    Map keys, plus the keys of the map elements of a `deep_tuple`-declared
    list -- at the list's own key path, since that is where `resolve`
    folds those elements together (issue #47). A `!remove` element is not
    descended into: it contributes a match, not data, and `resolve` never
    merges its interior.
    """

    entries: list[tuple[str, Any]] = []
    for key, value in data.items():
        path = f"{prefix}/{key}" if prefix else key
        entries.append((path, value))
        if isinstance(value, dict):
            entries.extend(_paths(value, merge_policies, path))
        elif isinstance(value, list) and _folds_elements_as_maps(path, value, merge_policies):
            for element in value:
                if isinstance(element, dict):
                    entries.extend(_paths(element, merge_policies, path))
    return entries


def _folds_elements_as_maps(
    key_path: str, value: list, merge_policies: list[MergePolicy]
) -> bool:
    """Whether `resolve` would fold the elements of this list as maps.

    Asked of `merge_plan` rather than answered here, so the scan and the
    merge walk read the fold rule off the same binding decision. One
    layer's list is bound alone under ambient `first`, which is enough:
    no ambient strategy is a tuple strategy, so only a declared policy can
    make a list fold, and whether it does depends on this list's shape
    alone.
    """

    decision = merge_plan.bind(key_path, [value], merge_policies, "first")
    return decision.folds_elements_as_maps


def values_by_key_path(entries: Iterable[Entry]) -> dict[str, list[Any]]:
    """Every value `entries` hold, pooled by key path, in scan order.

    What a check asks when the layer a value sits in does not matter, only
    that some layer holds it -- the estate-wide path-match evidence a
    `PolicyObservation` reads.
    """

    pooled: dict[str, list[Any]] = {}
    for entry in entries:
        pooled.setdefault(entry.key_path, []).append(entry.value)
    return pooled
