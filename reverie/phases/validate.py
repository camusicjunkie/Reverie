"""Phase 4: validate -- catch malformed merge/removal data before resolve.

Checks scoped to declared `merge:` policies: a pattern that matches no key
path in any walked layer (`validate.pattern_matches_nothing`), a policy
whose strategy never wins against a shape it can bind to on any host
(`validate.strategy_never_applies`), a tuple strategy (`unique_tuple`,
`deep_tuple`) that only ever meets a plain list -- never a map -- where it
wins (`validate.non_map_in_tuple_merge`), a duplicate element within one
layer's own list under a comparing strategy (`validate.duplicate_in_layer`),
and a `!remove` (map key or list element) that has nothing more general to
remove (`validate.remove_matches_nothing`). The `resolve` phase raises no
errors at all, by design -- anything that could go wrong with merge data is
caught here first.
"""

from __future__ import annotations

from reverie import keypath, list_merge
from reverie.errors import DiagnosticCollector
from reverie.phases.configure import MergePolicy
from reverie.phases.load import LoadedHost
from reverie.yaml_io import Remove

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


def _best_policy(key_path: str, merge_policies: list[MergePolicy]) -> MergePolicy | None:
    matches = keypath.best_match(merge_policies, key_path)
    return matches[0] if matches else None


def _check_removals(host: LoadedHost, collector: DiagnosticCollector, merge_policies: list[MergePolicy]) -> None:
    """A `!remove` reaches downward only: it must match something a
    strictly more general (already-walked) layer defined -- a map key by
    identity, a list element by whichever equality the path's declared
    list strategy uses."""

    seen_paths: set[str] = set()
    seen_list_elements: dict[str, list[object]] = {}

    for _layer, layer_data in host.layers:
        for path, value in _walk(layer_data):
            if isinstance(value, Remove):
                if path not in seen_paths:
                    collector.add("validate.remove_matches_nothing")
            else:
                seen_paths.add(path)

            if isinstance(value, list):
                policy = _best_policy(path, merge_policies)
                strategy = policy.strategy if policy else None
                tuple_keys = policy.tuple_keys if policy else None
                prior = seen_list_elements.get(path, [])

                for element in value:
                    if not isinstance(element, Remove):
                        continue
                    if strategy not in list_merge.LIST_STRATEGIES or not any(
                        list_merge.elements_equal(element.value, existing, strategy, tuple_keys)
                        for existing in prior
                    ):
                        collector.add("validate.remove_matches_nothing")

                seen_list_elements[path] = prior + [e for e in value if not isinstance(e, Remove)]


def _check_duplicates_in_layer(host: LoadedHost, collector: DiagnosticCollector, merge_policies: list[MergePolicy]) -> None:
    """A duplicate element within one layer's own list, under a strategy
    that compares elements at all (`append` never does)."""

    for layer, layer_data in host.layers:
        for path, value in _walk(layer_data):
            if not isinstance(value, list):
                continue
            policy = _best_policy(path, merge_policies)
            if policy is None or policy.strategy not in list_merge.COMPARING_STRATEGIES:
                continue
            elements = [e for e in value if not isinstance(e, Remove)]
            for i, a in enumerate(elements):
                if any(list_merge.elements_equal(a, b, policy.strategy, policy.tuple_keys) for b in elements[i + 1 :]):
                    collector.add("validate.duplicate_in_layer", file=str(layer.path), line=None)
                    break  # one report per key path is enough; keep scanning the layer's other paths


def validate(loaded_hosts: list[LoadedHost], merge_policies: list[MergePolicy]) -> list[LoadedHost]:
    collector = DiagnosticCollector(PHASE)

    for host in loaded_hosts:
        _check_removals(host, collector, merge_policies)
        _check_duplicates_in_layer(host, collector, merge_policies)

    values_by_path: dict[str, list[object]] = {}
    for host in loaded_hosts:
        for _layer, layer_data in host.layers:
            for path, value in _walk(layer_data):
                values_by_path.setdefault(path, []).append(value)

    matched_patterns: set[str] = set()
    map_shaped_wins: set[str] = set()
    plain_list_wins: set[str] = set()
    list_of_maps_wins: set[str] = set()
    non_map_tuple_patterns: set[str] = set()

    for path, values in values_by_path.items():
        for policy in merge_policies:
            if keypath.matches(policy.pattern, path):
                matched_patterns.add(policy.pattern)

        winners = keypath.best_match(merge_policies, path)
        list_values = [v for v in values if isinstance(v, list)]
        for policy in winners:
            if policy.strategy in _MAP_STRATEGIES and any(isinstance(v, dict) for v in values):
                map_shaped_wins.add(policy.pattern)
            elif policy.strategy in list_merge.PLAIN_LIST_STRATEGIES and list_values:
                if not list_merge.has_map_element(list_values):
                    plain_list_wins.add(policy.pattern)
            elif policy.strategy in list_merge.TUPLE_STRATEGIES and list_values:
                if list_merge.has_map_element(list_values):
                    list_of_maps_wins.add(policy.pattern)
                else:
                    non_map_tuple_patterns.add(policy.pattern)

    for _pattern in non_map_tuple_patterns:
        collector.add("validate.non_map_in_tuple_merge")

    for policy in merge_policies:
        if policy.pattern not in matched_patterns:
            collector.add("validate.pattern_matches_nothing", pattern=policy.pattern)
        elif policy.strategy in _MAP_STRATEGIES and policy.pattern not in map_shaped_wins:
            collector.add("validate.strategy_never_applies", key_path=policy.pattern)
        elif policy.strategy in list_merge.PLAIN_LIST_STRATEGIES and policy.pattern not in plain_list_wins:
            collector.add("validate.strategy_never_applies", key_path=policy.pattern)
        elif (
            policy.strategy in list_merge.TUPLE_STRATEGIES
            and policy.pattern not in list_of_maps_wins
            and policy.pattern not in non_map_tuple_patterns
        ):
            collector.add("validate.strategy_never_applies", key_path=policy.pattern)

    collector.raise_if_any()
    return loaded_hosts
