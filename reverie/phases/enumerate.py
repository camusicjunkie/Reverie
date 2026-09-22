"""Phase 2: enumerate -- resolve hosts and the ordered layer files each walks.

Chain templating and directory-layout validation are logic over data the
`load` phase already read (chain templating only needs a host file's own
top-level scalars, and `reverie.yml` from `configure`) -- enumerate never
opens a layer file itself.

`hosts/` is scanned recursively; a host's identity is its filename stem,
per CONTEXT.md. A host's directory position (relative to `hosts/`) is
validated against `layout:` rendered from that host's own facts -- never
inferred from the position itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from reverie.errors import Diagnostic, DiagnosticCollector
from reverie.phases.configure import GroupFact, SourceConfig

PHASE = "enumerate"

_TEMPLATE_VAR = re.compile(r"\{\{\s*host\.([A-Za-z0-9_]+)\s*\}\}")

# Ansible's own legal group/host name shape: a bare identifier, never a
# value rewritten to fit it (CONTEXT.md "Group").
_LEGAL_GROUP_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    ansible_host: str | None = None


@dataclass(frozen=True)
class EnumerateResult:
    hosts: list[HostPlan]
    # group name -> member host names, scanned from hosts/ directly rather
    # than resolved artifact data (issue #37) -- targeting-only, per
    # ADR 0007, so this never carries anything beyond membership.
    groups: dict[str, list[str]]
    warnings: list[Diagnostic]


def _group_name(fact: GroupFact, value: str) -> str:
    if fact.prefix is not None:
        return f"{fact.prefix}{value}"
    return f"{fact.fact}_{value}"


def _has_fact(facts: dict, name: str) -> bool:
    # A key present but null carries no value to key an inventory decision
    # on -- treated the same as the key being absent outright, rather than
    # stringified into a literal "None".
    return name in facts and facts[name] is not None


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


def enumerate_hosts(config: SourceConfig) -> EnumerateResult:
    collector = DiagnosticCollector(PHASE)

    hosts_dir = config.root / "hosts"
    host_files = sorted(hosts_dir.rglob("*.yml")) if hosts_dir.is_dir() else []

    plans: list[HostPlan] = []
    host_facts_by_name: dict[str, dict] = {}
    for host_file in host_files:
        name = host_file.stem
        host_facts = _load_host_facts(host_file)
        host_facts_by_name[name] = host_facts

        if config.layout:
            try:
                rendered_layout = _render_chain_address(config.layout, host_facts)
            except _MissingFact as exc:
                collector.add(
                    "enumerate.missing_host_fact",
                    host=name,
                    chain_entry=config.layout,
                    fact=exc.fact,
                )
                rendered_layout = None
        else:
            rendered_layout = ""

        if rendered_layout is not None:
            actual_rel = host_file.parent.relative_to(hosts_dir)
            actual_position = "" if str(actual_rel) == "." else actual_rel.as_posix()
            if actual_position != rendered_layout:
                collector.add("enumerate.host_layout_violation", host=name)

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
                        "enumerate.missing_host_fact",
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

        ansible_host = None
        if config.ansible_host_fact:
            if _has_fact(host_facts, config.ansible_host_fact):
                ansible_host = str(host_facts[config.ansible_host_fact])
            else:
                collector.add("enumerate.missing_ansible_host_fact")

        plans.append(HostPlan(name=name, file=host_file, layers=layers, ansible_host=ansible_host))

    groups = _build_groups(config.inventory_groups, host_facts_by_name, collector)

    host_names = {plan.name for plan in plans}
    for group_name in groups:
        if group_name in host_names:
            collector.add("enumerate.group_host_name_collision")

    warnings = _chain_fact_warnings(config)

    collector.raise_if_any()
    return EnumerateResult(hosts=plans, groups=groups, warnings=warnings)


def _build_groups(
    group_facts: list[GroupFact], host_facts_by_name: dict[str, dict], collector: DiagnosticCollector
) -> dict[str, list[str]]:
    """One group per distinct value each declared fact takes across `hosts/`.

    Scanned from the host files' own facts directly, never resolved
    artifact data (issue #37) -- groups are targeting-only and must stay
    computable before `load`/`resolve` run at all.
    """

    groups: dict[str, list[str]] = {}
    group_sources: dict[str, set[str]] = {}
    grounded_facts: set[str] = set()

    for group_fact in group_facts:
        source_key = f"{group_fact.fact}:{group_fact.prefix or ''}"
        for host_name, facts in host_facts_by_name.items():
            if not _has_fact(facts, group_fact.fact):
                continue

            value = str(facts[group_fact.fact])
            group_name = _group_name(group_fact, value)
            if not _LEGAL_GROUP_NAME.fullmatch(group_name):
                collector.add("enumerate.illegal_group_name", host=host_name, fact=group_fact.fact, value=value)
                continue

            grounded_facts.add(group_fact.fact)
            groups.setdefault(group_name, []).append(host_name)
            group_sources.setdefault(group_name, set()).add(source_key)

    for group_fact in group_facts:
        if group_fact.fact not in grounded_facts:
            collector.add("enumerate.ungrounded_group_fact")

    for sources in group_sources.values():
        if len(sources) > 1:
            collector.add("enumerate.group_name_collision")

    return groups


def _chain_fact_warnings(config: SourceConfig) -> list[Diagnostic]:
    """A fact the chain or layout addresses but `inventory.groups:` never declares.

    Legitimate in isolation (neither needs the fact to be a group), but
    resting on estate-wide knowledge no single layer file's author could
    have -- exactly ADR 0009's bar for a non-fatal warning.
    """

    declared = {group_fact.fact for group_fact in config.inventory_groups}
    referenced: set[str] = set()
    if config.layout:
        referenced.update(_TEMPLATE_VAR.findall(config.layout))
    for entry in config.chain:
        referenced.update(_TEMPLATE_VAR.findall(entry.address))

    return [
        Diagnostic(id="enumerate.undeclared_chain_fact", phase=PHASE)
        for fact in sorted(referenced - declared)
    ]
