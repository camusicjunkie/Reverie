"""Phase 1: configure -- locate and parse reverie.yml, no other file access."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reverie import keypath, reverie_yml
from reverie.errors import DiagnosticCollector

PHASE = "configure"

_TEMPLATE_BLOCK = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# The closed set of seven merge strategies (CONTEXT.md "Strategy").
_STRATEGIES = {"first", "shallow", "deep", "append", "unique", "unique_tuple", "deep_tuple"}

# The two strategies whose element identity comes from declared tuple_keys
# rather than the whole value -- the only two for which tuple_keys means
# anything at all.
_TUPLE_STRATEGIES = {"unique_tuple", "deep_tuple"}

# A `merge:` entry written in long form is exactly `{strategy, tuple_keys}`
# (CONTEXT.md "Merge policy") -- anything else is a typo, not an extension
# point (ADR 0005).
_MERGE_ENTRY_KEYS = {"strategy", "tuple_keys"}


def _report_if_malformed(
    field: reverie_yml.Field,
    shape: type,
    condition: str,
    collector: DiagnosticCollector,
) -> None:
    """Name `condition` if `field` holds something that is not `shape`.

    A field holding null declares nothing, and every optional block in the
    schema allows that: `secrets:` with nothing after it is a block with no
    secrets in it, the same as no `secrets:` line. That is the rule the
    document root follows too, so the whole file reads one way -- null
    declares nothing, anything else must have the shape the schema says.

    A field holding something of the *wrong* shape is the other case, and it
    used to reach the same empty default in silence. That is
    degrade-and-continue, which ADR 0009 forbids outright, and for `secrets:`
    it disarms the plaintext guardrail (ADR 0006) while the compile passes.

    The position comes off the field, which already carries it.
    """

    if field.value is not None and field.shaped(shape) is None:
        field.report(collector, condition, line=field.line)


def _validate_template(text: str, field: reverie_yml.Field, collector: DiagnosticCollector) -> None:
    """Check every `{{ ... }}` block in `text` addresses `host.<identifier>` only.

    Position is the discriminator (CONTEXT.md): a chain/layout template's
    only legal reference is a literal top-level scalar on the host's own
    file, addressed as `host.<name>` -- no nesting, no other namespace.

    `field` is the field the template was written in, and the three
    conditions below declare a `line`: it comes from the field, which
    already carries it.
    """

    def report(condition: str) -> None:
        field.report(collector, condition, line=field.line)

    stripped = _TEMPLATE_BLOCK.sub("", text)
    if "{{" in stripped or "}}" in stripped:
        report("configure.chain_template_illegal_expression")
        return

    for match in _TEMPLATE_BLOCK.finditer(text):
        inner = match.group(1).strip()
        if "." not in inner:
            report("configure.chain_template_illegal_expression")
            continue
        namespace, _, rest = inner.partition(".")
        if namespace != "host":
            report("configure.chain_template_unknown_namespace")
            continue
        if "." in rest:
            report("configure.chain_template_nested_reference")
            continue
        if not _IDENTIFIER.fullmatch(rest):
            report("configure.chain_template_illegal_expression")


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
class SecretBackend:
    lookup: str
    options: dict


@dataclass(frozen=True)
class GroupFact:
    fact: str
    prefix: str | None = None


@dataclass(frozen=True)
class SourceConfig:
    root: Path
    layout: str
    chain: list[ChainEntry]
    defaults: str | None
    merge_policies: list[MergePolicy]
    secrets: list[str]
    secret_backend: SecretBackend | None
    inventory_groups: list[GroupFact]
    ansible_host_fact: str | None


def check_host_argument(host: str | None, collector: DiagnosticCollector) -> None:
    """`rsop`'s `<host>` is domain-meaningful, so its absence is a named
    condition rather than an argument-parser message (ADR 0009's closed-list
    rule) -- the mirror of `configure.missing_source_argument`."""

    if not host:
        collector.add("configure.missing_host_argument")


def check_no_output_flag(output: str | None, collector: DiagnosticCollector) -> None:
    """`--output` belongs to `rsop` alone; `compile`'s destination is the
    source tree's owned directories, never a caller-chosen path."""

    if output is not None:
        collector.add("configure.unexpected_output_flag")


