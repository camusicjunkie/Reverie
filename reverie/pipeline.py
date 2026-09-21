"""Orchestrates the six-phase compile pipeline.

configure -> enumerate -> load -> validate -> resolve -> emit, in strict
order. Each phase collects every diagnostic it can before aborting at its
own boundary (`PhaseFailed`); the pipeline itself never blends phases.
"""

from __future__ import annotations

from reverie.errors import Diagnostic, PhaseFailed
from reverie.phases import configure as configure_phase
from reverie.phases import emit as emit_phase
from reverie.phases import enumerate as enumerate_phase
from reverie.phases import load as load_phase
from reverie.phases import resolve as resolve_phase
from reverie.phases import validate as validate_phase


def compile_source(source_arg: str | None) -> list[Diagnostic]:
    """Run the full compile pipeline. Returns [] on success, diagnostics on failure."""

    try:
        config = configure_phase.configure(source_arg)
        plans = enumerate_phase.enumerate_hosts(config)
        loaded = load_phase.load_layers(plans)
        validated = validate_phase.validate(loaded, config.merge_policies)
        resolved = resolve_phase.resolve(validated, config.merge_policies)
        emit_phase.emit(config, resolved)
    except PhaseFailed as exc:
        return exc.diagnostics

    return []
