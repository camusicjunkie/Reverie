"""The `reverie rsop` verb -- a per-host provenance document (issue #38).

Distinct from the artifact (CONTEXT.md "RSOP"): a flat map of key path to
record, showing every contributor and the losers, not just the winner.
Generated on demand, never committed, and a pure function of
`(source tree, host)` -- it never reads the artifact and works correctly
even in a checkout where `compile` has never been run.

Coverage is total: every key path any walked layer touches gets a record,
intermediate maps included. Each record carries exactly one of `value:`,
`redacted:`, `removed: true`, plus the `policy` that governed it (the
declared strategy/pattern, or the ambient one it inherited) and its
`contributors`, most-specific-first.

The merge mechanics mirror `resolve._merge_key` exactly (same ambient-
inheritance rule, same shape-mismatch fallback to most-specific-wins), with
list merging delegated straight to `resolve._merge_lists` so a list's
*value* here is always identical to what `compile` would emit for it --
only the contributor bookkeeping is new. Per CONTEXT.md's `Contributor`
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

from reverie import list_merge
from reverie.errors import Diagnostic, DiagnosticCollector, PhaseFailed
from reverie.phases import configure as configure_phase
from reverie.phases import enumerate as enumerate_phase
from reverie.phases import load as load_phase
from reverie.phases import validate as validate_phase
from reverie.phases.configure import MergePolicy, SourceConfig
from reverie.phases.enumerate import LayerRef
from reverie.phases.load import LoadedHost
from reverie.phases.resolve import merge_lists
from reverie import keypath
from reverie.version import COMPILER_VERSION, SPEC_VERSION
from reverie.yaml_io import Remove, Vault, dump_pinned

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


def _record_for_path(
    records: dict[str, dict],
    key_path: str,
    contributions: list[tuple[LayerRef, object]],
    merge_policies: list[MergePolicy],
    ambient_strategy: str,
) -> object:
    """Compute the record for one key path, store it in `records`, and
    return its resolved value (or `_ABSENT` if removed) for the parent
    map merge to fold in -- the same shape `resolve._merge_key` returns."""

    effective: list[tuple[LayerRef, object]] = []
    for layer, value in contributions:
        if isinstance(value, Remove):
            effective = []
        else:
            effective.append((layer, value))

    policy = keypath.winner(merge_policies, key_path)
    strategy = policy.strategy if policy else ambient_strategy

    effective_addresses = {layer.address for layer, _ in effective}
    outcome_by_address: dict[str, str] = {}
    for layer, value in contributions:
        if isinstance(value, Remove):
            outcome_by_address[layer.address] = "removed"
        elif layer.address not in effective_addresses:
            outcome_by_address[layer.address] = "overridden"

    result: object

    if not effective:
        result = _ABSENT
    elif strategy in ("shallow", "deep") and all(isinstance(v, dict) for _, v in effective):
        for layer, _ in effective:
            outcome_by_address[layer.address] = "merged"
        child_ambient = "deep" if strategy == "deep" else "first"
        keys = dict.fromkeys(key for _, d in effective for key in d)
        merged: dict = {}
        for key in keys:
            child_path = f"{key_path}/{key}" if key_path else key
            child_contributions = [(layer, d[key]) for layer, d in effective if key in d]
            child_value = _record_for_path(records, child_path, child_contributions, merge_policies, child_ambient)
            if child_value is not _ABSENT:
                merged[key] = child_value
        result = merged
    elif strategy in list_merge.LIST_STRATEGIES and all(isinstance(v, list) for _, v in effective):
        for layer, _ in effective:
            outcome_by_address[layer.address] = "merged"
        tuple_keys = policy.tuple_keys if policy else None
        result = merge_lists(key_path, [v for _, v in effective], strategy, tuple_keys, merge_policies)
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

    records[key_path] = record
    return result


def compute_rsop(host: LoadedHost, merge_policies: list[MergePolicy]) -> dict[str, dict]:
    """The full `rsop:` map for one loaded (and already-validated) host."""

    records: dict[str, dict] = {}
    keys = dict.fromkeys(key for _layer, data in host.layers for key in data)
    for key in keys:
        contributions = [(layer, data[key]) for layer, data in host.layers if key in data]
        _record_for_path(records, key, contributions, merge_policies, ambient_strategy="first")
    return records


def rsop_source(source_arg: str | None, host: str, output: str | None) -> RsopResult:
    """Run configure/enumerate/load/validate (exactly as `compile` does, so
    the same diagnostics fire the same way) and render the target host's
    RSOP document without ever running resolve or emit."""

    try:
        config: SourceConfig = configure_phase.configure(source_arg)

        output_collector = DiagnosticCollector("configure")
        _check_output_path(output, config.root, output_collector)
        output_collector.raise_if_any()

        enumerated = enumerate_phase.enumerate_hosts(config)

        host_collector = DiagnosticCollector("enumerate")
        if host not in {plan.name for plan in enumerated.hosts}:
            host_collector.add("enumerate.rsop_host_not_found")
        host_collector.raise_if_any()

        loaded = load_phase.load_layers(enumerated.hosts, config.secret_backend)
        validated = validate_phase.validate(loaded, config.merge_policies, config.secrets)

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
