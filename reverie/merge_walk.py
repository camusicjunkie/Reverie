"""The order in which one host's merges happen (issue #53).

`merge_plan.bind` answers *what* a single key path binds to. This module
answers *which* key paths a host binds at, and in what order: it walks a
loaded host's layer stack once and yields every merge that host performs,
in the order `resolve` reaches them.

Three consumers need that traversal and used to each write their own copy
of it -- `resolve` to execute the merges, `validate` to judge the binding
decisions, `rsop` to attribute the contributors. The copies re-derived the
same five rules (gather a key's per-layer contributions, extend the key
path, bind, recurse into a map where the strategy applied, fold each
`deep_tuple` element group of two or more at the list's own key path under
ambient `first`), and twice in one fortnight a copy diverged: a merge
policy inside a folded element that `resolve` executed and `validate`
rejected (issue #47), and fold interiors `resolve` merged and `rsop` filed
no record for (issue #48).

All three now consume this walk and keep no traversal of their own, so the
rules live in one place and a divergence of the kind issues #47 and #48
recorded has nowhere left to arise: a merge a consumer reports is a merge
the walk yielded, and a merge the walk yields is one `resolve` executes.

The walk computes no values and raises nothing. A `Merge` carries what the
merge *is*: the key path that bound it, the RSOP address it is filed
under, the binding decision, and every contribution paired with the layer
it came from. Turning that into a merged value is `resolve`'s
(`resolve.merged_value`), into a diagnostic `validate`'s, into a
provenance record `rsop`'s.

A `Merge` is also a tree node, not just a stream element: `children` are
the merges inside a map-strategy merge and `elements` the elements of a
list-strategy one, so a consumer that assembles a value bottom-up can
recurse, while one that only inspects decisions takes the flat pre-order
stream from `merges`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Sequence

from reverie import list_merge, merge_plan
from reverie.phases.configure import MergePolicy
from reverie.phases.enumerate import LayerRef
from reverie.phases.load import LoadedHost

# What one merge does with its contributions -- the four outcomes a binding
# decision can have, classified once here rather than by each consumer
# re-reading `applied`/`strategy`/`shape` for itself.
REMOVED = "removed"  # every contribution was `!remove`d away; nothing is merged
MOST_SPECIFIC_WINS = "most_specific_wins"  # `first`, or a shape mismatch falling back to it
MAP = "map"  # `shallow`/`deep` against map-shaped values
LIST = "list"  # a list strategy against list-shaped values


@dataclass(frozen=True)
class Contribution:
    """One layer's value at one key path, before the merge."""

    layer: LayerRef
    value: Any


@dataclass(frozen=True)
class ElementSelector:
    """The identity of one folded element of a list (CONTEXT.md "RSOP address").

    The declared `tuple_keys`, in declaration order, and the group's
    representative element to read them from -- element identity exactly as
    the merge itself computed it. Rendering this as `[name=Administrators]`
    is RSOP's own concern; the walk only needs to say *which* element the
    merges beneath it belong to.
    """

    tuple_keys: tuple[str, ...]
    element: dict


@dataclass(frozen=True)
class Element:
    """One element a list merge keeps, and the merges inside it, if any.

    `contributions` is the element group (CONTEXT.md "Element group"),
    most-general-first. A group of one is never merged, and no strategy but
    `deep_tuple` merges inside the elements it matches -- either way
    `interior` is empty and `selector` is None, and the element the merge
    emits is simply the most specific contribution.
    """

    contributions: tuple[Contribution, ...]
    selector: ElementSelector | None
    interior: tuple["Merge", ...]

    @property
    def folded(self) -> bool:
        return self.selector is not None


@dataclass(frozen=True)
class Merge:
    """One merge a host performs.

    `key_path` is what bound the policy; `address` is where RSOP files the
    record -- a tuple of steps, each a map key, or an `ElementSelector`
    naming the folded element whose interior follows. The two differ
    exactly below a `deep_tuple` fold, where one key path is merged once
    per element group.
    """

    key: str
    key_path: str
    address: tuple[str | ElementSelector, ...]
    decision: merge_plan.BindingDecision
    # Every layer's contribution, most-general-first, `!remove` included --
    # and the ones surviving the `!remove` resets, which are what the merge
    # actually operates on.
    contributions: tuple[Contribution, ...]
    effective: tuple[Contribution, ...]
    # Populated for exactly one kind each: `children` for MAP, `elements`
    # for LIST.
    children: tuple["Merge", ...]
    elements: tuple[Element, ...]

    @property
    def kind(self) -> str:
        return kind(self.decision)


