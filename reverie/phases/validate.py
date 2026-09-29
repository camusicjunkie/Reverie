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

The merge-policy checks judge the binding decisions of the shared merge
walk (`reverie.merge_walk`, issue #53) rather than a traversal of this
module's own: whichever merges a host performs are exactly the merges
judged here, structurally rather than by promise. The walk arrives already
produced (issue #60), so the merges judged here are the same objects
`resolve` turns into values -- not a second walk over the same host. What one policy was
seen to do across the estate is one `PolicyObservation`, and the
precedence between the conditions it raises is stated there, beside the
evidence each one reads.

The remaining checks -- removals, in-layer duplicates, plaintext secrets
-- are per-layer rather than per-merge: they ask whether any walked layer
touches a key path at all, winner or not. That is the **path scan**
(`reverie.path_scan`, issue #61), the second named traversal of a host's
layer data, and it is deliberately broader than the walk. This module
keeps no traversal of its own: it scans each host once and judges the
entries, exactly as it judges the merges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from reverie import keypath, list_merge, merge_plan, merge_walk, path_scan
from reverie.errors import DiagnosticCollector
from reverie.phases.configure import MergePolicy
from reverie.yaml_io import Remove, Secret, Vault

PHASE = "validate"

_MAP_STRATEGIES = merge_plan.MAP_STRATEGIES


def _check_removals(
    entries: tuple[path_scan.Entry, ...],
    collector: DiagnosticCollector,
    merge_policies: list[MergePolicy],
) -> None:
    """A `!remove` reaches downward only: it must match something a
    strictly more general (already-scanned) layer defined -- a map key by
    identity, a list element by whichever equality the path's declared
    list strategy uses."""

    seen_paths: set[str] = set()
    seen_list_elements: dict[str, list[object]] = {}

    for entry in entries:
        path, value = entry.key_path, entry.value

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
    entries: tuple[path_scan.Entry, ...],
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

    for entry in entries:
        if not isinstance(entry.value, list):
            continue
        policy = keypath.winner(merge_policies, entry.key_path)
        if policy is None or policy.strategy not in list_merge.COMPARING_STRATEGIES:
            continue
        condition = (
            "validate.duplicate_floor_key"
            if defaults_address is not None and entry.layer.address == defaults_address
            else "validate.duplicate_in_layer"
        )
        elements = [e for e in entry.value if not isinstance(e, Remove)]
        for i, a in enumerate(elements):
            if any(list_merge.elements_equal(a, b, policy.strategy, policy.tuple_keys) for b in elements[i + 1 :]):
                collector.add(condition, file=str(entry.layer.path), line=None)
                break  # one report per key path is enough; keep scanning the layer's other paths


def _check_secrets(
    entries: tuple[path_scan.Entry, ...],
    collector: DiagnosticCollector,
    secrets: list[str],
) -> None:
    """A plaintext value at a declared secret key path, in any walked layer.

    Checked over every layer, not just the winner -- a non-winning layer's
    plaintext is exactly as much of a leak risk sitting in git history
    (ADR 0006).
    """

    if not secrets:
        return

    for entry in entries:
        if isinstance(entry.value, (dict, list, Remove, Vault, Secret)):
            continue
        if any(keypath.matches(pattern, entry.key_path) for pattern in secrets):
            collector.add("validate.secret_is_plaintext", layer=str(entry.layer.path))


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


@dataclass
class PolicyObservation:
    """What one declared `merge:` policy was seen to do, across the estate.

    Every policy-scoped verdict rests on five observations, and they are
    gathered here rather than in five estate-wide sets whose intersection a
    reader has to compute by hand. Evidence arrives from the two
    traversals and only through the `saw_*` methods below: `saw_merge`
    folds in the shared merge walk's decisions as they stream past, and
    `saw_path_match` /
    `saw_vault_comparison` the findings of the path scan
    (`reverie.path_scan`), which is deliberately broader than the merges
    the walk performs.
    """

    policy: MergePolicy
    # Any walked layer touches a key path this pattern matches -- broader
    # than "the walk bound this policy somewhere", so a policy shadowed
    # under an ancestor's `first` still counts as matching something.
    matched_a_path: bool = False
    # The strategy won against the shape it is *for*: a map for
    # `shallow`/`deep`, a plain list for `append`/`unique`, a list of maps
    # for the tuple strategies. A plain-list strategy binding to a list of
    # maps is a merge that ran, but not the one that was declared.
    applied_to_its_shape: bool = False
    met_plain_list_under_tuple: bool = False
    element_missing_tuple_key: bool = False
    compared_vault: bool = False

    def saw_path_match(self) -> None:
        """Some walked layer touches a key path this pattern matches."""

        self.matched_a_path = True

    def saw_vault_comparison(self) -> None:
        """A comparing strategy under this policy reached `!vault`
        ciphertext, whose salting makes the comparison meaningless
        (ADR 0006)."""

        self.compared_vault = True

    def saw_merge(self, merge: merge_walk.Merge) -> None:
        """Fold in one merge of the walk that this policy won."""

        decision = merge.decision
        if not decision.applied:
            return

        if self.policy.strategy in _MAP_STRATEGIES:
            self.applied_to_its_shape = True
        elif self.policy.strategy in list_merge.PLAIN_LIST_STRATEGIES:
            self.applied_to_its_shape |= decision.shape == merge_plan.LIST_PLAIN
        elif self.policy.strategy in list_merge.TUPLE_STRATEGIES:
            if decision.shape == merge_plan.LIST_OF_MAPS:
                self.applied_to_its_shape = True
                self.element_missing_tuple_key |= _tuple_keys_missing(
                    [contribution.value for contribution in merge.effective],
                    self.policy.tuple_keys,
                )
            else:
                self.met_plain_list_under_tuple = True

    @property
    def never_applied(self) -> bool:
        """Whether this policy asked for an operation no host ever performed.

        `first` is total on every shape, so it can never be the answer to
        this question. A tuple strategy that only ever met a plain list is
        exempt: it has a more specific finding of its own, below.
        """

        if self.policy.strategy not in _MAP_STRATEGIES + list_merge.LIST_STRATEGIES:
            return False
        return not self.applied_to_its_shape and not self.met_plain_list_under_tuple

    def conditions(self) -> Iterator[tuple[str, dict]]:
        """Every policy-scoped condition this policy raises, with its fields.

        The precedence, which is contract:

        - a pattern no layer touches reports `pattern_matches_nothing`
          rather than `strategy_never_applies` -- whether its strategy
          could have applied is unanswerable when there was nothing to
          apply it to. It is in practice the only condition such a policy
          reaches, since the other three are findings about merges that
          did happen and the path scan is broader than the walk, but that
          is a consequence of the evidence, not a rule enforced here;
        - a tuple strategy that only ever met a plain list reports
          `non_map_in_tuple_merge` *instead of* `strategy_never_applies`,
          the specific finding displacing the general one about the same
          fault (see `never_applied`);
        - `secret_not_comparable` and `missing_tuple_key` are findings
          about merges that did happen, so they sit beside whichever
          verdict the cascade reaches rather than competing with it.
        """

        pattern = self.policy.pattern

        if self.compared_vault:
            yield "validate.secret_not_comparable", {"key_path": pattern}
        if self.element_missing_tuple_key:
            yield "validate.missing_tuple_key", {}
        if self.met_plain_list_under_tuple:
            yield "validate.non_map_in_tuple_merge", {}

        if not self.matched_a_path:
            yield "validate.pattern_matches_nothing", {"pattern": pattern}
        elif self.never_applied:
            yield "validate.strategy_never_applies", {"key_path": pattern}


def validate(
    host_merges: list[merge_walk.HostMerges],
    merge_policies: list[MergePolicy],
    secrets: list[str] | None = None,
    defaults_address: str | None = None,
) -> None:
    """Judge every host's merges, and raise if anything is wrong.

    Takes the walks rather than the hosts (issue #60), but keeps
    `merge_policies`: a verdict is owed for every *declared* policy,
    including the ones no merge ever bound, and the path scan reads them
    too. Returns nothing -- this phase is a checkpoint, and handing back
    the list it was given would claim a transform it never performs.
    """

    collector = DiagnosticCollector(PHASE)
    secrets = secrets or []

    # Each host is scanned once and walked once, and every verdict below
    # reads one of those two (issue #61).
    scanned = [path_scan.scan(walked.host, merge_policies) for walked in host_merges]

    for entries in scanned:
        _check_removals(entries, collector, merge_policies)
        _check_duplicates_in_layer(entries, collector, merge_policies, defaults_address)
        _check_secrets(entries, collector, secrets)

    observations = {policy.pattern: PolicyObservation(policy) for policy in merge_policies}

    values_by_path = path_scan.values_by_key_path(
        entry for entries in scanned for entry in entries
    )

    for path, values in values_by_path.items():
        for policy in merge_policies:
            if keypath.matches(policy.pattern, path):
                observations[policy.pattern].saw_path_match()

        list_values = [v for v in values if isinstance(v, list)]
        for policy in keypath.best_match(merge_policies, path):
            if policy.strategy in list_merge.COMPARING_STRATEGIES and list_values:
                elements = [
                    element.value if isinstance(element, Remove) else element
                    for layer_list in list_values
                    for element in layer_list
                ]
                if list_merge.has_vault_comparison(elements, policy.strategy, policy.tuple_keys):
                    observations[policy.pattern].saw_vault_comparison()

    for walked in host_merges:
        # A host whose every top-level key resolved away (or that never had
        # one) emits an artifact with an empty `reverie:` -- inert, and
        # almost always a mis-declared chain rather than an intent.
        if all(merge.decision.shape == merge_plan.ABSENT for merge in walked.merges):
            collector.add("validate.host_has_no_keys", host=walked.name)

        for merge in merge_walk.merges(walked.merges):
            policy = merge.decision.policy
            if policy is not None:
                observations[policy.pattern].saw_merge(merge)

    for pattern in secrets:
        if not any(keypath.matches(pattern, path) for path in values_by_path):
            collector.add("validate.secrets_pattern_matches_nothing", pattern=pattern)

    for policy in merge_policies:
        for condition, fields in observations[policy.pattern].conditions():
            collector.add(condition, **fields)

    collector.raise_if_any()
