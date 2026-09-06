# Datum merge semantics — a language-neutral reference

Derived by reading **Datum 0.40.1** (`datum.psm1`, 2142 lines, plus
`ScriptsToProcess/Resolve-NodeProperty.ps1`). Every claim below is traceable to
that source; PowerShell-specific quirks are called out as such rather than
smuggled into the model. Worked examples use the tree at
`D:\PowerShell\Modules\DscPlayground\source`.

This is the semantics reference Reverie's spec is written against and the future
port is tested against. Where 0.40.1 is ambiguous, accidental, or plainly buggy,
that is flagged as **[QUIRK]** — a decision Reverie has to make rather than
behaviour to copy. The last section collects them.

---

## 1. Vocabulary

| Term | Meaning |
| --- | --- |
| **Store** | A top-level named data source. In practice one directory beside the definition file: `AllNodes`, `Roles`, `Environments`… |
| **Tree** | The union of all stores, plus the definition itself under the reserved key `__Definition`. |
| **Node** | The subject of a lookup. A map of facts (`Name`, `Environment`, `Role`, …) supplied by the caller, bound to the name `Node` while a lookup runs. |
| **Property path** | The key path being looked up, e.g. `WindowsFeatures/Names`. Relative to a layer root. |
| **Layer** | One entry of `ResolutionPrecedence`, after template expansion: a path prefix into the tree. Earlier = more specific. |
| **Reference / difference** | Merge operands. **Reference** is the accumulated, more-specific side; **difference** is the next, less-specific layer. Reference always wins a conflict. |
| **Strategy** | A map of three per-type merge modes plus options, selected by property path. |
| **Knockout** | A key or array element prefixed with the knockout marker (default `--`), meaning "delete what less-specific layers say here". |

---

## 2. The data model

### 2.1 Loading the tree

`New-DatumStructure` reads the definition file (`Datum.yml`), then:

- Every **directory** beside the definition file becomes a store, named by its
  directory name, unless `DatumStructure` is declared explicitly.
- If `ResolutionPrecedence` is absent, it defaults to the list of store names.
  A definition file without `ResolutionPrecedence` is rejected outright.
- The definition map is attached to the tree root as `__Definition`.

The file provider maps the filesystem onto the tree lazily:

- a **directory** becomes a map keyed by the base names of its children;
- a **file** becomes the parsed content of that file, keyed by its base name —
  **the extension is stripped**, so `Roles/Dhcp.yml` is reached as `Roles/Dhcp`;
- parsing is by extension: `.yml`/`.yaml` → YAML (ordered), `.json` → JSON,
  `.psd1` → PowerShell data file, **anything else → the raw file text as a
  string**. There is no error for an unknown extension.
- Results are cached per absolute path, invalidated by last-write time.

A directory and a file with the same base name in the same directory collide;
0.40.1 does not detect this.

### 2.2 Value types

Every value is classified into exactly one of four types (`Get-DatumType`).
This classification drives all merge dispatch.

| Type | Definition |
| --- | --- |
| `hashtable` | A map. |
| `hash_array` | A sequence whose every element is coercible to a map. |
| `baseType_array` | Any other sequence (strings excluded — a string is never a sequence here). |
| `baseType` | Everything else: scalars, and **null**. |

- An **empty sequence** classifies as `baseType_array`, not `hash_array`.
- Null classifies as `baseType`, but in practice never reaches a merge, because
  a null layer value is treated as "not found" (§3.4).

### 2.3 Key identity

After any merge, maps are rebuilt as **case-insensitive, insertion-ordered**
dictionaries. YAML parsing is case-sensitive, so two keys differing only in case
survive loading but collide at merge time. **[QUIRK]** Reverie should fix key
identity once — case-insensitive is the behaviour to keep, but the collision
must be a diagnosed error, not a runtime failure inside the merge.

### 2.4 Source tracking

