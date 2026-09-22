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


def has_map_element(layer_lists: list[list[object]]) -> bool:
    """Whether any element across `layer_lists` (raw, `Remove` included) is a map."""

    for layer_list in layer_lists:
        for element in layer_list:
            target = element.value if isinstance(element, Remove) else element
            if isinstance(target, dict):
                return True
    return False
