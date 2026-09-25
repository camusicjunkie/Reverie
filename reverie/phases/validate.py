"""Phase 4: validate -- catch malformed merge/removal data before resolve.

Checks scoped to declared `merge:` policies: a pattern that matches no key
path in any walked layer (`validate.pattern_matches_nothing`), a policy
whose strategy never wins against a shape it can bind to on any host
(`validate.strategy_never_applies`), a tuple strategy (`unique_tuple`,
`deep_tuple`) that only ever meets a plain list -- never a map -- where it
wins (`validate.non_map_in_tuple_merge`), a duplicate element within one
layer's own list under a comparing strategy (`validate.duplicate_in_layer`),
and a `!remove` (map key or list element) that has nothing more general to
remove (`validate.remove_matches_nothing`).

Checks scoped to declared `secrets:` key paths (ADR 0006): a `!vault`
scalar reached by a comparing strategy (`unique`, `unique_tuple`,
`deep_tuple`) -- whole-element for `unique`, a `tuple_keys` field for the
tuple strategies -- since salting makes ciphertext comparison meaningless
(`validate.secret_not_comparable`), and a plaintext (neither `!vault` nor
`!secret`) value at a declared secret key path in any walked layer, winner
or not (`validate.secret_is_plaintext`).

The `resolve` phase raises no errors at all, by design -- anything that
could go wrong with merge data is caught here first.
"""

from __future__ import annotations

from reverie import keypath, list_merge, merge_plan
from reverie.errors import DiagnosticCollector
from reverie.phases.configure import MergePolicy
from reverie.phases.load import LoadedHost
from reverie.yaml_io import Remove, Secret, Vault

PHASE = "validate"

_MAP_STRATEGIES = merge_plan.MAP_STRATEGIES


def _folds_elements_as_maps(merge_policies: list[MergePolicy], key_path: str) -> bool:
    """Whether a list at `key_path` is declared under a strategy that merges
    its matched elements as maps -- see `list_merge.merges_elements_as_maps`."""

    policy = keypath.winner(merge_policies, key_path)
    return policy is not None and list_merge.merges_elements_as_maps(policy.strategy)


def _walk(data: dict, merge_policies: list[MergePolicy], prefix: str = "") -> list[tuple[str, object]]:
    """Every (key_path, value) pair in one layer's `data`, at every depth.

    Map keys, plus the keys of the map elements of a `deep_tuple`-declared
    list -- at the list's own key path, since that is where `resolve` folds
    those elements together (issue #47). A `!remove` element is not
    descended into: it contributes a match, not data, and `resolve` never
    merges its interior.

    This is raw per-layer key-path text, deliberately broader than the
    binding decisions `_decisions_for_host` computes: it answers "does any
    walked layer touch this path at all", so a policy under a shadowed
    ancestor still counts as matching something and reports as a strategy
    that never applies rather than as a pattern matching nothing. One layer
    alone has no cross-layer element matching either, so the paths inside
    its elements pool per key path rather than per element -- the checks
    over them are correspondingly path-keyed, which errs towards silence.
    """

    entries: list[tuple[str, object]] = []
    for key, value in data.items():
        path = f"{prefix}/{key}" if prefix else key
        entries.append((path, value))
        if isinstance(value, dict):
            entries.extend(_walk(value, merge_policies, path))
        elif isinstance(value, list) and _folds_elements_as_maps(merge_policies, path):
            for element in value:
                if isinstance(element, dict):
                    entries.extend(_walk(element, merge_policies, path))
    return entries


def _check_removals(host: LoadedHost, collector: DiagnosticCollector, merge_policies: list[MergePolicy]) -> None:
    """A `!remove` reaches downward only: it must match something a
    strictly more general (already-walked) layer defined -- a map key by
    identity, a list element by whichever equality the path's declared
    list strategy uses."""

    seen_paths: set[str] = set()
    seen_list_elements: dict[str, list[object]] = {}

    for _layer, layer_data in host.layers:
        for path, value in _walk(layer_data, merge_policies):
            if isinstance(value, Remove):
                if path not in seen_paths:
                    collector.add("validate.remove_matches_nothing")
            else:
                seen_paths.add(path)

            if isinstance(value, list):
                policy = keypath.winner(merge_policies, path)
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