As data loads, every value gets a hidden `__File` annotation naming the file it
came from. This is what makes `Get-DatumRsop -IncludeSource` able to say which
layer produced each key. Reverie's compiled artifact wants the same property;
note it is an *annotation on the value*, so it survives merges only for values
that pass through unmodified.

---

## 3. Resolution

`Resolve-Datum(propertyPath, node, tree, options?, pathPrefixes?, maxDepth?)`.

### 3.1 Assembling the option set

Three sources of lookup options, in the order they are considered:

1. `default_lookup_options` — the fallback strategy for paths nothing else matches.
2. `lookup_options` — the per-path map in the definition file.
3. `options` — a per-call override argument (unused by the DSC workflow).

The rules, from the source's own decision table:

- If `options` is supplied it **replaces** `lookup_options` wholesale — it is not
  merged with it. Otherwise `lookup_options` is used.
- Any entry written as a bare string is expanded to a full strategy map (§4.1)
  at this point.
- If the resulting map has **no `^.*` key**, one is appended, with
  `default_lookup_options` as its value (itself string-expanded), **tagged
  `Default = true`**. If `default_lookup_options` is absent, the tagged default
  is `MostSpecific`.
- If the user *does* declare `^.*` themselves, nothing is appended and **nothing
  is tagged**. That tag is load-bearing (§5.2), so declaring `^.*` explicitly
  changes deep-merge behaviour throughout the tree. **[QUIRK]**

### 3.2 Matching a path to a strategy

`Get-MergeStrategyFromPath(strategies, propertyPath)`:

1. **Exact key match** on the full property path, case-insensitive. Wins outright.
2. Otherwise, the **first key that begins with `^`**, is a valid regular
   expression, and matches the property path (unanchored at the end,
   case-insensitive).
3. Otherwise **no strategy** (§4.4).

Notes for reimplementation:

- Only keys starting with `^` are treated as patterns. `WindowsFeatures\Names`
  is a literal; `^WindowsFeatures\\.*` is a pattern. There is no glob syntax and
  no wildcard other than regex.
- The match is on the **whole property path from the layer root**, not on the
  leaf key.
- **[QUIRK] "First" is not well-defined.** The strategy set is a hash map, and
  0.40.1 takes the first pattern in *hash enumeration order*. With two competing
  `^` patterns the winner is effectively arbitrary. Reverie must specify an
  order — declaration order in the definition file is the obvious choice — or
  forbid overlapping patterns.
- **[QUIRK] Path separator is the host OS separator.** Child paths are built
  with the platform path-join, so keys read `WindowsFeatures\Names` on Windows
  and `WindowsFeatures/Names` on Linux. The same definition file is not portable.
  Reverie must fix one separator; `/` is the sane choice.

### 3.3 Walking one layer

For each entry of `ResolutionPrecedence`, in order:

1. The entry is first passed through the datum handlers (§7), so a handler may
   compute a prefix.
2. `searchPath = layerPrefix + separator + propertyPath`.
3. **Scriptblock templates** `<%= expr %>` are extracted from the whole search
   path and replaced by positional placeholders, *before* splitting.
4. The path is split on the separator into segments.
5. Segments are walked left to right against the tree:
   - a placeholder segment is **evaluated, and its result becomes the current
     node directly** — it is not used as a key. It is a value injection, not a
     key lookup. If further segments follow, they index into that result.
   - any other segment is **string-expanded** (so `$($Node.Environment)` and
     `$Node.Environment` interpolate from the bound node) and the result is used
     as a **key** on the current node.
6. If any segment yields null, the walk stops and **this layer contributes
   nothing**. This is a normal miss, never an error.
7. A value is emitted only when the last segment is consumed.

**Template evaluation is per-segment and lenient.** If `$Node.Team` is missing,
the segment expands to the empty string, the key lookup yields null, and the
layer is silently skipped. A typo in `ResolutionPrecedence` is therefore
indistinguishable from a legitimately absent layer. **[QUIRK]** — Reverie should
distinguish "fact not defined on this node" (skip, expected) from "template
references a fact no node ever has" (error at compile time).

