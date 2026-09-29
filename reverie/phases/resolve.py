"""Phase 5: resolve -- merge each host's layers into its final data.

By design, this phase raises no errors -- anything that could go wrong
with merge data was already caught in `validate`.

Which merges a host performs, and in what order, is `reverie.merge_walk`'s
(issue #53): the most specific *declared* policy for a key path wins
outright, and where nothing is declared the key path inherits the ambient
strategy its parent map is being merged under. The walk is handed to this
phase already produced (issue #60), and it does one thing with it -- turn
each merge into a value, bottom-up:

- nothing, where every contribution was `!remove`d away;
- a map, from the merges inside it;
- a list, one element per element group, folded groups merged as maps;
- the most specific contribution, for `first` and for every shape a
  declared strategy could not bind to.

The list strategies' shared ordering rule -- each distinct element once, at
the position of its first contribution, layers concatenated
most-specific-first -- and `!remove`'s list-element semantics live in
`reverie.list_merge`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from reverie import merge_walk

PHASE = "resolve"

# The value of a merge that resolved to nothing: every contribution to it
# was `!remove`d away, so the key it merged is absent from the result
# rather than present and empty. Named, not private, because it is half of
# `merged_value`'s contract -- comparing against it is the only way a
# caller tells absence from a value.
ABSENT = object()


@dataclass(frozen=True)
class ResolvedHost:
    name: str
    data: dict
    # Ordered most-general to most-specific, the layer addresses this host
    # actually walked -- goes straight into the artifact's reverie_meta.
    layers_walked: list[str]


def merged_value(merge: merge_walk.Merge) -> Any:
    """What one merge of the walk resolves to, or `ABSENT`."""

    kind = merge.kind

    if kind == merge_walk.REMOVED:
        return ABSENT
    if kind == merge_walk.MAP:
        return merged_map(merge.children)
    if kind == merge_walk.LIST:
        return list_value(merge.elements)
    return merge.effective[-1].value


def merged_map(children: Sequence[merge_walk.Merge]) -> dict:
    """The map a map merge resolves to, from the merges inside it.

    A child that resolved to nothing is simply absent -- a removed key
    leaves no trace, not an empty one.
    """

    merged: dict = {}
    for child in children:
        value = merged_value(child)
        if value is not ABSENT:
            merged[child.key] = value
    return merged


def list_value(elements: Sequence[merge_walk.Element]) -> list[Any]:
    """The list a list merge resolves to, one value per element group.

    A folded group resolves to the map its interior merges to; every other
    group keeps its most specific element whole.
    """

    return [
        merged_map(element.interior) if element.folded else element.contributions[-1].value
        for element in elements
    ]


def resolve(host_merges: list[merge_walk.HostMerges]) -> list[ResolvedHost]:
    """Each host's merges turned into its resolved data.

    Takes the walks rather than the hosts and the policies (issue #60):
    which merges a host performs is settled before this phase runs, so
    there is nothing left here to bind, and no policy list to bind it
    with.
    """

    return [
        ResolvedHost(
            name=walked.name,
            data=merged_map(walked.merges),
            layers_walked=walked.layers_walked,
        )
        for walked in host_merges
    ]
