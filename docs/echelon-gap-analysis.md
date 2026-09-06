# Echelon, measured against Datum's semantics

Derived by reading **all four files** of Echelon at
`sailthru/ansible-oss/tools/echelon` — `echelon.py` (188 lines: the action
plugin, the lookup plugin and the resolver), `echelon_yml.py` (35 lines, the
only backend), `echelon.yml` (the sample definition) and `README.md`. Line
references below are to `echelon.py` unless stated otherwise. The comparison is
against [`docs/datum-merge-semantics.md`](datum-merge-semantics.md); section
numbers in the form §5.2 refer to that document.

**Provenance note.** Echelon's last commit touching `tools/echelon` is
2016-05-08; the repository was last pushed 2016-11-17 and is unarchived but
dormant (13 stars, 8 forks). It targets Ansible 2.0/2.1 and **Python 2**:
`merge_dicts` calls `b.iteritems()` (line 113), which does not exist on Python 3,
and `backend_loader` uses `imp` (line 55), removed in Python 3.12. Every Ansible
controller from 2.10 onward is Python 3 only. **Echelon cannot run on a
supported Ansible.** It is a design reference, not a thing to adopt or fork.

---

## 1. What Echelon actually does

The README is misleading in one direction and thin in another. The mechanism,
from the source:

**Configuration** (`run`, lines 143–181). A definition file — `echelon.yml` by
default — declares `hierarchy` (an ordered list of single-key maps: a
*hierarchy name* mapped to an ordered list of *paths*) and `backends` (an
ordered list of single-key maps: a backend plugin name mapped to its config).
Both are mandatory in effect: no `hierarchy` returns an empty result, no
`backends` raises.

**Resolution** is two nested loops:

```
for each hierarchy k:                      # independent, no interaction
    data = {}
    for each path in hierarchy[k]:         # most specific first
        for each backend:                  # first non-empty wins, then break
            data_new = template(backend.main("k/path"))
            if data_new == {}: continue
            data = merge_dicts(data_new, data)
            break
    hierarchies[k] = data
```

Three corrections to the impression the README gives:

1. **It does merge, and it does not short-circuit.** Every path in a hierarchy
   is read and folded in; the walk never stops early. The README's own worked
   example shows this — `prod_ec2` contributes `ami_id`, `defaults` contributes
   `security_group`, the output has both — but never says so. What *is*
   first-match is the **backend** choice per path: the `break` at line 178 exits
   the backend loop, so for a given path only the first backend returning
   non-empty data is consulted.

2. **`merge_dicts(a, b)` is a deep merge where `b` wins**, and it is invoked as
   `merge_dicts(data_new, data)` — the newly-read, *less specific* layer as `a`,
   the accumulated *more specific* result as `b`. So more specific wins, the
   same invariant as Datum's reference/difference (§1, §3.4). Precisely
   (lines 109–125):
   - `b` not a map → `b` wins outright, whatever `a` was. A scalar in a specific
     layer replaces a map in a general one.
   - key in both and `a`'s value is a map → recurse. Deep, at every depth,
     unconditionally.
   - key in both and both values are **lists** → `b + a`: **concatenation**,
     specific items first, then general. No de-duplication, no knockout, no
     identity matching, no way to turn it off.
   - anything else → `b` wins; keys only in `a` survive; keys only in `b` are
     added. Key union at every level.

3. **Each hierarchy is a separate namespace, and they never interact.** `aws`
   and `app` resolve independently and land as two top-level keys. There is no
   single resolution chain and no single resolved document.

**Delivery.** As an action plugin (lines 82–99) the whole result is returned as
`ansible_facts`. As a lookup plugin (lines 62–80) a dotted term is rendered as a
Jinja expression against the result and **appended as a string** —
`result.append(out)` where `out` is `jtemplate.render(...)`, so a map or list
value comes back as its Python `repr`. Undefined is swallowed by
`SilentUndefined` (lines 101–103), which returns `u''`, so a mistyped lookup key
yields an empty string.

**Templating.** Two separate uses, both through Ansible's own `Templar` with
`fail_on_undefined=False` (lines 127–135):

- the **definition file** is templated after load (line 148), so hierarchy path
  templates like `aws/{{ env }}/{{ region }}` expand;
- **every data file's contents** are templated on load (line 173), with
  `convert_data=False`.

---

## 2. Catalogue coverage

Read as: how much of what `docs/datum-merge-semantics.md` describes Echelon can
express.

### 2.1 Per-key merge policy — absent entirely

This is the headline gap, and it is total. Echelon has **no `lookup_options`
analogue, no `default_lookup_options`, no strategy strings, no long form, no
path matching, no patterns, no `merge_options`**. Merge behaviour is hard-coded
in one 17-line function. Everything in §3.1, §3.2, §4.1, §4.2 and §4.3 has no
counterpart: there is no vocabulary in which to say "this key merges deeply,
that one takes the most specific value, this array is `Unique` and that one is
keyed on `GroupName`".

Translated into Datum's terms, Echelon is a single fixed strategy applied to
every path:

| Datum axis | Echelon's fixed value | Configurable? |
| --- | --- | --- |
| `merge_hash` | `deep` (§5.1 rules 3 and 4, map case) | No |
| `merge_baseType_array` | `Sum` (concatenate, no de-dup) | No |
| `merge_hash_array` | `Sum` (concatenate; items are never matched) | No |
| `merge_options.knockout_prefix` | — (no knockout at all) | — |
| `merge_options.tuple_keys` | — (no item identity) | — |
| `sort_merged_arrays` | — | — |
| Early exit / first-wins | — (never short-circuits) | — |

The consequence for the DscPlayground tree is concrete. `LocalGroups` (§5.2)
declares `merge_hash: deep`, then overrides `LocalGroups\Groups` to `DeepTuple`
on `tuple_keys: [GroupName]`, then overrides `Groups\Members` to `Add`. Under
Echelon, `Groups` from three layers concatenates into a list holding three
separate entries for the same group name, and nothing merges their `Members`.
`Configurations` — a `Unique` list in Datum — accumulates duplicates from every
layer that mentions a composite.

### 2.2 Entry by entry

| Catalogue | Echelon | Notes |
| --- | --- | --- |
| §2.1 Tree loading, stores, `ResolutionPrecedence` | **Different shape.** N independent hierarchies, each its own ordered path list, each its own namespace | No single precedence chain, no store concept |
| §2.1 File→key mapping, extension stripping, per-extension parsers | **Narrower.** One backend; tries `<path>.yaml` then `<path>.yml`; a whole file is one layer | No directory-as-map, no lazy tree, no caching |
| §2.2 Four-way type classification | **Absent.** Type is inspected inline (`isinstance` dict/list) | No `hash_array` vs `baseType_array` distinction — this is *why* item identity is impossible |
| §2.3 Case-insensitive key identity | **Absent.** Python dict keys, case-sensitive | Echelon is the sane default here; Datum's collision quirk does not arise |
| §2.4 Source tracking (`__File`) | **Absent.** No annotation, no provenance, no RSOP | Nothing to borrow for the artifact contract |
| §3.1 Option-set assembly, `^.*`, `Default` tag | **Absent** | |
| §3.2 Path→strategy matching, exact then `^` regex | **Absent** | |
| §3.2 Path separator quirk | **Not applicable**, and incidentally correct: paths are joined with `/` (line 172, `echelon_yml.py:24`) | Confirms `/` is portable and workable |
| §3.3 Layer walk, per-segment template expansion | **Different.** The *path* is templated as a whole by Jinja, then used as a file path. There is no walk into a tree and no property path | A layer is a file, not a subtree |
| §3.3 Missing fact = silent skip | **Same failure, worse.** `fail_on_undefined=False` leaves `{{ env }}` literal in the path, the file is missing, the layer is silently skipped | Confirms this is a trap to design out, not a Datum accident |
| §3.4 Accumulation, more-specific-wins | **Same invariant**, achieved by argument order | The one thing that transfers directly |
| §3.4 Null / `[]` / absent conflation | **Same conflation, differently caused.** `echelon_yml.py:32` turns a `None` parse into `{}`; line 174 skips any layer resolving to `{}` | A legitimately empty file is indistinguishable from a missing one |
| §3.4 Early exit / first-wins | **Absent.** Always merges everything | |
| §3.4 `MaxDepth` | **Absent** | |
| §3.5 Null policy, throw on unresolvable | **Absent, and inverted.** Missing data is an empty string (lookup) or an absent key (action plugin) | No `DefaultValue`, no error |
| §4.3 Type-mismatch handling | **Silent.** A mismatch just resolves to the specific side | Datum at least warns |
| §5.1 Knockout | **Absent entirely** | No way to delete a value a lower layer set |
| §6.1–6.3 Tuple keys, `DeepTuple`, `UniqueKeyValTuples` | **Absent** | Arrays of maps concatenate |
| §6.4 `sort_merged_arrays` | **Absent** | |
| §7 Datum handlers | **Absent as a concept**; see §3.2 below for the nearest thing | No predicate/transform contract, no `SkipDuringLoad` |
| §8 RSOP / compiled artifact | **Absent.** Runtime only, by design | |

---

## 3. What Echelon does that Datum does not

Four things worth taking seriously.