### 3.4 Accumulating layers

- The first layer that yields a non-null value becomes the **reference**.
- Each later non-null layer is merged in as the **difference**, at the original
  property path, with the full strategy map — the accumulated result is always
  the reference side, so **more specific always wins**.
- **Null is "not found".** A key explicitly set to null in YAML is
  indistinguishable from an absent key: it does not become a null value and does
  not stop the search. **[QUIRK]** — there is no way to say "explicitly empty"
  short of a knockout.
- **An empty sequence is also "not found"**, as a side effect of PowerShell's
  array comparison semantics. `[]` at a layer neither becomes the result nor
  stops the search. **[QUIRK]**, and a surprising one — Reverie should treat
  `[]` as a real value.

**Early exit.** If the strategy selected for the *starting* path carries a key
named `Strategy` whose value begins with `MostSpecific` or `First`, the very
first non-null layer is returned immediately, without merging.

**[QUIRK] the early exit almost never fires.** String-expanded strategies (§4.1)
produce maps with `merge_hash`/`merge_baseType_array`/`merge_hash_array` and *no*
`Strategy` key — so `default_lookup_options: MostSpecific` does **not** take the
early exit. Instead every layer is visited and merged with an all-MostSpecific
strategy, which returns the reference at every type. The final value is the same,
but the walk is not: lower layers are still read, their handlers still run, and
type mismatches between layers still emit warnings. Reverie should specify
first-wins as a genuine short-circuit.

**[QUIRK] `MaxDepth` does not work.** The depth counter is initialised to zero
and never incremented. `MaxDepth` therefore only has an effect when set to `0`
(stop after the first layer); any positive value is equivalent to unlimited.

### 3.5 The caller's null policy

`Resolve-NodeProperty` (aliased `Lookup`) wraps resolution with the policy the
DSC workflow actually sees:

1. Non-null result → return it.
2. Else, if a truthy `DefaultValue` was supplied → return it.
3. Else, if `DefaultValue` was supplied *as null* → return null, legitimately.
4. Else → **throw**. An unresolvable lookup with no declared default is a hard
   error.

Note step 2 tests *truthiness*, not presence: a declared default of `0`, `false`,
or `""` falls through to step 3/4. **[QUIRK]**

---

## 4. Strategies

### 4.1 The string shorthands

A strategy may be written as a string, expanded as follows. Matching is
case-insensitive and anchored.

| String | `merge_hash` | `merge_baseType_array` | `merge_hash_array` | `merge_options` |
| --- | --- | --- | --- | --- |
| `First`, `MostSpecific` | `MostSpecific` | `MostSpecific` | `MostSpecific` | — |
| `hash`, `MergeTopKeys` | `hash` | `MostSpecific` | `MostSpecific` | `knockout_prefix: --` |
| `deep`, `MergeRecursively` | `deep` | `Unique` | `DeepTuple` | `knockout_prefix: --`, `tuple_keys: [Name, Version]` |
| *anything else* | `MostSpecific` | `MostSpecific` | `MostSpecific` | — |

**[QUIRK]** An unrecognised string — a typo like `Deeep` — silently degrades to
`MostSpecific`. Reverie must reject unknown strategy names.

**[QUIRK]** `deep` carries an implicit `tuple_keys: [Name, Version]`. Any deep
merge of an array of maps that does not declare its own `tuple_keys` is
silently keyed on `Name` and `Version`.

### 4.2 The long form

Written as a map, the recognised keys are:

- `merge_hash` — `MostSpecific` | `First` | `hash` | `deep`
- `merge_baseType_array` — `MostSpecific` | `First` | `Unique` | `Sum` | `Add`
- `merge_hash_array` — `MostSpecific` | `First` | `UniqueKeyValTuples` |
  `DeepTuple` | `DeepItemMergeByTuples` | `Sum`