def _check_duplicates_in_layer(
    host: LoadedHost,
    collector: DiagnosticCollector,
    merge_policies: list[MergePolicy],
    defaults_address: str | None,
) -> None:
    """A duplicate element within one layer's own list, under a strategy
    that compares elements at all (`append` never does).

    The defaults floor reports under its own condition: it sits beneath the
    chain rather than in it, so "the floor ships redundant data" is a
    separately addressable finding from the same fault in a chain layer.
    """

    for layer, layer_data in host.layers:
        condition = (
            "validate.duplicate_floor_key"
            if defaults_address is not None and layer.address == defaults_address
            else "validate.duplicate_in_layer"
        )
        for path, value in _walk(layer_data, merge_policies):
            if not isinstance(value, list):
                continue
            policy = keypath.winner(merge_policies, path)
            if policy is None or policy.strategy not in list_merge.COMPARING_STRATEGIES:
                continue
            elements = [e for e in value if not isinstance(e, Remove)]
            for i, a in enumerate(elements):
                if any(list_merge.elements_equal(a, b, policy.strategy, policy.tuple_keys) for b in elements[i + 1 :]):
                    collector.add(condition, file=str(layer.path), line=None)
                    break  # one report per key path is enough; keep scanning the layer's other paths


def _check_secrets(
    host: LoadedHost,
    collector: DiagnosticCollector,
    secrets: list[str],
    merge_policies: list[MergePolicy],
) -> None:
    """A plaintext value at a declared secret key path, in any walked layer.

    Checked over every layer, not just the winner -- a non-winning layer's
    plaintext is exactly as much of a leak risk sitting in git history
    (ADR 0006).
    """

    if not secrets:
        return

    for layer, layer_data in host.layers:
        for path, value in _walk(layer_data, merge_policies):
            if isinstance(value, (dict, list, Remove)):
                continue
            if not isinstance(value, (Vault, Secret)) and any(keypath.matches(pattern, path) for pattern in secrets):
                collector.add("validate.secret_is_plaintext", layer=str(layer.path))


def _tuple_keys_missing(layer_lists: list[list], tuple_keys: tuple[str, ...] | None) -> bool:
    """Whether any map element across `layer_lists` lacks a declared tuple key.

    Element identity under a tuple strategy *is* the declared keys, so an
    element missing one can never match anything -- it silently accumulates
    instead of merging, which is the opposite of what declaring the policy
    asked for.
    """

    for layer_list in layer_lists:
        for element in layer_list:
            target = element.value if isinstance(element, Remove) else element
            if isinstance(target, dict) and not all(key in target for key in tuple_keys or ()):
                return True
    return False


def _decisions_for_host(host: LoadedHost, merge_policies: list[MergePolicy]) -> list[merge_plan.BindingDecision]:
    """Every binding decision `resolve` would compute while merging this
    host, in the same order (same ambient-strategy inheritance, same
    recursion into map-shaped, strategy-applied children only, same fold of
    each `deep_tuple`-matched element group) -- so a policy shadowed under
    an ancestor's `first` (never reached during resolve) is invisible here
    too, and a mis-shape on this host alone can't be masked by another
    host's correctly-shaped contribution."""

    decisions: list[merge_plan.BindingDecision] = []

    def walk(key_path: str, dicts: list[dict], ambient: str) -> None:
        keys = dict.fromkeys(key for d in dicts for key in d)
        for key in keys:
            child_path = f"{key_path}/{key}" if key_path else key
            contributions = [d[key] for d in dicts if key in d]
            decision = merge_plan.bind(child_path, contributions, merge_policies, ambient)
            decisions.append(decision)
            if decision.applied and decision.strategy in _MAP_STRATEGIES:
                walk(child_path, decision.effective, decision.children_ambient)
            elif decision.applied and list_merge.merges_elements_as_maps(decision.strategy):
                # `resolve.merge_lists` folds each group of matched elements
                # into one via a map merge at this same key path -- so those
                # folds' children are decisions this host really computes.
                tuple_keys = decision.policy.tuple_keys if decision.policy else None
                for group in list_merge.element_groups(decision.effective, decision.strategy, tuple_keys):
                    if len(group) > 1:  # a lone element survives whole, unmerged
                        walk(child_path, group, "first")

    walk("", [layer_data for _layer, layer_data in host.layers], "first")
    return decisions


