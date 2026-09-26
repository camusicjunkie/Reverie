"""The `reverie rsop` verb -- a per-host provenance document (issue #38).

Distinct from the artifact (CONTEXT.md "RSOP"): a flat map of RSOP address
to record, showing every contributor and the losers, not just the winner.
Generated on demand, never committed, and a pure function of
`(source tree, host)` -- it never reads the artifact and works correctly
even in a checkout where `compile` has never been run.

Coverage is every merge this host performs: every key path any walked layer
touches through its maps, intermediate maps included, plus the key paths a
`deep_tuple` fold merges *inside* a list's elements. One key path is merged
once per element group there, so those records are filed under an RSOP
address -- the key path with an element selector, `groups[name=admins]`,
naming the element by its declared `tuple_keys` (CONTEXT.md "RSOP address",
ADR 0010). Nothing is merged inside an element under any other list
strategy, nor inside a group of one, so neither has anything to attribute.
Each record carries exactly one of `value:`,
`redacted:`, `removed: true`, plus the `policy` that governed it (the
declared strategy/pattern, or the ambient one it inherited) and its
`contributors`, most-specific-first.

The binding decision (policy, effective strategy, shape, applied-or-not) at
each key path comes from `merge_plan.bind`, the same primitive `resolve`
executes -- so a list's *value* here is always identical to what `compile`
would emit for it, via the same `resolve.merge_lists`. Only the per-layer
contributor bookkeeping is this module's own. Per CONTEXT.md's `Contributor`
entry, a layer's contribution at a key path resolves to exactly one of:

- `won` -- the sole survivor under most-specific-wins (an explicit `first`,
  or a shape mismatch falling back to it).
- `overridden` -- superseded, either by `won` at the same path or by a
  later `!remove` that cleared it.
- `merged` -- folded into a map or list merge (`shallow`/`deep`, or a list
  strategy binding to list-shaped values).
- `removed` -- the layer's own contribution at this path was `!remove`.

`!vault` values redact to `redacted: vault` in place of `value:` (their
contributor entries keep the ciphertext, unredacted -- it's already opaque
material, so showing it costs nothing, and attribution stays legible).
`!secret` addresses are never redacted; they're addresses, not material.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reverie import list_merge, merge_plan
from reverie.errors import Diagnostic, DiagnosticCollector, PhaseFailed
from reverie.phases import configure as configure_phase
from reverie.phases import enumerate as enumerate_phase
from reverie.phases import load as load_phase
from reverie.phases import validate as validate_phase
from reverie.phases.configure import MergePolicy, SourceConfig
from reverie.phases.enumerate import LayerRef
from reverie.phases.load import LoadedHost
from reverie.phases.resolve import merge_lists
from reverie.version import COMPILER_VERSION, SPEC_VERSION
from reverie.yaml_io import Remove, Vault, dump_flow_scalar, dump_pinned

_ABSENT = object()


def _strip_removes(value: object) -> object:
    """A contributor's raw per-layer value, with any `!remove` marker
    unwrapped to its underlying content -- the tag itself is never
    emitted (CONTEXT.md "!remove"), including when it sits buried inside
    a list or map a layer contributed at this key path."""

    if isinstance(value, Remove):
        return _strip_removes(value.value)
    if isinstance(value, dict):
        return {key: _strip_removes(v) for key, v in value.items()}
    if isinstance(value, list):
        return [_strip_removes(v) for v in value]
    return value


@dataclass(frozen=True)
class RsopResult:
    diagnostics: list[Diagnostic]
    text: str | None  # the rendered `rsop_meta:`/`rsop:` document, or None on failure


def _check_output_path(output: str | None, root: Path, collector: DiagnosticCollector) -> None:
    """`--output` must land outside both the source tree and the compiler's
    owned output directories -- both nested under `root`, so one check
    against `root` itself covers both (CONTEXT.md "Owned directory")."""

    if output is None:
        return

    path = Path(output)
    resolved = path if path.is_absolute() else Path.cwd() / path
    resolved = resolved.resolve()
    root_resolved = root.resolve()

    if resolved == root_resolved or root_resolved in resolved.parents:
        collector.add("configure.rsop_output_in_estate", path=str(path), tree=str(root))
    elif not resolved.parent.is_dir():
        collector.add("configure.rsop_output_parent_missing", path=str(path))


def _element_selector(element: dict, tuple_keys: tuple[str, ...] | None) -> str:
    """The `[name=Administrators]` part of an RSOP address (CONTEXT.md
    "RSOP address"), naming one folded element by the identity the merge
    itself used: its declared `tuple_keys`, in declaration order.

    Every element of a fold carries every declared tuple key -- that's what
    made them match, and `validate.missing_tuple_key` rejects an estate
    where one doesn't -- so this never has to describe a partial identity.

    Each value is written as YAML writes a scalar inside a flow collection
    (`yaml_io.dump_flow_scalar`), which is what a selector is: so the
    delimiters are unambiguous without an escape scheme of Reverie's own,
    and two distinct elements can never render to one address.
    """

    pairs = ",".join(f"{key}={dump_flow_scalar(element[key])}" for key in tuple_keys or ())
    return f"[{pairs}]"


def _records_inside_fold(
    records: dict[str, dict],
    address: str,
    key_path: str,
    effective: list[tuple[LayerRef, object]],
    decision: merge_plan.BindingDecision,
    merge_policies: list[MergePolicy],
) -> None:
    """Records for the key paths a `deep_tuple` fold merges inside this
    list's elements (issue #48).

    One address per element group, so two groups contributing the same key
    attribute separately instead of colliding on the list's own path. The
    grouping and the skip of a group of one come from the same
    `list_merge.element_groups_by_layer` that `resolve.merge_lists` folds
    by, so these records describe the merges that really happened and no
    others.

    The fold's *interior* is then walked here rather than by `resolve`,
    because only this module tracks which layer contributed each element.
    So this mirrors `resolve._merge_maps` -- ambient `first`, the group
    most-general-first, keys in first-contribution order -- exactly as
    `_record_for_path` already mirrors it for a map's children. The
    emitted list value still comes from `merge_lists` itself, so the
    document's *values* remain byte-identical to `compile`'s either way.
    """

    tuple_keys = decision.policy.tuple_keys if decision.policy else None
    groups = list_merge.element_groups_by_layer(
        [value for _layer, value in effective], decision.strategy, tuple_keys
    )

    for group in groups:
        if len(group) < 2:
            continue  # a lone element survives whole -- nothing is merged inside it
        # A group of two or more matched under a tuple strategy, so every
        # member of it is map-shaped -- that is what `elements_equal` had
        # to establish to group them at all.
        elements: list[tuple[LayerRef, dict]] = [(effective[index][0], element) for index, element in group]
        element_address = f"{address}{_element_selector(group[-1][1], tuple_keys)}"
        keys = dict.fromkeys(key for _layer, element in elements for key in element)
        for key in keys:
            _record_for_path(
                records,
                f"{element_address}/{key}",
                f"{key_path}/{key}",
                [(layer, element[key]) for layer, element in elements if key in element],
                merge_policies,
                ambient_strategy="first",
            )


def _record_for_path(
    records: dict[str, dict],
    address: str,
    key_path: str,
    contributions: list[tuple[LayerRef, object]],
    merge_policies: list[MergePolicy],
    ambient_strategy: str,
) -> object:
    """Compute the record for one key path, store it in `records` under its
    RSOP address, and return its resolved value (or `_ABSENT` if removed)
    for the parent map merge to fold in -- the same shape
    `resolve._merge_key` returns.

    `key_path` is what binds the policy; `address` is only where the record
    is filed. The two differ exactly below a `deep_tuple` fold, where one
    key path is merged once per element group: a `merge:` pattern addresses
    the path, a reader addresses the element.
    """

    decision = merge_plan.bind(key_path, [value for _layer, value in contributions], merge_policies, ambient_strategy)
    policy = decision.policy
    strategy = decision.strategy

    # `bind` computes the same reset-on-`!remove` effective set, but
    # without layer identity -- the contributor bookkeeping below needs
    # each surviving value's layer, so it's paired here separately.
    effective: list[tuple[LayerRef, object]] = []
    for layer, value in contributions:
        if isinstance(value, Remove):
            effective = []
        else:
            effective.append((layer, value))

    effective_addresses = {layer.address for layer, _ in effective}
    outcome_by_address: dict[str, str] = {}
    for layer, value in contributions:
        if isinstance(value, Remove):
            outcome_by_address[layer.address] = "removed"
        elif layer.address not in effective_addresses:
            outcome_by_address[layer.address] = "overridden"

    result: object

    if decision.shape == merge_plan.ABSENT:
        result = _ABSENT
    elif decision.applied and strategy in merge_plan.MAP_STRATEGIES:
        for layer, _ in effective:
            outcome_by_address[layer.address] = "merged"
        keys = dict.fromkeys(key for _, d in effective for key in d)
        merged: dict = {}
        for key in keys:
            child_path = f"{key_path}/{key}" if key_path else key
            child_address = f"{address}/{key}" if address else key
            child_contributions = [(layer, d[key]) for layer, d in effective if key in d]
            child_value = _record_for_path(
                records,
                child_address,
                child_path,
                child_contributions,
                merge_policies,
                decision.children_ambient,
            )
            if child_value is not _ABSENT:
                merged[key] = child_value
        result = merged
    elif decision.applied and strategy in list_merge.LIST_STRATEGIES:
        for layer, _ in effective:
            outcome_by_address[layer.address] = "merged"
        tuple_keys = policy.tuple_keys if policy else None
        result = merge_lists(key_path, [v for _, v in effective], strategy, tuple_keys, merge_policies)
        if list_merge.merges_elements_as_maps(strategy):
            _records_inside_fold(records, address, key_path, effective, decision, merge_policies)
    else:
        winner_layer, winner_value = effective[-1]
        outcome_by_address[winner_layer.address] = "won"
        for layer, _ in effective[:-1]:
            outcome_by_address[layer.address] = "overridden"
        result = winner_value

    contributors = [
        {
            "layer": layer.address,
            "value": _strip_removes(value),
            "outcome": outcome_by_address[layer.address],
        }
        for layer, value in reversed(contributions)  # most-specific-first
    ]

    record: dict = {
        "policy": {"strategy": strategy, "pattern": policy.pattern if policy else None},
        "contributors": contributors,
    }
    if result is _ABSENT:
        record["removed"] = True
    elif isinstance(result, Vault):
        record["redacted"] = "vault"
    else:
        record["value"] = result

    records[address] = record
    return result


def compute_rsop(host: LoadedHost, merge_policies: list[MergePolicy]) -> dict[str, dict]:
    """The full `rsop:` map for one loaded (and already-validated) host."""

    records: dict[str, dict] = {}
    keys = dict.fromkeys(key for _layer, data in host.layers for key in data)
    for key in keys:
        contributions = [(layer, data[key]) for layer, data in host.layers if key in data]
        _record_for_path(records, key, key, contributions, merge_policies, ambient_strategy="first")
    return records


def rsop_source(source_arg: str | None, host: str | None, output: str | None) -> RsopResult:
    """Run configure/enumerate/load/validate (exactly as `compile` does, so
    the same diagnostics fire the same way) and render the target host's
    RSOP document without ever running resolve or emit."""

    try:
        config: SourceConfig = configure_phase.configure(source_arg)

        argument_collector = DiagnosticCollector("configure")
        configure_phase.check_host_argument(host, argument_collector)
        _check_output_path(output, config.root, argument_collector)
        argument_collector.raise_if_any()

        enumerated = enumerate_phase.enumerate_hosts(config)

        host_collector = DiagnosticCollector("enumerate")
        if host not in {plan.name for plan in enumerated.hosts}:
            host_collector.add("enumerate.rsop_host_not_found")
        host_collector.raise_if_any()

        loaded = load_phase.load_layers(enumerated.hosts, config.secret_backend)
        validated = validate_phase.validate(
            loaded, config.merge_policies, config.secrets, config.defaults
        )

        target = next(h for h in validated if h.name == host)
        document = {
            "rsop_meta": {
                "compiler_version": COMPILER_VERSION,
                "spec_version": SPEC_VERSION,
                "host": host,
            },
            "rsop": compute_rsop(target, config.merge_policies),
        }
    except PhaseFailed as exc:
        return RsopResult(diagnostics=exc.diagnostics, text=None)

    return RsopResult(diagnostics=[], text=dump_pinned(document))