def configure(source_arg: str | None) -> SourceConfig:
    collector = DiagnosticCollector(PHASE)

    if not source_arg:
        collector.add("configure.missing_source_argument")
        collector.raise_if_any()

    root = Path(source_arg)
    reverie_yml_path = root / "reverie.yml"
    if not reverie_yml_path.is_file():
        collector.add("configure.reverie_yml_not_found", file=str(reverie_yml_path))
        collector.raise_if_any()

    try:
        document = reverie_yml.read(reverie_yml_path)
    except yaml.YAMLError as exc:
        collector.add("configure.malformed_reverie_yml", file=str(reverie_yml_path), detail=str(exc))
        collector.raise_if_any()

    # A root holding nothing -- a blank file or a bare `null` -- is an empty
    # declaration, and every field below then reads as absent. Anything else
    # that is not a mapping is a malformed root, the empty `[]`, `""`, `0`
    # and `false` included: the test is against null, not against falsity,
    # which cannot tell the four apart from a document that declares nothing.
    if document.value is not None and not isinstance(document.value, dict):
        document.report(
            collector,
            "configure.malformed_reverie_yml",
            detail="expected a mapping at the document root",
        )
        collector.raise_if_any()

    layout_field = document.field("layout")
    # An undeclared `layout:` is the empty layout; `layout:` written with no
    # value is a declaration of null, and null is not a layout.
    layout = layout_field.value if layout_field.present else ""
    if not isinstance(layout, str) or layout.startswith("/") or layout.endswith("/"):
        layout_field.report(collector, "configure.malformed_layout", layout=layout)

    if isinstance(layout, str) and layout:
        _validate_template(layout, layout_field, collector)

    chain_field = document.field("chain")
    _report_if_malformed(chain_field, list, "configure.malformed_chain", collector)
    chain: list[ChainEntry] = []
    for entry_field in chain_field.elements():
        # An entry is a bare address, or a mapping declaring one -- and the
        # address is the field a template violation is reported against
        # either way.
        address_field = entry_field if entry_field.shaped(str) is not None else entry_field.field("address")
        address = address_field.shaped(str)
        if address is None:
            entry_field.report(collector, "configure.malformed_chain_entry", entry=entry_field.value)
            continue

        optional = bool(entry_field.field("optional").value)
        chain.append(ChainEntry(address=address, optional=optional))
        _validate_template(address, address_field, collector)

    defaults_field = document.field("defaults")
    defaults = defaults_field.value
    if defaults is not None and not isinstance(defaults, str):
        defaults_field.report(collector, "configure.malformed_defaults", defaults=defaults)
        defaults = None
    elif isinstance(defaults, str) and not (root / defaults).parent.is_dir():
        # The declared floor's *directory* is a configure-phase concern: a
        # `defaults:` address whose directory is absent is a reverie.yml
        # that describes a tree it isn't rooted in. The floor file itself
        # missing from an existing directory stays `enumerate`'s
        # missing_layer_file, same as any other addressed-but-absent layer.
        defaults_field.report(collector, "configure.missing_defaults_directory")
        defaults = None

    merge_field = document.field("merge")
    # A `merge:` of the wrong shape discards every policy in the file, so
    # most-specific-wins quietly becomes ambient `first` everywhere.
    _report_if_malformed(merge_field, dict, "configure.malformed_merge", collector)
    merge_policies: list[MergePolicy] = []
    for pattern, entry_field in merge_field.entries():
        tuple_keys = None
        declares_tuple_keys = False
        bare_strategy = entry_field.shaped(str)
        if bare_strategy is not None:
            strategy = bare_strategy
        elif entry_field.shaped(dict) is not None:
            for key, _value_field in entry_field.entries():
                if key not in _MERGE_ENTRY_KEYS:
                    entry_field.report(collector, "configure.unknown_entry_key", key=key)

            strategy = entry_field.field("strategy").shaped(str)
            if strategy is None:
                entry_field.report(collector, "configure.missing_strategy", key_path=pattern)
                continue

            tuple_keys_field = entry_field.field("tuple_keys")
            declares_tuple_keys = tuple_keys_field.present
            raw_tuple_keys = tuple_keys_field.shaped(list)
            if raw_tuple_keys is not None and all(isinstance(key, str) for key in raw_tuple_keys):
                tuple_keys = tuple(raw_tuple_keys)
        else:
            entry_field.report(collector, "configure.missing_strategy", key_path=pattern)
            continue

        if strategy not in _STRATEGIES:
            entry_field.report(
                collector, "configure.unknown_strategy", key_path=pattern, strategy=strategy
            )
            continue

        if strategy in _TUPLE_STRATEGIES and tuple_keys is None:
            entry_field.report(collector, "configure.missing_tuple_keys", key_path=pattern)
            continue

        if strategy not in _TUPLE_STRATEGIES and declares_tuple_keys:
            entry_field.report(collector, "configure.unexpected_tuple_keys", key_path=pattern)
            continue

        merge_policies.append(MergePolicy(pattern=pattern, strategy=strategy, tuple_keys=tuple_keys))

    for first, _second in keypath.tied_patterns(policy.pattern for policy in merge_policies):
        merge_field.field(first).report(
            collector, "configure.ambiguous_specificity", key_path=first
        )

    secrets_field = document.field("secrets")
    _report_if_malformed(secrets_field, list, "configure.malformed_secrets", collector)
    secrets: list[str] = []
    for element in secrets_field.elements():
        address = element.shaped(str)
        if address is None:
            # No `entry=` echo, unlike `configure.malformed_chain_entry`:
            # `line` already points at it, and ADR 0006 keeps Reverie from
            # holding secret material it could then print (a malformed entry
            # is, by definition, not the key path it was meant to be).
            element.report(collector, "configure.malformed_secret_entry", line=element.line)
            continue
        secrets.append(address)

    backend_field = document.field("secret_backend")
    lookup = backend_field.field("lookup").shaped(str)
    # Not foldable into `_report_if_malformed`: what has to have a shape is
    # the child `lookup`, not `secret_backend:` itself. The presence test is
    # the helper's, though -- a `secret_backend:` holding null declares no
    # backend, which `configure.no_secret_backend` names later if a secret
    # turns out to need one. A backend that *was* declared and has no usable
    # lookup is this condition, and never defers to that one.
    if lookup is None and backend_field.value is not None:
        backend_field.report(
            collector, "configure.malformed_secret_backend", line=backend_field.line
        )
    secret_backend = (
        SecretBackend(lookup=lookup, options=backend_field.field("options").shaped(dict) or {})
        if lookup is not None
        else None
    )

    inventory_field = document.field("inventory")
    _report_if_malformed(inventory_field, dict, "configure.malformed_inventory", collector)
    groups_field = inventory_field.field("groups")
    _report_if_malformed(groups_field, list, "configure.malformed_inventory_groups", collector)
    inventory_groups: list[GroupFact] = []
    for element in groups_field.elements():
        # A group is a bare fact name, or a mapping declaring one with an
        # optional prefix.
        bare_fact = element.shaped(str)
        if bare_fact is not None:
            inventory_groups.append(GroupFact(fact=bare_fact))
            continue
        fact = element.field("fact").shaped(str)
        if fact is not None:
            inventory_groups.append(GroupFact(fact=fact, prefix=element.field("prefix").shaped(str)))

    ansible_host_fact = inventory_field.field("ansible_host").shaped(str)

    collector.raise_if_any()

    return SourceConfig(
        root=root,
        layout=layout,
        chain=chain,
        defaults=defaults,
        merge_policies=merge_policies,
        secrets=secrets,
        secret_backend=secret_backend,
        inventory_groups=inventory_groups,
        ansible_host_fact=ansible_host_fact,
    )
