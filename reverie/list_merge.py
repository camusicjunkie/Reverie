"""Shared list-strategy mechanics for resolve and validate (issue #34).

One ordering rule covers all four list strategies (`append`, `unique`,
`unique_tuple`, `deep_tuple`): each distinct element once, at the position
of its first contribution, with layers concatenated most-specific-first.
They differ only in what "the same element" means: nothing for `append`,
the whole value for `unique`, `tuple_keys` for the two tuple strategies.

Shape is classified over the concatenation of every contributing layer's
list: any map present anywhere makes it list-of-maps; otherwise it's a
*plain list*, whatever its elements -- scalars, nested lists, or a mix
(design tracker #24).
"""

from __future__ import annotations

from reverie.yaml_io import Remove, Vault

PLAIN_LIST_STRATEGIES = ("append", "unique")
TUPLE_STRATEGIES = ("unique_tuple", "deep_tuple")
LIST_STRATEGIES = PLAIN_LIST_STRATEGIES + TUPLE_STRATEGIES

# Strategies that compare elements to one another at all -- `append` never
# does, so it can never produce a `validate.duplicate_in_layer`.
COMPARING_STRATEGIES = ("unique", "unique_tuple", "deep_tuple")


def exact_equal(a: object, b: object) -> bool:
    """Same type, same value -- no coercion, no case folding (design tracker #21)."""

    return type(a) is type(b) and a == b


def elements_equal(a: object, b: object, strategy: str, tuple_keys: tuple[str, ...] | None) -> bool:
    """Whether `a` and `b` count as "the same element" under `strategy`."""

    if strategy == "append":
        return False
    if strategy == "unique":
        return exact_equal(a, b)
    # unique_tuple / deep_tuple: same tuple_keys, both map-shaped.
    if not tuple_keys or not isinstance(a, dict) or not isinstance(b, dict):
        return False
    return all(key in a and key in b and exact_equal(a[key], b[key]) for key in tuple_keys)


def _compared_values(element: object, strategy: str, tuple_keys: tuple[str, ...] | None) -> tuple[object, ...]:
    """The value(s) `elements_equal` actually inspects for `element` under `strategy`."""

    if strategy == "unique":
        return (element,)
    if tuple_keys and isinstance(element, dict):
        return tuple(element[key] for key in tuple_keys if key in element)
    return ()


def has_vault_comparison(elements: list[object], strategy: str, tuple_keys: tuple[str, ...] | None) -> bool:
    """Whether comparing `elements` under `strategy` would inspect a `!vault` scalar.

    Salting makes ciphertext comparison meaningless (ADR 0006) -- `unique`
    and the tuple strategies must never silently compare a `!vault`
    scalar's content, whether as a whole element (`unique`) or as one of
    its `tuple_keys` fields (`unique_tuple`/`deep_tuple`).
    """

    return any(
        isinstance(value, Vault)
        for element in elements
        for value in _compared_values(element, strategy, tuple_keys)
    )


def merges_elements_as_maps(strategy: str) -> bool:
    """Whether `strategy` merges the elements it matches as maps.

    Only `deep_tuple` does. `unique_tuple` keeps the more specific element
    whole, and `append`/`unique` never look inside an element at all -- so
    `deep_tuple` alone gives the keys of its elements real key paths (the
    list's own path, extended), and a merge policy addressed there binds to
    something only under it (issue #47).
    """

    return strategy == "deep_tuple"


def element_groups_by_layer(
    layer_lists: list[list[object]],
    strategy: str,
    tuple_keys: tuple[str, ...] | None,
) -> list[list[tuple[int, object]]]:
    """`element_groups`, with each element paired to the index of the layer
    list it came from.

    Only `reverie.rsop` needs the pairing -- a record inside a folded
    element attributes its contributors, so it has to know which layer
    contributed each one, where `resolve` and `validate` care only about
    the values. The grouping itself is one algorithm either way, so it
    lives here once and `element_groups` drops the indices.
    """

    removal_targets: list[object] = []
    groups: list[list[tuple[int, object]]] = []

    for index in reversed(range(len(layer_lists))):  # most-specific-first
        layer_list = layer_lists[index]
        layer_removals = [element.value for element in layer_list if isinstance(element, Remove)]

        for element in layer_list:
            if isinstance(element, Remove):
                continue  # contributes a match, not an element -- holds no position
            if any(elements_equal(element, target, strategy, tuple_keys) for target in removal_targets):
                continue
            # A group's representative is its most specific element, the
            # one a comparing strategy keeps.
            group = next(
                (
                    existing
                    for existing in groups
                    if elements_equal(element, existing[-1][1], strategy, tuple_keys)
                ),
                None,
            )
            if group is not None:
                group.insert(0, (index, element))  # more general than everything already in it
            else:
                groups.append([(index, element)])

        removal_targets.extend(layer_removals)

    return groups


def element_groups(
    layer_lists: list[list[object]],
    strategy: str,
    tuple_keys: tuple[str, ...] | None,
) -> list[list[object]]:
    """The kept elements of a list merge, each as the group of contributions
    that count as "the same element" -- most-general-first within a group,
    the groups themselves in the order the merge emits them.

    This is the whole of the ordering rule above, and the whole of
    `!remove`'s list-element semantics, in one place: a `!remove` holds no
    position and reaches only *downward*, matching elements contributed by
    strictly more general layers.

    `resolve.merge_lists` turns each group into one element (for
    `deep_tuple`, by merging it as a map), and `validate` walks the same
    groups to see the key paths that merge will visit -- so the two agree
    by construction rather than by coincidence (issue #47). A group of one
    is never merged at all, under any strategy: its lone element is already
    the answer, so nothing beneath it is ever visited.
    """

    return [
        [element for _index, element in group]
        for group in element_groups_by_layer(layer_lists, strategy, tuple_keys)
    ]


def has_map_element(layer_lists: list[list[object]]) -> bool:
    """Whether any element across `layer_lists` (raw, `Remove` included) is a map."""

    for layer_list in layer_lists:
        for element in layer_list:
            target = element.value if isinstance(element, Remove) else element
            if isinstance(target, dict):
                return True
    return False