def kind(decision: merge_plan.BindingDecision) -> str:
    """What a merge under `decision` does with its contributions."""

    if decision.shape == merge_plan.ABSENT:
        return REMOVED
    if decision.applied and decision.strategy in merge_plan.MAP_STRATEGIES:
        return MAP
    if decision.applied and decision.strategy in list_merge.LIST_STRATEGIES:
        return LIST
    return MOST_SPECIFIC_WINS


def walk(host: LoadedHost, merge_policies: list[MergePolicy]) -> tuple[Merge, ...]:
    """Every merge `host` performs, as the merges at its top-level keys.

    The layer stack itself is merged as a map at the empty key path under
    ambient `first`, so a top-level key inherits `first` unless a policy
    declares otherwise -- the stack is not a value any layer contributed,
    so there is no merge to report for it, only the merges it contains.
    """

    layers = tuple(Contribution(layer, data) for layer, data in host.layers)
    return _children("", (), layers, "first", merge_policies)


def merges(nodes: Iterable[Merge]) -> Iterator[Merge]:
    """`nodes` and everything beneath them, pre-order -- every merge before
    the merges it contains, which is the order they bind in: a key path's
    strategy is decided before anything under it is reached. (`resolve`
    assembles the *values* the other way, innermost first, since a map's
    value is made of its children's.)"""

    for node in nodes:
        yield node
        yield from merges(node.children)
        for element in node.elements:
            yield from merges(element.interior)


def _list_elements(
    key_path: str,
    address: tuple[str | ElementSelector, ...],
    effective: Sequence[Contribution],
    decision: merge_plan.BindingDecision,
    merge_policies: list[MergePolicy],
) -> tuple[Element, ...]:
    """The elements one list merge keeps, each with the merges inside it.

    `address` is where the list itself is filed; every fold interior is
    addressed beneath it.
    """

    tuple_keys = decision.policy.tuple_keys if decision.policy else None
    folds = list_merge.merges_elements_as_maps(decision.strategy)
    groups = list_merge.element_groups_by_layer(
        [contribution.value for contribution in effective], decision.strategy, tuple_keys
    )

    elements: list[Element] = []
    for group in groups:
        contributions = tuple(
            Contribution(effective[index].layer, element) for index, element in group
        )
        if folds and len(contributions) > 1:
            # A group of two or more matched under a tuple strategy, so
            # every member is map-shaped -- that is what grouping them
            # established. The fold is one map merge over the whole group,
            # at the list's own key path, under ambient `first`.
            selector = ElementSelector(
                tuple_keys=tuple(tuple_keys or ()), element=contributions[-1].value
            )
            interior = _children(
                key_path, address + (selector,), contributions, "first", merge_policies
            )
        else:
            selector, interior = None, ()
        elements.append(
            Element(contributions=contributions, selector=selector, interior=interior)
        )

    return tuple(elements)


def _children(
    key_path: str,
    address: tuple[str | ElementSelector, ...],
    maps: Sequence[Contribution],
    ambient_strategy: str,
    merge_policies: list[MergePolicy],
) -> tuple[Merge, ...]:
    """The merges inside a map merge of `maps`: one per key any of them
    holds, in first-contribution order."""

    keys = dict.fromkeys(key for contribution in maps for key in contribution.value)
    return tuple(
        _merge(
            key,
            f"{key_path}/{key}" if key_path else key,
            address + (key,),
            tuple(
                Contribution(contribution.layer, contribution.value[key])
                for contribution in maps
                if key in contribution.value
            ),
            ambient_strategy,
            merge_policies,
        )
        for key in keys
    )


def _merge(
    key: str,
    key_path: str,
    address: tuple[str | ElementSelector, ...],
    contributions: tuple[Contribution, ...],
    ambient_strategy: str,
    merge_policies: list[MergePolicy],
) -> Merge:
    decision = merge_plan.bind(
        key_path,
        [contribution.value for contribution in contributions],
        merge_policies,
        ambient_strategy,
    )
    effective = tuple(
        merge_plan.effective_contributions(
            contributions, value_of=lambda contribution: contribution.value
        )
    )

    children: tuple[Merge, ...] = ()
    elements: tuple[Element, ...] = ()
    merge_kind = kind(decision)
    if merge_kind == MAP:
        children = _children(
            key_path, address, effective, decision.children_ambient, merge_policies
        )
    elif merge_kind == LIST:
        elements = _list_elements(key_path, address, effective, decision, merge_policies)

    return Merge(
        key=key,
        key_path=key_path,
        address=address,
        decision=decision,
        contributions=contributions,
        effective=effective,
        children=children,
        elements=elements,
    )