**3.1 Hierarchies as named namespaces.** Datum resolves one precedence chain
into one flat, un-namespaced map — which
[Datum RSOP output prototype](https://github.com/camusicjunkie/Reverie/issues/3)
found produces top-level keys as generic as `Name`, `Role` and `Environment`.
Echelon's result is `{hierarchy_name: {...}}`, so its data can never collide
with a role default. The cost is that a hierarchy is also the unit of
resolution: there is no way to say "these two path lists both contribute to the
same key". Reverie is not obliged to take that coupling — namespacing the
*output* and having one resolution chain are independent choices — but the
demonstration that a namespace makes injected data safe is directly relevant to
[Compiled artifact contract](https://github.com/camusicjunkie/Reverie/issues/6).

**3.2 Pluggable backends behind a path.** A path is resolved by asking each
backend in turn for `<hierarchy>/<path>`; the first with data answers (lines
171–178). The backend contract is one method —
`Backend(conf).main(path) -> dict` (`echelon_yml.py`) — configured by a
per-backend map in the definition file. This is a cleaner seam than Datum's
handlers for the "where does data come from" question: a secret store or a CMDB
becomes a backend rather than a value transformer bound by naming convention to
an in-scope `$Node`. Worth weighing for
[Secrets after ProtectedData](https://github.com/camusicjunkie/Reverie/issues/7)
and for the port's plugin contract in the map's **Not yet specified**. The
first-non-empty-wins arbitration *between* backends is too coarse to copy —
whole-file granularity means one backend's file shadows another's entirely.

**3.3 Path templates are Jinja, and they work.** `aws/{{ env }}/{{ region }}`
expands against the play's variable context with Ansible's own templating
engine. Compared with Datum's `$($Node.Environment)` this is language-neutral,
familiar to every Ansible user, and needs no custom expander. It is evidence for
the Jinja option in
[Expressions and resolution purity](https://github.com/camusicjunkie/Reverie/issues/11)
item 3 — at least for the *precedence chain*, where the input is a fixed set of
node facts, as distinct from expressions inside data values.

**3.4 The definition file is small and declarative.** Ordered lists of templated
paths, no strategy language at all. That is the wrong trade-off for Reverie's
requirements, but it is a reminder of what is being paid for: every entry in
`lookup_options` is a thing an operator has to understand.

---

## 4. What Ansible forces, and therefore constrains Reverie too

Separating "chosen" from "forced" was the point of this ticket. Four of
Echelon's shapes are Ansible's doing, not Sailthru's.

**4.1 There is no per-key merge policy anywhere in Ansible, at any layer.**
Echelon had to write `merge_dicts` for the same reason Reverie does. This
independently confirms the reasoning behind the map's compile-to-artifacts
decision: `hash_behaviour = merge` was never a candidate, and two separate
projects reached the same conclusion.

**4.2 Injected data has to land on one of Ansible's precedence rungs, and the
choice has consequences.** Echelon's action plugin returns `ansible_facts`,
which land at the `set_fact`/registered-vars rung — above `host_vars`, above
role `defaults`, above `vars_files`, below only include params and
`--extra-vars`. That is a high rung: an operator cannot override a resolved
value with anything except `-e`. Reverie's artifacts face the same question from
the other end, and it is exactly the second bullet of
[Compiled artifact contract](https://github.com/camusicjunkie/Reverie/issues/6).
Note that Echelon's namespacing (§3.1) is what makes a high rung survivable — it
can outrank role defaults without shadowing them, because the names never meet.

**4.3 Runtime resolution costs a task-ordering problem Echelon does not solve.**
The action plugin is a task: everything before it in the play runs without the
data, and `vars:` blocks, `when:` on earlier tasks and role `defaults` are all
evaluated in a world where the hierarchy has not resolved yet. The lookup plugin
avoids this but returns strings only. The README's bare `- echelon:` task is the
workaround, and it has to be first in every play. Compiling ahead of the run
makes this disappear.

**4.4 Ansible's templating is lenient by default, and the leniency is
contagious.** `fail_on_undefined=False` at line 131, `SilentUndefined` at line
101 — both deliberate, both making missing data indistinguishable from empty
data. This is the same class of failure as Datum's silently-skipped layer (§3.3)
and its null-vs-absent conflation (§3.4), reached by a completely different
route. Two independent implementations landing on silent-empty is a strong
signal that Reverie has to specify strictness explicitly and test for it, rather
than expect it.

**Not forced, and worth naming as such:** Echelon templates *data file contents*
as well as paths (line 173), with `convert_data=False` so any templated value is
a string regardless of what it looks like. Nothing about Ansible requires this,
and it is the same purity hole as Datum's `Datum.InvokeCommand` reaching the
build machine — the variables reachable here are the entire play context,
including gathered facts and registered results. Both projects put an escape
hatch in data values; neither recorded that it fired.

---

## 5. Verdict

**Echelon solves no problem Reverie can inherit a solution to.** The gap is not
"a few missing merge modes" — it is the whole per-key policy layer, which is the
reason Datum was worth reproducing in the first place. Sections 3.1, 3.2, 4.x,
5, 6 and 7 of the semantics catalogue have no Echelon counterpart at all.

What it does provide, at low cost:

- **Three design ideas** worth carrying into open tickets — output namespacing
  (Compiled artifact contract), a backend seam distinct from a value-transformer
  seam (Secrets after ProtectedData, and the port's plugin contract), and Jinja
  as the precedence-chain template language (Expressions and resolution purity).
- **Independent confirmation** of three findings the catalogue reached alone:
  `/` is the right separator, null/empty/absent conflation is a trap that has to
  be designed out rather than avoided by luck, and Ansible has no native per-key
  merge policy to build on.
- **Two Ansible constraints stated in evidence** rather than assumption: the
  precedence-rung question is real and its answer interacts with namespacing,
  and runtime resolution imposes a task-ordering problem that compiling removes.

Nothing here changes the map's destination or its settled decisions.