- `merge_options`
  - `knockout_prefix` — string, default `--`
  - `tuple_keys` — list of key names identifying "the same item" in an array of maps
- `sort_merged_arrays` — boolean; see §6.4
- `Strategy` — only consulted for the early exit in §3.4

Key names are matched case-insensitively (`merge_basetype_array` and
`merge_baseType_array` both work — the DscPlayground definition uses both
spellings). Mode *values* are matched by prefix, case-insensitively:
`merge_baseType_array: Summation` is accepted as `Sum`. **[QUIRK]** — prefix
matching should be replaced by exact matching.

### 4.3 Merge dispatch

`Merge-Datum(path, reference, difference, strategies)`:

1. Both operands are passed through the datum handlers (element-wise for
   sequences).
2. Both are classified (§2.2).
3. **Type mismatch → warn, return the reference.** More specific wins; no
   attempt at coercion.
4. Otherwise dispatch on the shared type:

| Type | Mode | Result |
| --- | --- | --- |
| `baseType` | *(any)* | reference |
| `hashtable` | `MostSpecific`/`First` | reference |
| `hashtable` | `hash`, `deep` | map merge (§5) |
| `baseType_array` | `MostSpecific`/`First` | reference |
| `baseType_array` | `Unique` | `reference ++ difference`, knockouts dropped, then de-duplicated keeping first occurrence — so reference order is preserved and reference wins ties |
| `baseType_array` | `Sum`/`Add` | `reference ++ difference`, knockouts dropped, **no** de-duplication |
| `baseType_array` | anything else | reference |
| `hash_array` | `MostSpecific`/`First` | reference |
| `hash_array` | `UniqueKeyValTuples` | tuple de-duplication (§6.3) |
| `hash_array` | `DeepTuple`/`DeepItemMergeByTuples` | tuple-wise deep merge (§6.2) |
| `hash_array` | `Sum` | **broken — do not use** (§6.5) |
| `hash_array` | anything else | reference |

**Knockouts in base-type arrays** are dropped from the *result*, not matched
against specific elements: any element whose text begins with the knockout
prefix is removed from the concatenation, along with nothing else. It removes
the marker, **not the element it names**. **[QUIRK]** — knockout for base-type
arrays is effectively non-functional in 0.40.1; Reverie must decide whether
`--foo` should remove `foo`.

### 4.4 No strategy at all

If no strategy matches (only reachable when `^.*` is absent, i.e. never via
`Resolve-Datum`, but reachable when `Merge-Datum` is called directly), the
strategy is null and the effective behaviour is: maps get a **shallow key union**
(§5), base types keep the reference, arrays keep the reference. Note this is
*not* the same as `MostSpecific`.

---

## 5. Map merge

`Merge-Hashtable(reference, difference, strategy, childStrategies, parentPath)`.
Reached for `merge_hash` of `hash` **or** `deep`.

### 5.1 Algorithm

Start from an ordered copy of the reference. Compute the **knocked-out set**:
every reference key beginning with the knockout prefix, with the prefix stripped.
Then, for each key of the difference, in difference order:

1. **Key is in the knocked-out set** → drop it. The less-specific value is deleted.
2. **Key itself carries the knockout prefix, and the reference has no
   corresponding un-prefixed key** → copy the marker into the result with a null
   value, so it continues to knock the key out against still-lower layers.
3. **Key absent from the reference** → add it with the difference's value. *This
   is the key union, and it happens under `hash` as well as `deep`.*
4. **Key present in both** → dispatch on the **reference** value's type:
   - **map** — merged recursively **only if `merge_hash` is exactly `deep`**;
     under `hash` the reference value is kept whole. See §5.2.
   - **base type** — reference kept.
   - **either array kind** — always re-enters `Merge-Datum` at the child path
     `parentPath + separator + key`, with the full strategy set. **This happens
     under `hash` too**, so `hash` is "union top-level keys, keep scalars and
     maps, but merge arrays per their own declared strategy".

