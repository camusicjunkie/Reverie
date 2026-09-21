"""Phase 5: resolve -- merge each host's layers into its final data.

Scalar and map strategies only (`first`, `shallow`, `deep`); list shapes
are a later ticket's work (#34). By design, this phase raises no errors --
anything that could go wrong with merge data was already caught in
`validate`.

The most specific *declared* policy for a key path wins outright. Where
nothing is explicitly declared for a key path, it inherits the ambient
strategy its parent map is being merged under: `deep` recurses (the
strategy that structurally governs its whole subtree until a more
specific declaration interrupts it), while `shallow` and the implied
top-level default both fall back to `first` for their children.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reverie import keypath
from reverie.phases.configure import MergePolicy
from reverie.phases.load import LoadedHost
from reverie.yaml_io import REMOVE

PHASE = "resolve"

_ABSENT = object()


@dataclass(frozen=True)
class ResolvedHost:
    name: str
    data: dict
    # Ordered most-general to most-specific, the layer addresses this host
    # actually walked -- goes straight into the artifact's reverie_meta.
    layers_walked: list[str]


def _explicit_strategy(key_path: str, merge_policies: list[MergePolicy]) -> str | None:
    matches = keypath.best_match(merge_policies, key_path)
    return matches[0].strategy if matches else None


def _merge_key(
    key_path: str,
    contributions: list[Any],
    merge_policies: list[MergePolicy],
    ambient_strategy: str,
) -> Any:
    """Merge one key path's per-layer values (general to specific)."""

    effective: list[Any] = []
    for value in contributions:
        if value is REMOVE:
            effective = []
        else:
            effective.append(value)

    if not effective:
        return _ABSENT

    strategy = _explicit_strategy(key_path, merge_policies) or ambient_strategy

    if strategy in ("shallow", "deep"):
        if all(isinstance(v, dict) for v in effective):
            child_ambient = "deep" if strategy == "deep" else "first"
            return _merge_maps(key_path, effective, merge_policies, child_ambient)
        return effective[-1]  # shape mismatch -> most-specific-wins, like `first`

    # `first`, and the four list strategies (out of scope this ticket):
    # most-specific-wins.
    return effective[-1]


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
