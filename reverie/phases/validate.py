"""Phase 4: validate -- catch malformed merge/removal data before resolve.

Nothing in this ticket's scope declares a `merge:` policy or uses
`!remove`, so this phase has no checks to run yet; it exists so every
later ticket that adds validate-phase conditions (`validate.*`) has a
phase already wired into the pipeline to add them to. The `resolve` phase
raises no errors at all, by design -- anything that could go wrong with
merge data is caught here first.
"""

from __future__ import annotations

from reverie.errors import DiagnosticCollector
from reverie.phases.load import LoadedHost

PHASE = "validate"


def validate(loaded_hosts: list[LoadedHost]) -> list[LoadedHost]:
    collector = DiagnosticCollector(PHASE)
    collector.raise_if_any()
    return loaded_hosts