New keys are appended in difference order after the reference's own keys.

**[QUIRK] Knockout markers are never stripped from the output.** A `--Foo` key
survives into the final document (with a null value if it came from rule 2).
Anything consuming the resolved document has to strip them. Reverie's compiler
should strip them at the end of resolution.

**[QUIRK]** Rule 4 tests the **reference** value's type only; if reference and
difference disagree, the mismatch is caught one level down in `Merge-Datum`
(warn, keep reference) — but for the map case it is not caught at all: a map on
the reference side and a scalar on the difference side under `deep` recurses and
fails messily.

### 5.2 How `deep` propagates — the `Default` tag

This is the single most important rule in Datum, and the least obvious.

When a deep merge recurses into a nested map at child path `P`, it looks up the
strategy for `P`:

- **If that strategy is the tagged default** (i.e. `P` matched only the
  synthesised `^.*` entry from §3.1), the *current* strategy is carried down
  unchanged and the recursion continues as a map merge. **Deep merging
  propagates downward through paths that say nothing.**
- **If `P` matched a real, declared entry**, that entry takes over: the recursion
  goes through full merge dispatch with the child's own strategy.

So in the DscPlayground definition:

```yaml
LocalGroups:
  merge_hash: deep
LocalGroups\Groups:
  merge_baseType_array: Unique
  merge_hash_array: DeepTuple
  merge_options:
    tuple_keys: [GroupName]
LocalGroups\Groups\Members:
  merge_baseType_array: Add
```

`LocalGroups` deep-merges; `Groups` (an array of maps) is overridden to merge by
`GroupName`; and within each merged group, `Members` accumulates additively
rather than uniquely. Every intermediate path that is *not* named simply
inherits `deep`.

**[QUIRK]** The corollary from §3.1: declare `^.*` yourself and nothing is
tagged, so every nested key re-enters dispatch with `^.*`'s strategy instead of
inheriting the parent's. Reverie should make inheritance explicit rather than a
side effect of a tag.

---

## 6. Array-of-maps merge

`Merge-DatumArray(referenceArray, differenceArray, strategy, childStrategies, startingPath)`.

### 6.1 Tuple keys

`merge_options.tuple_keys` names the keys that identify "the same item" across
layers. Two items are the same when **all** tuple keys compare equal.

Comparison (`Compare-Hashtable`) is per key:

- both sides have the key, and either value is an array of maps → compare
  recursively, over the union of *their* keys;
- both sides have the key otherwise → loose scalar inequality (case-insensitive
  for strings);
- key present on one side only → different.

Items are "the same" when the comparison produces no differences.

### 6.2 `DeepTuple` / `DeepItemMergeByTuples`

For each **reference** item, in order:

1. Find every difference item that matches it on the tuple keys.
2. Fold each match into the reference item with a **map merge** (§5), using the
   same strategy and the same child strategy set, at the **array's** path.
3. Emit the merged item.

Then append every difference item that matched nothing, in difference order.

Result ordering: merged reference items first (reference order preserved), then
new items contributed by less-specific layers.

**[QUIRK]** The nested merge is performed at the *array's* path, not at
`array[i]`, so child strategies below an array element are addressed as
`Path\To\Array\Key` — array indices never appear in a lookup-options key. That
is arguably the right design; it just needs stating.

**[QUIRK]** If `tuple_keys` is absent, the key set is taken from the **first**
reference item and then reused for all subsequent items, because the variable
persists across the loop. Heterogeneous arrays merge incoherently.

**[QUIRK]** "Which difference items were used" is tracked by object identity, not
value. Works in practice only because the same instances are threaded through.

### 6.3 `UniqueKeyValTuples`

De-duplication, never merging. Walk the reference array then the difference
array, appending an item only if no already-emitted item matches it on the tuple
keys. Reference items win; the first occurrence survives.

