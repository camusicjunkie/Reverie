"""Orchestrates the six-phase compile pipeline.

configure -> enumerate -> load -> validate -> resolve -> emit, in strict
order. Each phase collects every diagnostic it can before aborting at its
own boundary (`PhaseFailed`); the pipeline itself never blends phases.
"""

from __future__ import annotations

from dataclasses import dataclass

from reverie import prologue
from reverie.errors import Diagnostic, DiagnosticCollector, PhaseFailed
from reverie.phases import configure as configure_phase
from reverie.phases import emit as emit_phase
from reverie.phases import resolve as resolve_phase


@dataclass(frozen=True)
class CompileResult:
    diagnostics: list[Diagnostic]
    # Non-fatal (spec/warnings.yml); empty whenever `diagnostics` isn't,
    # since a failed phase never returns far enough to have collected any.
    warnings: list[Diagnostic]


def compile_source(source_arg: str | None, output: str | None = None) -> CompileResult:
    """Run the full compile pipeline."""

    try:
        flag_collector = DiagnosticCollector("configure")
        configure_phase.check_no_output_flag(output, flag_collector)
        flag_collector.raise_if_any()

        # The phases up to validate are `prologue`'s, shared with `rsop`.
        shared = prologue.run(source_arg)
        enumerated = shared.enumerated
        resolved = resolve_phase.resolve(shared.host_merges)
        emit_phase.emit(shared.config, resolved, enumerated.hosts, enumerated.groups)
    except PhaseFailed as exc:
        return CompileResult(diagnostics=exc.diagnostics, warnings=[])

    return CompileResult(diagnostics=[], warnings=enumerated.warnings)