def validate(
    loaded_hosts: list[LoadedHost],
    merge_policies: list[MergePolicy],
    secrets: list[str] | None = None,
    defaults_address: str | None = None,
) -> list[LoadedHost]:
    collector = DiagnosticCollector(PHASE)
    secrets = secrets or []

    for host in loaded_hosts:
        _check_removals(host, collector, merge_policies)
        _check_duplicates_in_layer(host, collector, merge_policies, defaults_address)
        _check_secrets(host, collector, secrets, merge_policies)

    values_by_path: dict[str, list[object]] = {}
    for host in loaded_hosts:
        for _layer, layer_data in host.layers:
            for path, value in _walk(layer_data, merge_policies):
                values_by_path.setdefault(path, []).append(value)

    matched_patterns: set[str] = set()
    vault_comparison_patterns: set[str] = set()

    for path, values in values_by_path.items():
        for policy in merge_policies:
            if keypath.matches(policy.pattern, path):
                matched_patterns.add(policy.pattern)

        list_values = [v for v in values if isinstance(v, list)]
        for policy in keypath.best_match(merge_policies, path):
            if policy.strategy in list_merge.COMPARING_STRATEGIES and list_values:
                elements = [
                    element.value if isinstance(element, Remove) else element
                    for layer_list in list_values
                    for element in layer_list
                ]
                if list_merge.has_vault_comparison(elements, policy.strategy, policy.tuple_keys):
                    vault_comparison_patterns.add(policy.pattern)

    map_shaped_wins: set[str] = set()
    plain_list_wins: set[str] = set()
    list_of_maps_wins: set[str] = set()
    non_map_tuple_patterns: set[str] = set()
    incomplete_tuple_patterns: set[str] = set()

    for host in loaded_hosts:
        decisions = _decisions_for_host(host, merge_policies)

        # A host whose every top-level key resolved away (or that never had
        # one) emits an artifact with an empty `reverie:` -- inert, and
        # almost always a mis-declared chain rather than an intent.
        top_level = [d for d in decisions if "/" not in d.key_path]
        if all(d.shape == merge_plan.ABSENT for d in top_level):
            collector.add("validate.host_has_no_keys", host=host.name)

        for decision in decisions:
            policy = decision.policy
            if policy is None or not decision.applied:
                continue
            if policy.strategy in list_merge.TUPLE_STRATEGIES and decision.shape == merge_plan.LIST_OF_MAPS:
                if _tuple_keys_missing(decision.effective, policy.tuple_keys):
                    incomplete_tuple_patterns.add(policy.pattern)
            if policy.strategy in _MAP_STRATEGIES:
                map_shaped_wins.add(policy.pattern)
            elif policy.strategy in list_merge.PLAIN_LIST_STRATEGIES:
                if decision.shape == merge_plan.LIST_PLAIN:
                    plain_list_wins.add(policy.pattern)
            elif policy.strategy in list_merge.TUPLE_STRATEGIES:
                if decision.shape == merge_plan.LIST_OF_MAPS:
                    list_of_maps_wins.add(policy.pattern)
                else:
                    non_map_tuple_patterns.add(policy.pattern)

    for _pattern in non_map_tuple_patterns:
        collector.add("validate.non_map_in_tuple_merge")

    for _pattern in incomplete_tuple_patterns:
        collector.add("validate.missing_tuple_key")

    for pattern in vault_comparison_patterns:
        collector.add("validate.secret_not_comparable", key_path=pattern)

    for pattern in secrets:
        if not any(keypath.matches(pattern, path) for path in values_by_path):
            collector.add("validate.secrets_pattern_matches_nothing", pattern=pattern)

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