> **[QUIRK] — the serious one.** If `tuple_keys` is absent, this branch tries to
> fall back to "all keys of the reference item" but reads an unset variable, so
> the key set is empty. An empty key set makes the comparison find **no
> differences**, so **every item matches every other item, and the merged array
> collapses to a single element.** `UniqueKeyValTuples` without `tuple_keys` is
> silent data loss. Reverie must make `tuple_keys` mandatory for this mode.

### 6.4 `sort_merged_arrays`

Sorts the array by `tuple_keys` — but **only in the branch where the array
strategy is `MostSpecific` or unset**, i.e. only when merging is *disabled*.
It has no effect on an actually-merged array. **[QUIRK]**

### 6.5 `Sum` on arrays of maps

**Broken in 0.40.1.** The `Sum` branch of `Merge-Datum` for `hash_array`
references two variables that do not exist in its scope, and never reaches the
working implementation in `Merge-DatumArray`. It produces nothing usable. Treat
`merge_hash_array: Sum` as unimplemented. (The `Sum`/`Add` branch inside
`Merge-DatumArray` — concatenate difference then reference — is the intended
behaviour and is what Reverie should specify, though note the *reversed* order
there: difference items come first.)

---

## 7. Datum handlers

Handlers are pluggable value transformers, invoked wherever a value is touched:
on file load, on both operands of every merge, and again when the RSOP result is
cloned.

Declaration:

```yaml
DatumHandlers:
  Datum.ProtectedData::ProtectedDatum:
    CommandOptions:
      Certificate: A428BD0CDE918995D330D15FA0656E9CBB58236F
  Datum.InvokeCommand::InvokeCommand:
    SkipDuringLoad: true
```

- The key is `Module::Name`. The predicate is `Module\Test-<Name>Filter`, the
  transform is `Module\Invoke-<Name>Action`. Convention over configuration.
- The predicate is normally a prefix/suffix test on a string, e.g.
  `[ENC=...]` for ProtectedData, `[x= ... =]` for InvokeCommand.
- `CommandOptions` are bound to the transform's parameters by name.
  **[QUIRK]** Any transform parameter *not* in `CommandOptions` is auto-bound
  from any in-scope variable of the same name. That is how a handler gets hold
  of `$Node` — and it is an unbounded coupling to the caller's variable scope.
  Reverie's handler contract must pass an explicit context object.
- `SkipDuringLoad: true` defers the handler past file loading, so it runs at
  merge/resolve time instead. This is what makes `Datum.InvokeCommand` see the
  resolved node rather than the raw file.
- `DatumHandlersThrowOnError: true` (recommended, and set in DscPlayground) makes
  a failing handler abort compilation. Default is to warn and pass the input
  through unchanged — which silently ships an unresolved `[ENC=...]` string into
  the output.
- **Handlers must be idempotent and total on already-transformed values**, since
  values pass through them several times per lookup.

---

## 8. What `Get-DatumRsop` actually produces

Relevant because Reverie's v1 compiler is built on it.

For each node:

1. The node's own facts are copied verbatim into the result.
2. The **composition key** (default `Configurations`) is resolved, defaulting to
   an empty list, and stored on the result.
3. **Each name in that list is itself resolved as a property path**, defaulting
   to an empty map, and stored under that name.
4. If `DscLocalConfigurationManagerKeyName` is declared, that path is resolved
   and stored under `LcmConfig`.
5. The result is deep-copied, re-run through the handlers, and cached by node name.

So the RSOP document is **not** "the whole tree resolved for this node" — it is
node facts plus the composition list plus exactly the keys the composition list
names. Anything in the source tree that no configuration references is absent
from the RSOP. Reverie's artifact contract has to decide whether that is the
right shape, or whether the compiler emits every resolvable key.

`-IncludeSource` / `-RemoveSource` control whether the `__File` annotations are
expanded into the output.

