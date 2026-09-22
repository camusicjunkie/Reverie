"""Phase 5: resolve -- merge each host's layers into its final data.

By design, this phase raises no errors -- anything that could go wrong
with merge data was already caught in `validate`.

The most specific *declared* policy for a key path wins outright. Where
nothing is explicitly declared for a key path, it inherits the ambient
strategy its parent map is being merged under: `deep` recurses (the
strategy that structurally governs its whole subtree until a more
specific declaration interrupts it), while `shallow` and the implied
top-level default both fall back to `first` for their children.

List strategies (`append`, `unique`, `unique_tuple`, `deep_tuple`) bind
only to list-shaped values; on any other shape, most-specific-wins
applies instead, same as `shallow`/`deep` against a non-map value. Their
one shared ordering rule -- each distinct element once, at the position
of its first contribution, layers concatenated most-specific-first -- and
`!remove`'s list-element semantics live in `reverie.list_merge`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reverie import keypath, list_merge
from reverie.phases.configure import MergePolicy
from reverie.phases.load import LoadedHost
from reverie.yaml_io import Remove

PHASE = "resolve"

_ABSENT = object()


@dataclass(frozen=True)
class ResolvedHost:
    name: str
    data: dict
    # Ordered most-general to most-specific, the layer addresses this host
    # actually walked -- goes straight into the artifact's reverie_meta.
    layers_walked: list[str]


def _merge_key(
    key_path: str,
    contributions: list[Any],
    merge_policies: list[MergePolicy],
    ambient_strategy: str,
) -> Any:
    """Merge one key path's per-layer values (general to specific)."""

    effective: list[Any] = []
    for value in contributions:
        if isinstance(value, Remove):
            effective = []
        else:
            effective.append(value)

    if not effective:
        return _ABSENT

    policy = keypath.winner(merge_policies, key_path)
    strategy = policy.strategy if policy else ambient_strategy

    if strategy in ("shallow", "deep"):
        if all(isinstance(v, dict) for v in effective):
            child_ambient = "deep" if strategy == "deep" else "first"
            return _merge_maps(key_path, effective, merge_policies, child_ambient)
        return effective[-1]  # shape mismatch -> most-specific-wins, like `first`

    if strategy in list_merge.LIST_STRATEGIES:
        if all(isinstance(v, list) for v in effective):
            tuple_keys = policy.tuple_keys if policy else None
            return _merge_lists(key_path, effective, strategy, tuple_keys, merge_policies)
        return effective[-1]  # shape mismatch -> most-specific-wins

    # `first`: most-specific-wins.
    return effective[-1]


def _merge_lists(
    key_path: str,
    layer_lists: list[list[Any]],
    strategy: str,
    tuple_keys: tuple[str, ...] | None,
    merge_policies: list[MergePolicy],
) -> list[Any]:
    """Merge one key path's per-layer lists under a list strategy.

    Most-specific-first, keep-first-occurrence, clustered by layer -- see
    `reverie.list_merge`'s module docstring. `deep_tuple` additionally
    folds each matched general-layer element into the kept (more
    specific) one via a normal map merge, at this same key path so any
    nested policy declared under it (e.g. `items/tags`) still applies.
    """

    removal_targets: list[Any] = []
    kept: list[Any] = []

    for layer in reversed(layer_lists):  # most-specific-first
        layer_removals = [element.value for element in layer if isinstance(element, Remove)]

        for element in layer:
            if isinstance(element, Remove):
                continue  # contributes a match, not an element -- holds no position
            if any(list_merge.elements_equal(element, target, strategy, tuple_keys) for target in removal_targets):
                continue
            match = next(
                (i for i, existing in enumerate(kept) if list_merge.elements_equal(element, existing, strategy, tuple_keys)),
                None,
            )
            if match is not None:
                if strategy == "deep_tuple":
                    kept[match] = _merge_maps(key_path, [element, kept[match]], merge_policies, "first")
                continue  # unique / unique_tuple: the kept (more specific) element survives whole
            kept.append(element)

        removal_targets.extend(layer_removals)

    return kept


def _merge_maps(
    key_path: str,
    dicts: list[dict],
    merge_policies: list[MergePolicy],
    ambient_strategy: str,
) -> dict:
    keys = dict.fromkeys(key for d in dicts for key in d)
    result: dict = {}
    for key in keys:
        child_path = f"{key_path}/{key}" if key_path else key
        contributions = [d[key] for d in dicts if key in d]
        merged = _merge_key(child_path, contributions, merge_policies, ambient_strategy)
        if merged is not _ABSENT:
            result[key] = merged
    return result


def resolve(loaded_hosts: list[LoadedHost], merge_policies: list[MergePolicy]) -> list[ResolvedHost]:
    resolved: list[ResolvedHost] = []
    for host in loaded_hosts:
        layer_dicts = [layer_data for _layer, layer_data in host.layers]
        data = _merge_maps("", layer_dicts, merge_policies, ambient_strategy="first")
        layers_walked = [layer.address for layer, _ in host.layers]
        resolved.append(ResolvedHost(name=host.name, data=data, layers_walked=layers_walked))
    return resolved
