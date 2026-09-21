"""Phase 4: validate -- catch malformed merge/removal data before resolve.

Checks scoped to declared `merge:` policies (scalar/map strategies only;
list shapes are a later ticket's work): a pattern that matches no key path
in any walked layer (`validate.pattern_matches_nothing`), a `shallow`/
`deep` policy that never wins against a map-shaped value on any host
(`validate.strategy_never_applies`), and a `!remove` that has nothing
more general to remove (`validate.remove_matches_nothing`). The `resolve`
phase raises no errors at all, by design -- anything that could go wrong
with merge data is caught here first.
"""

from __future__ import annotations

from reverie import keypath
from reverie.errors import DiagnosticCollector
from reverie.phases.configure import MergePolicy
from reverie.phases.load import LoadedHost
from reverie.yaml_io import REMOVE

PHASE = "validate"

_MAP_STRATEGIES = ("shallow", "deep")


def _walk(data: dict, prefix: str = "") -> list[tuple[str, object]]:
    """Every (key_path, value) pair in `data`, at every depth (map keys only)."""

    entries: list[tuple[str, object]] = []
    for key, value in data.items():
        path = f"{prefix}/{key}" if prefix else key
        entries.append((path, value))
        if isinstance(value, dict):
            entries.extend(_walk(value, path))
    return entries


def _check_removals(host: LoadedHost, collector: DiagnosticCollector) -> None:
    """A `!remove` reaches downward only: it must match something a
    strictly more general (already-walked) layer defined."""

    seen_paths: set[str] = set()
    for _layer, layer_data in host.layers:
        for path, value in _walk(layer_data):
            if value is REMOVE:
                if path not in seen_paths:
                    collector.add("validate.remove_matches_nothing")
            else:
                seen_paths.add(path)


def validate(loaded_hosts: list[LoadedHost], merge_policies: list[MergePolicy]) -> list[LoadedHost]:
    collector = DiagnosticCollector(PHASE)

    for host in loaded_hosts:
        _check_removals(host, collector)

    values_by_path: dict[str, list[object]] = {}
    for host in loaded_hosts:
        for _layer, layer_data in host.layers:
            for path, value in _walk(layer_data):
                values_by_path.setdefault(path, []).append(value)

    matched_patterns: set[str] = set()
    map_shaped_wins: set[str] = set()
    for path, values in values_by_path.items():
        for policy in merge_policies:
            if keypath.matches(policy.pattern, path):
                matched_patterns.add(policy.pattern)

        winners = keypath.best_match(merge_policies, path)
        for policy in winners:
            if policy.strategy in _MAP_STRATEGIES and any(isinstance(v, dict) for v in values):
                map_shaped_wins.add(policy.pattern)

    for policy in merge_policies:
        if policy.pattern not in matched_patterns:
            collector.add("validate.pattern_matches_nothing", pattern=policy.pattern)
        elif policy.strategy in _MAP_STRATEGIES and policy.pattern not in map_shaped_wins:
            collector.add("validate.strategy_never_applies", key_path=policy.pattern)

    collector.raise_if_any()
    return loaded_hosts
