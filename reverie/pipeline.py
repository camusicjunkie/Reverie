"""Orchestrates the six-phase compile pipeline.

configure -> enumerate -> load -> validate -> resolve -> emit, in strict
order. Each phase collects every diagnostic it can before aborting at its
own boundary (`PhaseFailed`); the pipeline itself never blends phases.
"""

from __future__ import annotations

from dataclasses import dataclass

from reverie.errors import Diagnostic, PhaseFailed
from reverie.phases import configure as configure_phase
from reverie.phases import emit as emit_phase
from reverie.phases import enumerate as enumerate_phase
from reverie.phases import load as load_phase
from reverie.phases import resolve as resolve_phase
from reverie.phases import validate as validate_phase


@dataclass(frozen=True)
class CompileResult:
    diagnostics: list[Diagnostic]
    # Non-fatal (spec/warnings.yml); empty whenever `diagnostics` isn't,
    # since a failed phase never returns far enough to have collected any.
    warnings: list[Diagnostic]


def compile_source(source_arg: str | None) -> CompileResult:
    """Run the full compile pipeline."""

    try:
        config = configure_phase.configure(source_arg)
        enumerated = enumerate_phase.enumerate_hosts(config)
        loaded = load_phase.load_layers(enumerated.hosts, config.secret_backend)
        validated = validate_phase.validate(loaded, config.merge_policies, config.secrets)
        resolved = resolve_phase.resolve(validated, config.merge_policies)
        emit_phase.emit(config, resolved, enumerated.hosts, enumerated.groups)
    except PhaseFailed as exc:
        return CompileResult(diagnostics=exc.diagnostics, warnings=[])

    return CompileResult(diagnostics=[], warnings=enumerated.warnings)
