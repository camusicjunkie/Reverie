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

Which merges those are, and what each binds to, is `reverie.merge_walk`'s
(issue #57): this module consumes the same walk `resolve` executes and
`validate` judges, and keeps no traversal of its own. A record's value is
`resolve.merged_value` of the merge that produced it, so an RSOP value is
the artifact's value by construction rather than by agreement. What is left
here, and all that is left, is the per-layer contributor bookkeeping and
the writing of an address. Per CONTEXT.md's `Contributor` entry, a layer's
contribution at a key path resolves to exactly one of:

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

from reverie import merge_walk
from reverie.errors import Diagnostic, DiagnosticCollector, PhaseFailed
from reverie.phases import configure as configure_phase
from reverie.phases import enumerate as enumerate_phase
from reverie.phases import load as load_phase
from reverie.phases import resolve as resolve_phase
from reverie.phases import validate as validate_phase
from reverie.phases.configure import MergePolicy, SourceConfig
from reverie.phases.load import LoadedHost
from reverie.version import COMPILER_VERSION, SPEC_VERSION
from reverie.yaml_io import Remove, Vault, dump_flow_scalar, dump_pinned


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


def _element_selector(selector: merge_walk.ElementSelector) -> str:
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

    pairs = ",".join(
        f"{key}={dump_flow_scalar(selector.element[key])}" for key in selector.tuple_keys
    )
    return f"[{pairs}]"


def render_address(steps: tuple[str | merge_walk.ElementSelector, ...]) -> str:
    """One merge's address written down, as a reader of the document
    addresses it (CONTEXT.md "RSOP address").

    The walk hands an address over as steps (`merge_walk.Merge.address`);
    this writes them. A map key is a `/`-separated segment; an element
    selector binds tight to the list key it names, because it selects
    within that step rather than descending a further one --
    `local_groups/groups[name=Administrators]/members`.

    Public because it is half of `compute_rsop`'s contract: the records are
    keyed by rendered address, so anything asking whether a given merge was
    reported -- the coverage tests over the walk do -- has to be able to
    render the address it would have been filed under.
    """

    rendered = ""
    for step in steps:
        if isinstance(step, merge_walk.ElementSelector):
            rendered += _element_selector(step)
        elif rendered:
            rendered += f"/{step}"
        else:
            rendered = step
    return rendered


def _outcomes(merge: merge_walk.Merge) -> dict[str, str]:
    """What each contributing layer's contribution to `merge` came to, by
    layer address -- the bookkeeping CONTEXT.md's `Contributor` entry
    defines, and the one thing about a merge this module works out for
    itself.

    Every layer that contributed lands in exactly one of the four
    outcomes. A `!remove` is `removed`; a contribution the `!remove` resets
    cleared, or one a winner superseded, is `overridden`; what is left
    follows the kind of merge it was -- folded in (`merged`) where a map or
    list strategy applied, or the sole survivor (`won`) where the most
    specific contribution won outright.
    """

    surviving = {contribution.layer.address for contribution in merge.effective}
    outcomes: dict[str, str] = {}
    for contribution in merge.contributions:
        if isinstance(contribution.value, Remove):
            outcomes[contribution.layer.address] = "removed"
        elif contribution.layer.address not in surviving:
            outcomes[contribution.layer.address] = "overridden"

    if merge.kind in (merge_walk.MAP, merge_walk.LIST):
        for contribution in merge.effective:
            outcomes[contribution.layer.address] = "merged"
    elif merge.kind == merge_walk.MOST_SPECIFIC_WINS:
        for contribution in merge.effective[:-1]:
            outcomes[contribution.layer.address] = "overridden"
        outcomes[merge.effective[-1].layer.address] = "won"
    # REMOVED leaves nothing surviving, so the loop above already named
    # every contribution `removed` or `overridden`.

    return outcomes


def _record(merge: merge_walk.Merge) -> dict:
    """The record for one merge of the walk.

    The value is `resolve`'s (`resolve.merged_value`) -- the same function
    `compile` emits from, so a record's `value:` is the value the artifact
    holds and cannot drift from it. The policy is the walk's binding
    decision. Only the contributors are computed here.
    """

    outcomes = _outcomes(merge)
    value = resolve_phase.merged_value(merge)
    policy = merge.decision.policy

    record: dict = {
        "policy": {
            "strategy": merge.decision.strategy,
            "pattern": policy.pattern if policy else None,
        },
        "contributors": [
            {
                "layer": contribution.layer.address,
                "value": _strip_removes(contribution.value),
                "outcome": outcomes[contribution.layer.address],
            }
            for contribution in reversed(merge.contributions)  # most-specific-first
        ],
    }

    if value is resolve_phase.ABSENT:
        record["removed"] = True
    elif isinstance(value, Vault):
        record["redacted"] = "vault"
    else:
        record["value"] = value
    return record


def compute_rsop(host: LoadedHost, merge_policies: list[MergePolicy]) -> dict[str, dict]:
    """The full `rsop:` map for one loaded (and already-validated) host.

    One record per merge the host performs, which is every merge
    `merge_walk` yields and no others -- so coverage is the walk's
    (fold interiors included, issue #48) rather than a traversal of this
    module's own, and a key path cannot be merged without being reported.
    """

    return {
        render_address(merge.address): _record(merge)
        for merge in merge_walk.merges(merge_walk.walk(host, merge_policies))
    }


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
