"""The closed diagnostic shape every phase raises through.

Every error a compile can produce is a ``Diagnostic``: an ``id`` of the
form ``<phase>.<condition>``, the ``phase`` it was raised in, and a set of
declared fields (``file``/``line`` where a position exists). Message prose
is never contract -- only ``id``, ``phase``, and ``fields`` are asserted by
conformance fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Diagnostic:
    id: str
    phase: str
    fields: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "phase": self.phase, **self.fields}


class PhaseFailed(Exception):
    """Raised at a phase boundary once that phase has collected >=1 diagnostic."""

    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        super().__init__(f"{len(diagnostics)} diagnostic(s)")


class DiagnosticCollector:
    """Collects diagnostics within one phase; raises PhaseFailed at the boundary."""

    def __init__(self, phase: str):
        self.phase = phase
        self._diagnostics: list[Diagnostic] = []

    def add(self, id: str, **fields) -> None:
        self._diagnostics.append(Diagnostic(id=id, phase=self.phase, fields=fields))

    def raise_if_any(self) -> None:
        if self._diagnostics:
            raise PhaseFailed(self._diagnostics)
