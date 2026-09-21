"""Phase 5: resolve -- merge each host's layers into its final data.

No `merge:` policy is declared in this ticket's scope, so every key path
falls under the implied `**: first` strategy: the most specific layer to
define a top-level key wins outright. Full per-key-path policy
resolution (declared `merge:` blocks, the other six strategies, shape
classification) is later tickets' work (#33, #34). By design, this phase
raises no errors -- anything that could go wrong with merge data was
already caught in `validate`.
"""

from __future__ import annotations

from dataclasses import dataclass

from reverie.phases.load import LoadedHost

PHASE = "resolve"


@dataclass(frozen=True)
class ResolvedHost:
    name: str
    data: dict
    # Ordered most-general to most-specific, the layer addresses this host
    # actually walked -- goes straight into the artifact's reverie_meta.
    layers_walked: list[str]


def resolve(loaded_hosts: list[LoadedHost]) -> list[ResolvedHost]:
    resolved: list[ResolvedHost] = []
    for host in loaded_hosts:
        data: dict = {}
        for layer, layer_data in host.layers:
            data.update(layer_data)  # most-specific-last wins: implied **: first
        layers_walked = [layer.address for layer, _ in host.layers]
        resolved.append(ResolvedHost(name=host.name, data=data, layers_walked=layers_walked))
    return resolved
