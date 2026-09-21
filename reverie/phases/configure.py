"""Phase 1: configure -- locate and parse reverie.yml, no other file access."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reverie.errors import DiagnosticCollector

PHASE = "configure"

_TEMPLATE_BLOCK = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _get_child_node(node: yaml.Node, key: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return value_node
    return None


def _validate_template(text: str, line: int | None, file: str, collector: DiagnosticCollector) -> None:
    """Check every `{{ ... }}` block in `text` addresses `host.<identifier>` only.

    Position is the discriminator (CONTEXT.md): a chain/layout template's
    only legal reference is a literal top-level scalar on the host's own
    file, addressed as `host.<name>` -- no nesting, no other namespace.
    """

    stripped = _TEMPLATE_BLOCK.sub("", text)
    if "{{" in stripped or "}}" in stripped:
        collector.add("configure.chain_template_illegal_expression", file=file, line=line)
        return

    for match in _TEMPLATE_BLOCK.finditer(text):
        inner = match.group(1).strip()
        if "." not in inner:
            collector.add("configure.chain_template_illegal_expression", file=file, line=line)
            continue
        namespace, _, rest = inner.partition(".")
        if namespace != "host":
            collector.add("configure.chain_template_unknown_namespace", file=file, line=line)
            continue
        if "." in rest:
            collector.add("configure.chain_template_nested_reference", file=file, line=line)
            continue
        if not _IDENTIFIER.fullmatch(rest):
            collector.add("configure.chain_template_illegal_expression", file=file, line=line)


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
        collector.add(
            "configure.malformed_reverie_yml",
            file=str(reverie_yml),
            detail="expected a mapping at the document root",
        )
        collector.raise_if_any()

    layout = raw.get("layout", "")
    if not isinstance(layout, str) or layout.startswith("/") or layout.endswith("/"):
        collector.add("configure.malformed_layout", file=str(reverie_yml), layout=layout)

    root_node = yaml.compose(reverie_yml.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
    layout_node = _get_child_node(root_node, "layout")
    chain_node = _get_child_node(root_node, "chain")

    if isinstance(layout, str) and layout:
        layout_line = layout_node.start_mark.line + 1 if layout_node is not None else None
        _validate_template(layout, layout_line, str(reverie_yml), collector)

    chain_raw = raw.get("chain", []) or []
    chain_nodes = chain_node.value if isinstance(chain_node, yaml.SequenceNode) else []
    chain: list[ChainEntry] = []
    for index, entry in enumerate(chain_raw):
        entry_node = chain_nodes[index] if index < len(chain_nodes) else None
        if isinstance(entry, str):
            address_node = entry_node
            chain.append(ChainEntry(address=entry))
        elif isinstance(entry, dict) and "address" in entry and isinstance(entry["address"], str):
            address_node = _get_child_node(entry_node, "address") if entry_node is not None else None
            chain.append(ChainEntry(address=entry["address"], optional=bool(entry.get("optional", False))))
        else:
            collector.add("configure.malformed_chain_entry", file=str(reverie_yml), entry=entry)
            continue

        address = chain[-1].address
        if isinstance(address, str):
            line = address_node.start_mark.line + 1 if address_node is not None else None
            _validate_template(address, line, str(reverie_yml), collector)

    defaults = raw.get("defaults")
    if defaults is not None and not isinstance(defaults, str):
        collector.add("configure.malformed_defaults", file=str(reverie_yml), defaults=defaults)
        defaults = None

    collector.raise_if_any()

    return SourceConfig(root=root, layout=layout, chain=chain, defaults=defaults)
