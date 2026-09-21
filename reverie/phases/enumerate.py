"""Phase 2: enumerate -- resolve hosts and the ordered layer files each walks.

Chain templating and directory-layout validation are logic over data the
`load` phase already read (chain templating only needs a host file's own
top-level scalars, and `reverie.yml` from `configure`) -- enumerate never
opens a layer file itself.

Note: full `layout:` template validation (a host's directory position
checked against the declared template) is out of scope for this ticket
and lands with issue #32; here, `hosts/` is simply scanned recursively and
a host's identity is its filename stem, per CONTEXT.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from reverie.errors import DiagnosticCollector
from reverie.phases.configure import SourceConfig

PHASE = "enumerate"

_TEMPLATE_VAR = re.compile(r"\{\{\s*host\.([A-Za-z0-9_]+)\s*\}\}")


@dataclass(frozen=True)
class LayerRef:
    address: str
    path: Path


@dataclass(frozen=True)
class HostPlan:
    name: str
    file: Path
    # Ordered most-general to most-specific; the host's own file is last.
    layers: list[LayerRef]


class _MissingFact(Exception):
    def __init__(self, fact: str):
        self.fact = fact


def _render_chain_address(address: str, host_facts: dict) -> str:
    """Render a chain address against a host's own facts.

    Raises `_MissingFact` if the address references a fact the host
    doesn't declare -- distinct from the rendered address then pointing
    at a file that doesn't exist ("no such fact" vs "no such file" must
    stay distinguishable, per CONTEXT.md's "Layer" entry).
    """

    def substitute(match: re.Match) -> str:
        fact = match.group(1)
        if fact not in host_facts:
            raise _MissingFact(fact)
        return str(host_facts[fact])

    return _TEMPLATE_VAR.sub(substitute, address)


def _load_host_facts(host_file: Path) -> dict:
    # A permissive parse for chain templating only, deliberately separate
    # from load.load_layers's closed-domain parse of the same file: the
    # two need different rules (this one only reads scalars, and must not
    # itself fail the compile on a value load.py will reject later with a
    # proper diagnostic). The host file is read twice per compile as a
    # result -- an accepted, cheap cost at this estate size.
    try:
        data = yaml.safe_load(host_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def enumerate_hosts(config: SourceConfig) -> list[HostPlan]:
    collector = DiagnosticCollector(PHASE)

    hosts_dir = config.root / "hosts"
    host_files = sorted(hosts_dir.rglob("*.yml")) if hosts_dir.is_dir() else []

    plans: list[HostPlan] = []
    for host_file in host_files:
        name = host_file.stem
        host_facts = _load_host_facts(host_file)

        layers: list[LayerRef] = []

        if config.defaults:
            defaults_path = config.root / config.defaults
            if not defaults_path.is_file():
                collector.add(
                    "enumerate.missing_layer_file",
                    host=name,
                    chain_entry=config.defaults,
                    rendered_address=config.defaults,
                )
            else:
                layers.append(LayerRef(address=config.defaults, path=defaults_path))

        for entry in config.chain:
            try:
                rendered = _render_chain_address(entry.address, host_facts)
            except _MissingFact as exc:
                if not entry.optional:
                    collector.add(
                        "enumerate.missing_chain_fact",
                        host=name,
                        chain_entry=entry.address,
                        fact=exc.fact,
                    )
                continue

            layer_path = config.root / rendered
            if not layer_path.is_file():
                if not entry.optional:
                    collector.add(
                        "enumerate.missing_layer_file",
                        host=name,
                        chain_entry=entry.address,
                        rendered_address=rendered,
                    )
                continue
            layers.append(LayerRef(address=rendered, path=layer_path))

        host_address = str(host_file.relative_to(config.root)).replace("\\", "/")
        layers.append(LayerRef(address=host_address, path=host_file))

        plans.append(HostPlan(name=name, file=host_file, layers=layers))

    collector.raise_if_any()
    return plans
