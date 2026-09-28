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

    def shaped(self, shape: type | tuple[type, ...]) -> Any | None:
        """This field's value if it has `shape`, otherwise None.

        The one shape test, so `isinstance` conventions don't multiply one
        per field. A field holding null answers None for every shape, which
        is what `configure` wants of an optional field written empty.
        """

        return self.value if isinstance(self.value, shape) else None

    def report(self, collector: DiagnosticCollector, condition: str, **fields) -> None:
        """Report `condition` against this field.

        The one path a configure-phase diagnostic about a field goes
        through: `file` is the document's, and any `line` the registry
        declares for the condition is passed as `line=self.line` -- never
        recovered by a walk over the node tree at the call site.
        """

        collector.add(condition, file=self.file, **fields)


def read(path: Path) -> Field:
    """Read and parse `path` once, returning its root as a `Field`.

    Raises `yaml.YAMLError` for a document PyYAML cannot parse; naming that
    condition is `configure`'s to do, since it owns the schema.
    """

    loader = yaml.SafeLoader(path.read_text(encoding="utf-8"))
    try:
        node = loader.get_single_node()
        value = loader.construct_document(node) if node is not None else None
    finally:
        loader.dispose()
    return Field(value=value, file=str(path), node=node)
