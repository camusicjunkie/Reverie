"""`reverie.yml` read once, with every field carrying its position.

`configure` is the only phase that reads `reverie.yml` (CONTEXT.md
"Phase"), and every diagnostic it raises about the file needs two things of
a field: the value, to check its shape against the schema, and the position,
to point the operator at the line that is wrong. This module hands over
both at once.

One read, one parse. PyYAML's loader composes the node tree and constructs
the document from that same tree, so values and positions come out of a
single pass rather than a `safe_load` for the values and a `compose` for
the lines stitched back together per field.

A `Field` is one field of that document: its value, its line, and the
document's path. Navigation (`field`, `elements`, `entries`) yields more
`Field`s, so a position is never something a caller walks nodes to find;
`shaped` is the one shape test; `report` is the one path a diagnostic about
a field goes through. What fields exist, what shapes they take, and what
each violation is called stay with `configure` -- this module knows the
mechanics, not the schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from reverie.errors import DiagnosticCollector


@dataclass(frozen=True)
class Field:
    """One field of `reverie.yml`: its value and its position, together.

    `present` is whether the field was written at all, which is distinct
    from holding null: `defaults:` with nothing after it is a declaration
    of null, while no `defaults:` line is no declaration. `configure`'s
    defaults differ between the two, so the read preserves the difference
    rather than collapsing both to None.
    """

    value: Any
    file: str
    present: bool = True
    node: yaml.Node | None = None

    @property
    def line(self) -> int | None:
        """The 1-based line the field's value starts on, or None if absent."""

        return self.node.start_mark.line + 1 if self.node is not None else None

    def field(self, name: str) -> Field:
        """The named member of this field, absent if this field is not a
        mapping or does not declare it."""

        if not isinstance(self.value, dict) or name not in self.value:
            return Field(value=None, file=self.file, present=False)
        return Field(value=self.value[name], file=self.file, node=self._child_node(name))

    def key_line(self, name: str) -> int | None:
        """The 1-based line the named key itself is written on, or None.

        `field(name).line` is the line the key's *value* starts on, which
        for a block mapping or sequence is the line below. A diagnostic
        about the key -- a declaration the schema does not have -- has to
        point at the key, so it reads its position here rather than off
        the value it introduces.
        """

        if isinstance(self.node, yaml.MappingNode):
            for key_node, _value_node in self.node.value:
                if isinstance(key_node, yaml.ScalarNode) and key_node.value == name:
                    return key_node.start_mark.line + 1
        return None

    def _child_node(self, name: str) -> yaml.Node | None:
        if isinstance(self.node, yaml.MappingNode):
            for key_node, value_node in self.node.value:
                if isinstance(key_node, yaml.ScalarNode) and key_node.value == name:
                    return value_node
        return None

    def elements(self) -> list[Field]:
        """This field's elements, in order, empty if it is not a sequence."""

        if not isinstance(self.value, list):
            return []
        nodes = self.node.value if isinstance(self.node, yaml.SequenceNode) else []
        return [
            Field(value=value, file=self.file, node=nodes[index] if index < len(nodes) else None)
            for index, value in enumerate(self.value)
        ]

    def entries(self) -> list[tuple[Any, Field]]:
        """This field's `(key, value field)` pairs, in declaration order,
        empty if it is not a mapping."""

        if not isinstance(self.value, dict):
            return []
        return [(key, self.field(key)) for key in self.value]

    def shaped(self, shape: type) -> Any | None:
        """This field's value if it has `shape`, otherwise None.

        The one shape test, so `isinstance` conventions don't multiply one
        per field. A field holding null answers None for every shape, which
        is what `configure` wants of an optional field written empty.
        """

        return self.value if isinstance(self.value, shape) else None

    def report(self, collector: DiagnosticCollector, condition: str, **fields) -> None:
        """Report `condition` against this field.

        The one path a configure-phase diagnostic about a field goes
        through. `file` is the document's; every other key the registry
        declares for the condition is the caller's to pass, including
        `line`, written as `line=field.line` -- which is the point: a
        position is read off the field, never recovered by a walk over the
        node tree at the call site. What each condition carries stays a
        statement `configure` makes, since it owns the schema.
        """

        collector.add(condition, file=self.file, **fields)


@dataclass(frozen=True)
class DuplicateKey:
    """A key written a second (or later) time in one mapping: the key and
    the line the repeated declaration sits on."""

    key: Any
    line: int


class DuplicateKeysError(Exception):
    """The document declares a key twice in one mapping, at any depth.

    PyYAML's own rule is last-one-wins, silently, so the earlier
    declaration would vanish from the constructed document. The read is
    where the node tree is composed, so it is where that is visible --
    `load`'s layer files are held to the same rule. Naming the condition
    is `configure`'s to do, as for `yaml.YAMLError`; `duplicates` carries
    one entry per repeated declaration, in document order.
    """

    def __init__(self, duplicates: list[DuplicateKey]):
        self.duplicates = duplicates
        super().__init__(f"duplicate keys: {[(d.key, d.line) for d in duplicates]}")


def _duplicate_keys(root: yaml.Node | None) -> list[DuplicateKey]:
    """Every repeated key in every mapping under `root`, in document order.

    Keys are compared as written (resolved tag and text), so `1` and `"1"`
    stay distinct, as they do once constructed. A node reached twice
    through an alias is walked once, which also keeps a self-referencing
    anchor from looping. A duplicate inside an aliased mapping is thus
    reported once, at the repeated declaration in the anchored text: that
    is the line written twice, and naming it again at each `*alias` would
    point at lines where nothing is.
    """

    found: list[DuplicateKey] = []
    seen_nodes: set[int] = set()

    def walk(node: yaml.Node) -> None:
        if id(node) in seen_nodes:
            return
        seen_nodes.add(id(node))
        if isinstance(node, yaml.MappingNode):
            keys: set[tuple[str, str]] = set()
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode) and key_node.tag != "tag:yaml.org,2002:merge":
                    identity = (key_node.tag, key_node.value)
                    if identity in keys:
                        found.append(DuplicateKey(key_node.value, key_node.start_mark.line + 1))
                    keys.add(identity)
                walk(key_node)
                walk(value_node)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item)

    if root is not None:
        walk(root)
    return found


def read(path: Path) -> Field:
    """Read and parse `path` once, returning its root as a `Field`.

    Raises `yaml.YAMLError` for a document PyYAML cannot parse, and
    `DuplicateKeysError` for one that declares a key twice; naming those
    conditions is `configure`'s to do, since it owns the schema.
    """

    loader = yaml.SafeLoader(path.read_text(encoding="utf-8"))
    try:
        node = loader.get_single_node()
        duplicates = _duplicate_keys(node)
        if duplicates:
            raise DuplicateKeysError(duplicates)
        value = loader.construct_document(node) if node is not None else None
    finally:
        loader.dispose()
    return Field(value=value, file=str(path), node=node)