The cache is keyed on node name only and is not invalidated by source changes —
`-IgnoreCache` or `Clear-DatumRsopCache` is required between runs in a
long-lived session.

---

## 9. Worked example

Given the DscPlayground precedence chain:

```yaml
ResolutionPrecedence:
  - AllNodes\$($Node.Environment)\$($Node.Team)\$($Node.NodeName)
  - Teams\$($Node.Team)
  - Environments\$($Node.Environment)
  - Locations\$($Node.Location)
  - Roles\$($Node.Role)
  - Stigs\$($Node.OsStig)
  - Baselines\$($Node.Baseline)
  - Baselines\DscLcm
```

and a lookup of `WindowsFeatures/Names` for a node with
`Environment: Production, Team: Platforms, NodeName: DSCFile01, Role: Dfs`:

1. `WindowsFeatures` matches the declared entry `WindowsFeatures` → `merge_hash: deep`;
   `WindowsFeatures\Names` matches its own entry → `merge_baseType_array: Unique`.
2. Layers are visited in order. `AllNodes\Production\Platforms\DSCFile01` yields
   the node file's list; `Roles\Dfs` yields the role's list; `Baselines\Server`
   yields the baseline's list. Layers whose template resolves to a missing key
   (`Locations\` when the node has no `Location`) are skipped silently.
3. Each non-null layer is folded in as the difference against the accumulated
   reference, at path `WindowsFeatures\Names`, with `Unique`: concatenate,
   drop knockout-prefixed entries, de-duplicate keeping first occurrence.
4. The result preserves node-file order first, then role, then baseline.

Had `WindowsFeatures\Names` not been declared, the path would have matched the
synthesised `^.*` default (`MostSpecific`), and the node file's list would have
won outright with nothing from the role or baseline.

---

## 10. Decisions this hands to Reverie

Ordered roughly by how much of the spec they touch.

1. **Path separator.** Fix `/`. 0.40.1's OS-dependent separator makes definition
   files non-portable. (§3.2)
2. **Strategy inheritance.** Specify explicitly that a merge mode propagates to
   nested paths that declare nothing, instead of deriving it from a `Default`
   tag that disappears when the user declares `^.*`. (§5.2, §3.1)
3. **First-wins must short-circuit.** Make `MostSpecific` a real early exit, so
   lower layers are neither read nor handler-evaluated. (§3.4)
4. **`tuple_keys` mandatory** for both tuple modes. The absent-tuple-keys
   fallbacks are a silent-data-loss bug and a heterogeneity bug. (§6.2, §6.3)
5. **Null and empty are values.** Decide how "explicitly empty" is expressed and
   stop conflating null, `[]`, and absent. (§3.4)
6. **Knockout semantics.** Define what `--x` means in a base-type array (0.40.1
   removes only the marker), and strip all knockout markers from the compiled
   output. (§4.3, §5.1)
7. **Unknown names are errors.** Unrecognised strategy strings, unrecognised
   mode values, and prefix-matched mode names should all be rejected at load.
   (§4.1, §4.2)
8. **Pattern precedence.** Define the order in which `^` patterns are tried
   (declaration order), or forbid overlaps. (§3.2)
9. **Template strictness.** Separate "node lacks this fact, skip the layer" from
   "template names a fact that does not exist", and make the second a compile
   error. (§3.3)
10. **Handler contract.** Replace implicit variable-scope binding with an
    explicit context, and require idempotence. (§7)
11. **Drop or re-specify:** `MaxDepth` (non-functional), `sort_merged_arrays`
    (applies only where it cannot matter), `merge_hash_array: Sum` (broken).
12. **Artifact scope.** Decide whether the compiled document is composition-driven
    like the RSOP, or the full resolved key set. (§8)

Items 1–8 are behavioural and belong in the semantics section of the spec.
Items 9–12 are scope questions for other tickets on the map.
