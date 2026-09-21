"""Phase 1: configure -- locate and parse reverie.yml, no other file access."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reverie.errors import DiagnosticCollector

PHASE = "configure"


@dataclass(frozen=True)
class ChainEntry:
    address: str
    optional: bool = False


@dataclass(frozen=True)
class SourceConfig:
    root: Path
    layout: str
    chain: list[ChainEntry]
    defaults: str | None


def configure(source_arg: str | None) -> SourceConfig:
    collector = DiagnosticCollector(PHASE)

    if not source_arg:
        collector.add("configure.missing_source_argument")
        collector.raise_if_any()

    root = Path(source_arg)
    reverie_yml = root / "reverie.yml"
    if not reverie_yml.is_file():
        collector.add("configure.reverie_yml_not_found", file=str(reverie_yml))
        collector.raise_if_any()

    try:
        raw = yaml.safe_load(reverie_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        collector.add("configure.malformed_reverie_yml", file=str(reverie_yml), detail=str(exc))
        collector.raise_if_any()

    if not isinstance(raw, dict):
        collector.add("configure.malformed_reverie_yml", file=str(reverie_yml))
        collector.raise_if_any()

    layout = raw.get("layout", "")
    if not isinstance(layout, str) or layout.startswith("/") or layout.endswith("/"):
        collector.add("configure.malformed_layout", file=str(reverie_yml), layout=layout)

    chain_raw = raw.get("chain", []) or []
    chain: list[ChainEntry] = []
    for entry in chain_raw:
        if isinstance(entry, str):
            chain.append(ChainEntry(address=entry))
        elif isinstance(entry, dict) and "address" in entry:
            chain.append(ChainEntry(address=entry["address"], optional=bool(entry.get("optional", False))))
        else:
            collector.add("configure.malformed_chain_entry", file=str(reverie_yml), entry=entry)

    defaults = raw.get("defaults")
    if defaults is not None and not isinstance(defaults, str):
        collector.add("configure.malformed_defaults", file=str(reverie_yml), defaults=defaults)
        defaults = None

    collector.raise_if_any()

    return SourceConfig(root=root, layout=layout, chain=chain, defaults=defaults)
