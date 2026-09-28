# Reverie

A hierarchical configuration data layer for Ansible: layered data where the specific overrides the general, with declared per-key merge behaviour, compiled to static artifacts rather than resolved at play time.

## Language

**Host**:
The unit of resolution. Identity is the filename stem of its file under `hosts/`; never a synthesized or declared name.
_Avoid_: Node, AllNodes (DSC/Datum vocabulary, dropped).

**Fact**:
One top-level key of a host's own file, read before any layer is loaded and used to route the host: to render a chain address or the layout, to key an inventory group, and to supply `ansible_host`. All three read a fact as a scalar, so a fact whose value is a map, a list, or one of Reverie's three tags has nothing to stand as a path segment or a group name — tagged or not, it simply isn't usable there. It remains ordinary data on the host layer, merged and emitted like any other.

**Source tree**:
The host layer, the declared chain, and the optional defaults floor together — everything `reverie.yml` and its location define.

**Field** (of `reverie.yml`):
One field of the `reverie.yml` document, read as its value and its position together — the unit `configure` checks against the file's schema, and the unit a configure-phase diagnostic is reported against. The document is read once, so a field's line is something it carries rather than something a caller recovers by walking the parse tree, and what fields exist, what shapes they take and what each violation is called stay with `configure`.
_Avoid_: using it for an **error condition**'s declared fields (the keys a diagnostic carries), and node (PyYAML's parse tree, which nothing outside the read walks).

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

**Element group**:
The elements of a merged list that a strategy counts as the same element, gathered across every contributing layer — the unit a list merge emits one element for. A group of one is never merged: its lone element is already the answer. Under `deep_tuple` a group of two or more is *folded*: merged as a map at the list's own key path, so a policy addressed there governs it. The fold is one merge over the whole group, never a chain of pairwise ones, so a `!remove` inside a folded element reaches every more general contributor to it, exactly as it would anywhere else. Also the unit RSOP attributes a fold's interior merges to — one element selector per group.

**Merge walk**:
Every merge one host performs, in the order it performs them: one traversal of its layer stack, yielding each merge's key path, RSOP address, binding decision, and per-layer contributions. The traversal rules — gather a key's contributions, extend the key path, bind, recurse into a map the strategy applied to, fold each element group of two or more — belong to the walk, and every consumer of a host's merges is meant to read them from it rather than re-derive them: resolve to compute values, validate to judge decisions, RSOP to attribute contributors. All three do, and none keeps a traversal of its own.
_Avoid_: resolution (the whole compile is that), and calling one step of the walk a *merge policy* — a policy is the declaration, a merge is the act.

**Policy observation**:
What one declared **merge policy** was seen to do across every host compiled in one run — whether any layer touched a key path it matches, whether its **strategy** ever won against the shape it is for, and the specific faults it met on the way. The unit `validate` judges a policy by, and the place the precedence between a policy's **error condition**s is stated: a pattern that matched nothing reports only that, and a tuple strategy that only ever met a plain list reports the specific finding in place of the general one. Built by folding the **merge walk**'s decisions in as they stream past, so the verdict rests on the merges the host actually performed.
_Avoid_: spreading one policy's verdict across per-condition sets keyed by pattern, which makes "what is wrong with this policy" a set intersection rather than a lookup.

**Key path**:
A single `/`-separated glob (`*` one segment, `**` zero or more, no regex, no list indices) addressing into resolved data. Shared syntax for merge policies and declared secret keys. Having no list indices, a list's own path is also the path its elements' keys hang from — real only under `deep_tuple`, the one strategy that merges its elements as maps. Beneath any other list strategy nothing is merged there, so a policy addressed inside one binds to nothing and is reported. One key path there stands for one merge per element group, which only RSOP needs to tell apart — see **RSOP address**.

**RSOP address**:
The key one RSOP record sits under: a key path, with an *element selector* — `[name=Administrators]`, the fold's declared `tuple_keys` in declaration order — appended to any segment naming a list whose elements a `deep_tuple` fold merged. Element identity as the merge itself computed it, so an address is stable across layer order and across a layer being added, and two element groups contributing the same key address distinctly instead of colliding. Each value inside a selector is written as YAML writes a scalar in a flow collection — which is what a selector is — so YAML's own quoting settles every ambiguity against the delimiters without an escape scheme of Reverie's own; a `/` is quoted too, being the segment separator YAML knows nothing about. A superset of key-path syntax and RSOP's alone: a merge policy or declared secret key is a plain key path and never carries a selector.
_Avoid_: list index (an artifact of merge order, not an identity), and nesting a fold's records inside the list's own record (the map stays flat).

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
The structured, per-host provenance document — a flat map of **RSOP address** to record, showing every contributor and the losers, not just the winner. One record per merge the host performs, the interior of a `deep_tuple` fold included. Distinct from the artifact: generated on demand, never committed, and the only place per-key attribution lives.
_Avoid_: using "artifact" for this — the artifact carries no attribution.

**Contributor**:
One entry in an RSOP record's contributor list: `{layer, value, outcome}`, ordered most-specific-first, where outcome is one of `won`, `overridden`, `merged`, `removed`. Inside a `deep_tuple` fold, contributors are those of one element group — the layers that contributed *that* element — never pooled across the list.

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
