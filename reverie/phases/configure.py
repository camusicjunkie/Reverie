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

# The closed set of seven merge strategies (CONTEXT.md "Strategy").
_STRATEGIES = {"first", "shallow", "deep", "append", "unique", "unique_tuple", "deep_tuple"}


def _tokenize(pattern: str) -> list[str]:
    return pattern.split("/") if pattern else []


def _consume(tokens: list[str], i: int) -> tuple[int, int, int, str | None]:
    """One token's contribution when it accounts for one shared path segment.

    Returns (next_index, literal_delta, star_delta, literal_value_or_None).
    """

    token = tokens[i]
    if token == "**":
        return i, 0, 0, None
    if token == "*":
        return i + 1, 0, 1, None
    return i + 1, 1, 0, token


def _patterns_tie(first: str, second: str) -> bool:
    """Whether two distinct merge-policy patterns could tie in specificity
    on some shared concrete key path.

    Modeled as a joint automaton walking a hypothetical shared path one
    segment at a time: each pattern's `**` may either absorb the segment
    (staying put) or step aside without consuming one (an epsilon move),
    while `*` and literal tokens always consume exactly one segment. This
    searches the resulting state graph for a way to fully parse both
    patterns ending with equal (literal, star) specificity scores -- the
    same score keypath.specificity would compute for each, on the same
    concrete path.
    """

    a = _tokenize(first)
    b = _tokenize(second)
    la, lb = len(a), len(b)

    start = (0, 0, 0, 0, 0, 0)
    seen = {start}
    stack = [start]
    while stack:
        i, j, lit_a, star_a, lit_b, star_b = stack.pop()

        if i == la and j == lb and lit_a == lit_b and star_a == star_b:
            return True

        if i < la and a[i] == "**":
            nxt = (i + 1, j, lit_a, star_a, lit_b, star_b)
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
        if j < lb and b[j] == "**":
            nxt = (i, j + 1, lit_a, star_a, lit_b, star_b)
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)

        if i < la and j < lb:
            ni, dla, dsa, tok_a = _consume(a, i)
            nj, dlb, dsb, tok_b = _consume(b, j)
            if tok_a is None or tok_b is None or tok_a == tok_b:
                nxt = (ni, nj, lit_a + dla, star_a + dsa, lit_b + dlb, star_b + dsb)
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)

    return False


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
class MergePolicy:
    pattern: str
    strategy: str
    tuple_keys: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SourceConfig:
    root: Path
    layout: str
    chain: list[ChainEntry]
    defaults: str | None
    merge_policies: list[MergePolicy]
    secrets: list[str]


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

    merge_raw = raw.get("merge", {}) or {}
    merge_policies: list[MergePolicy] = []
    if isinstance(merge_raw, dict):
        for pattern, entry in merge_raw.items():
            tuple_keys = None
            if isinstance(entry, str):
                strategy = entry
            elif isinstance(entry, dict) and isinstance(entry.get("strategy"), str):
                strategy = entry["strategy"]
                raw_tuple_keys = entry.get("tuple_keys")
                if isinstance(raw_tuple_keys, list) and all(isinstance(k, str) for k in raw_tuple_keys):
                    tuple_keys = tuple(raw_tuple_keys)
            else:
                collector.add("configure.missing_strategy", file=str(reverie_yml), key_path=pattern)
                continue

            if strategy not in _STRATEGIES:
                collector.add(
                    "configure.unknown_strategy", file=str(reverie_yml), key_path=pattern, strategy=strategy
                )
                continue

            merge_policies.append(MergePolicy(pattern=pattern, strategy=strategy, tuple_keys=tuple_keys))

    for index, first in enumerate(merge_policies):
        for second in merge_policies[index + 1 :]:
            if _patterns_tie(first.pattern, second.pattern):
                collector.add("configure.ambiguous_specificity", file=str(reverie_yml), key_path=first.pattern)

    secrets_raw = raw.get("secrets", []) or []
    secrets = [entry for entry in secrets_raw if isinstance(entry, str)] if isinstance(secrets_raw, list) else []

    collector.raise_if_any()

    return SourceConfig(
        root=root, layout=layout, chain=chain, defaults=defaults, merge_policies=merge_policies, secrets=secrets
    )
