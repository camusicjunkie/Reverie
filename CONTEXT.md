# Reverie

A hierarchical configuration data layer for Ansible: layered data where the specific overrides the general, with declared per-key merge behaviour, compiled to static artifacts rather than resolved at play time.

## Language

**Host**:
The unit of resolution. Identity is the filename stem of its file under `hosts/`; never a synthesized or declared name.
_Avoid_: Node, AllNodes (DSC/Datum vocabulary, dropped).

**Source tree**:
The host layer, the declared chain, and the optional defaults floor together — everything `reverie.yml` and its location define.

**Chain**:
The ordered sequence of layer addresses declared in `reverie.yml` that a host walks during resolution, most general to most specific.
_Avoid_: ResolutionPrecedence (Datum's name).

**Layer**:
One file in the chain, contributing data at one precedence rung. A layer address is a filename with its extension, not a key path into a loaded tree — so "no such file" stays distinguishable from "no such fact".

**Defaults floor**:
The optional, lowest-precedence layer beneath the chain.

**Layout**:
A directory template that a host's position in the source tree is validated against, never inferred from. Host files no longer need expressions to read their own facts back out of their path.

**Merge policy**:
A declaration, addressed by key path, of exactly how values at that path combine across layers: one strategy, written bare or as `{strategy, tuple_keys}`.
_Avoid_: lookup_options (Hiera's name by way of Datum, for an operation Reverie doesn't have).

**Strategy**:
The operation a merge policy performs on the shape it binds to. The closed set is seven: `first`, `shallow`, `deep`, `append`, `unique`, `unique_tuple`, `deep_tuple`. A strategy is total on its own shape and most-specific-wins on every other.

**Key path**:
A single `/`-separated glob (`*` one segment, `**` zero or more, no regex, no list indices) addressing into resolved data. Shared syntax for merge policies and declared secret keys.

**Deferred Jinja**:
A `{{ … }}` template inside a data value, passed through as inert literal text for Ansible to evaluate at play time. Reverie never parses it, only balance-checks the braces.
_Avoid_: expression (Reverie has no expression evaluator — that term belongs only to the chain's own templating, which is a distinct, closed grammar).

**Position is the discriminator**:
The rule that chain templating (in `reverie.yml`) and deferred Jinja (in data values) never share a file, so which one a `{{ … }}` means is always determined by where it appears.

**Artifact**:
The compiled `host_vars/<host>.yml`, one per host, all resolved data under a single top-level `reverie:` key with `reverie_meta:` beside it.

**Owned directory**:
A directory the compiler generates wholesale and may delete files from; anything in it not carrying the compiler's generated header is an error, never a cleanup target.

**RSOP** (Resolved Set of Policy):
The structured, per-host provenance document — a flat map of key path to record, showing every contributor and the losers, not just the winner. Distinct from the artifact: generated on demand, never committed, and the only place per-key attribution lives.
_Avoid_: using "artifact" for this — the artifact carries no attribution.

**Contributor**:
One entry in an RSOP record's contributor list: `{layer, value, outcome}`, ordered most-specific-first, where outcome is one of `won`, `overridden`, `merged`, `removed`.

**`!remove`**:
The tag marking removal of a key, scalar list element, or tuple-matched list-of-maps element during merge. Never emitted in output.

**`!vault`**:
The tag marking an opaque, `ansible-vault`-encrypted scalar. Never inspected, interpolated, or compared — copied into the artifact verbatim.

**`!secret`**:
The tag marking a structured reference to an address in the one external secret-store backend. Translated to the backend's native form at emit, never appears in the artifact as ciphertext, and — unlike `!vault` — can participate in `unique` and tuple matching because it's an address, not material.

**Phase**:
One of the six named stages a compile passes through in order: configure, enumerate, load, validate, resolve, emit. Every error condition is scoped to exactly one phase.

**Error condition**:
A `<phase>.<condition>` slug naming a way a compile can fail, with a declared, fixed set of fields (`file`, `line` where a position exists). Message prose is never contract.

**Conformance fixture**:
A miniature estate — real files, one directory per case — compiled whole and asserted against, either as parsed resolved values or as an exact diagnostic set. The spec's primary correctness deliverable.

**Reference estate**:
The one large, hand-authored conformance fixture (six to ten hosts, invented in Ansible vocabulary) exercising realistic composition rather than a single isolated rule.

**Group** (inventory):
A named set of hosts in the generated `inventory/hosts.yml`, produced one-per-distinct-value for each fact declared in `inventory.groups:`. Targeting-only — Reverie never emits `group_vars`.
