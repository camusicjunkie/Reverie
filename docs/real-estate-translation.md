# Expressing the real estate in Reverie

A translation of the DscPlayground source tree (`D:\PowerShell\Modules\DscPlayground\source`,
22 files, three hosts, an eight-rung `ResolutionPrecedence`) into Reverie as the spec
currently stands. The translated tree is in [`real-estate-translation/`](real-estate-translation/).

**This is a spec-completeness check, not a fixture.** The tree is throwaway and is not
maintained; the output that matters is the list below. Its job is to find requirements the
invented reference estate cannot, because an invented estate only exercises what its author
thought of.

Translated against: [Reverie source tree layout](https://github.com/camusicjunkie/Reverie/issues/5),
[Compiled artifact contract](https://github.com/camusicjunkie/Reverie/issues/6),
[Secrets after ProtectedData](https://github.com/camusicjunkie/Reverie/issues/7),
[Resolution semantics decisions](https://github.com/camusicjunkie/Reverie/issues/8),
[The composition model](https://github.com/camusicjunkie/Reverie/issues/9),
[Artifact serialisation rules](https://github.com/camusicjunkie/Reverie/issues/10),
[Expressions and resolution purity](https://github.com/camusicjunkie/Reverie/issues/11),
[Reverie's extension contract](https://github.com/camusicjunkie/Reverie/issues/14),
[Failure semantics](https://github.com/camusicjunkie/Reverie/issues/15),
[Inventory generation contract](https://github.com/camusicjunkie/Reverie/issues/16).

The friction the ticket predicted — no expression evaluator, `LcmConfig` out of scope, no
seam for the two DatumHandlers, `Configurations` deleted, `Global\Domain.yml` demoted to the
floor — all landed as expected and is not repeated here except where it behaved differently
than predicted.

---

## A. The spec had no answer

### 1. The merge declaration language is not fixed anywhere

The translation stalled on its first line of `reverie.yml`. Nothing in the map fixes:

- **The block's name.** [Reverie source tree layout](https://github.com/camusicjunkie/Reverie/issues/5)
  calls it `merge:`; [Secrets after ProtectedData](https://github.com/camusicjunkie/Reverie/issues/7)
  and [Resolution semantics decisions](https://github.com/camusicjunkie/Reverie/issues/8) call it
  `lookup_options:`.
- **The declaration's shape.** #8 writes `local_groups/groups: { merge_hash_array: deep_tuple, tuple_keys: [group_name] }`
  — Datum's tri-key vocabulary, with `tuple_keys` hoisted out of Datum's `merge_options` wrapper.
  #7 writes `api_keys: {merge: unique}` — a single `merge:` key. These are not two spellings of
  one design; they disagree about whether a declaration carries one strategy or several.
- **The strategy and mode names themselves.** [Conformance fixture shape](https://github.com/camusicjunkie/Reverie/issues/13)
  ships "the closed sets of strategy names, mode values and the three tags" as `spec/` data, and
  [Failure semantics](https://github.com/camusicjunkie/Reverie/issues/15) raises
  `configure.unknown_strategy` and `configure.unknown_mode` against "the closed set". The closed
  set is referenced by two tickets and enumerated by none.
- **The default policy.** Datum has `default_lookup_options: MostSpecific`.
  [The composition model](https://github.com/camusicjunkie/Reverie/issues/9) argues a default
  "has to exist regardless" and hands the question to #8, which does not answer it — the word
  "default" appears in #8 only in connection with the defaults *floor*.

Every merge declaration in the translated `reverie.yml` is therefore invented, written in #8's
shape because it is the more detailed of the two. This is the largest hole the check found: it
is not a corner case, it is the spec's central data structure.

### 2. Specificity selection is not shape-aware, and this estate needs it to be

`LocalGroups` is the shape the ticket flagged, and it does not survive contact.

```yaml
local_groups:                 { merge_hash: deep }
local_groups/groups:          { merge_hash_array: deep_tuple, tuple_keys: [group_name] }
local_groups/groups/members:  { merge_baseType_array: append }
```

`baselines/server.yml` contributes an `Administrators` element carrying `members` **and**
`credential`. The key path `local_groups/groups/credential` is a scalar. Its best match under
#8's rule — a declaration governs its subtree, most specific wins — is `local_groups/groups`,
whose strategy is a **list** strategy. #8 fixes which *entry* wins and never says:

- what happens when the winning entry's strategy does not fit the value's shape;
- whether selection falls through to the next-less-specific entry when it does not;
- or whether one path may carry several shape-keyed strategies at once.

That last one is not hypothetical. Datum declares **two** strategies on `LocalGroups\Groups`
— `merge_baseType_array: Unique` *and* `merge_hash_array: DeepTuple` — dispatching on whether
the list holds scalars or maps. #8's worked example silently drops the first half. Datum
encoded shape in the key name; #8 inherits the three key names without ever saying they are
shape selectors, which is the one reading that makes this estate translatable.

### 3. List merge ordering is unspecified, and it is directly observable

`local_groups/groups/members` is the estate's one accumulating list.
`baselines/server.yml` offers `[SG-SA-ServerAdmins, SG-SA-ServerAdminServiceAccounts]`;
`roles/dfs.yml`, more specific, offers `[SG-AA-DFSAdmins]`. The merged value appears verbatim
in `host_vars/nipat-pl-dfs01.yml` — and the spec does not say whether it is most-specific-first
or least-specific-first.

[Artifact serialisation rules](https://github.com/camusicjunkie/Reverie/issues/10) rules that
"list order is data and is never sorted", and notes that "precedence-ordered results — the layer
list in `reverie_meta`, `unique`-merged arrays — survive by this rule". That *presumes* a
precedence order exists without ever fixing its direction. The same question is open for which
duplicate survives under `unique`, and for where a deep-tuple-merged element sits when several
layers offer it.

This blocks fixtures, not just prose: every list-merge case asserts an order, and none can be
written today.

### 4. `host.name` is an implicit binding that exists only in an example

`hosts.layout` in #5 reads `"{{ host.environment }}/{{ host.team }}/{{ host.name }}.yml"`.
But #5 also rules that a placeholder reads "only the host file's own literal top-level scalars",
and that **declaring `name` inside the file is an error**. So `name` is bound from the filename
stem by a rule that appears nowhere except that example.

It has a knock-on. [Inventory generation contract](https://github.com/camusicjunkie/Reverie/issues/16)
makes `enumerate.undeclared_chain_fact` warn for a chain-referenced fact absent from
`inventory.groups:`. `name` is referenced by `layout` and can never be a group fact, so either
`layout` is not part of "the chain" for that check, or every estate warns forever. Neither is
stated.

### 5. A layer file whose document is `null` has no defined meaning

Four of the estate's five location files are **zero bytes** — `DelDin`, `Molesworth`,
`Pentagon`, `Shape`. An empty file is valid YAML and `null` is inside the closed value domain,
but that domain governs *values*, and a layer is defined by the top-level keys it contributes.
`load.invalid_yaml` does not fire. Whether such a file contributes nothing, or is an error,
or must be written `{}`, is unspecified. The translation wrote `{}`, which the source did not
ask for.

---

## B. Decisions already made, biting harder than expected

### 6. `enumerate.orphan_layer_file` makes this estate uncompilable, and every orphan is legitimate

Seven of the estate's nineteen layer files are addressed by no host's chain:

| File | Why nothing reaches it |
| --- | --- |
| `environments/staging.yml` | all three hosts are `production` |
| `locations/deldin.yml` | all three hosts are `patch` |
| `locations/molesworth.yml` | " |
| `locations/pentagon.yml` | " |
| `locations/shape.yml` | " |
| `roles/domaincontroller.yml` | no host carries `role: domaincontroller` |
| `stigs/server2019.yml` | all three hosts are `server2019core` |

None is a typo. Every one is a **pre-provisioned layer awaiting its first host**, which is how
a layered tree is grown: you write `locations/pentagon.yml` on the day the site is commissioned,
not on the day its first server is racked.

[Failure semantics](https://github.com/camusicjunkie/Reverie/issues/15) justified the rule from
the *pattern* side — "a typo'd filename is a typo'd pattern with worse consequences". From the
*file* side the same rule forbids writing a layer before the host that will use it. The real
estate puts a number on the false-positive rate: **7 of 19**.

This is the single largest thing the check turned up, and it re-opens a decision rather than
filling a hole.

### 7. `validate.pattern_matches_nothing` fires correctly — and is unreachable behind finding 6

Three of `Datum.yml`'s `lookup_options` entries target key paths no layer in the tree defines:
`windows_features/names`, `registry_values`, and `registry_values/values`. `WindowsFeatures`
is a bare list here, never a map with a `Names` member, so the declaration has been dead since
it was written. The rule works exactly as advertised — **recorded as a win**.

But note the interaction with collect-within-abort-between: phase 2 raises seven
`enumerate.orphan_layer_file` errors and the compile stops there, so the author fixes all seven
before being told about the three dead patterns waiting in phase 4.

### 8. A policy whose shape disagrees with its data is caught by nothing

`Datum.yml` declares `Baseline: {merge_hash: deep}`. `baseline` is a **scalar fact**
(`Server`). The pattern matches a real resolved key path, so `validate.pattern_matches_nothing`
is silent, and no other rule compares a strategy's shape against the value it lands on.
`WindowsFeatures: {merge_hash: deep}` against list data is the same case.

This is finding 2 seen from the data side, and it is precisely the class of silent wrongness
the map exists to eliminate: a declaration that reads as working and does nothing.

---

## C. Expressible, but lossy or awkward

### 9. Cross-tree secret references become play-time Jinja, and provenance stops at the string

`Baselines/Server.yml` and `Roles/DomainController.yml` both reach
`$Datum.Global.Domain.DomainJoinCredentials`. With cross-tree references deleted and `Global`
demoted to the floor, the call sites become:

```yaml
credential: "{{ reverie.domain_admin_password }}"
```

Inert deferred Jinja, resolved by Ansible at play time. It works and needs no new machinery.
What changes is that **Reverie no longer resolves the reference**, so:

- RSOP shows the literal string, not the secret's provenance — where
  [Expressions and resolution purity](https://github.com/camusicjunkie/Reverie/issues/11)
  promised provenance that is "total and structural";
- the compile cannot distinguish a live reference from a typo. `{{ reverie.domain_join_pasword }}`
  compiles clean and fails at play time, which is the failure class the balance-check-never-parse
  rule accepts by design.

That is the real price of deleting absolute references on this estate. It is payable, but it
belongs in the spec as a stated cost rather than as something an implementer discovers.

### 10. Three expression uses translate to deferred Jinja and get *better* — a win

`ComputerSettings.Description` is `"$($Node.Role) in $($Node.Environment)"`, evaluated by
Datum on the build machine. It becomes `"{{ reverie.role }} in {{ reverie.environment }}"`,
and `ComputerSettings.Name` becomes `"{{ inventory_hostname }}"`. Position-is-the-discriminator
carries both with no loss and no build-machine dependency. The no-evaluator decision costs
this estate less than the expected-friction list implies.

### 11. `teams/platforms.yml` translates to nothing at all

Its entire content was `DscTagging.Layers` — the provenance list `reverie_meta.layers` now
generates. One whole rung of the estate's eight-rung chain existed only to carry provenance by
hand. Not a gap; evidence that `reverie_meta` earns its place.

### 12. The out-of-scope carve-out is larger than the file count suggests

`LcmConfig` accounts for six of `Datum.yml`'s twenty-four `lookup_options` entries, and
`Baselines/DscLcm.yml` is the largest data file in the tree. The translated estate is materially
smaller and thinner than the source. Worth remembering when this tree is cited as evidence that
the reference estate is realistically sized — it is a three-host tree whose richest file is out
of scope.

### 13. The estate carries no address data of any kind

There is no `ip_address` or equivalent anywhere, so `inventory.ansible_host` is omitted and
connection falls to DNS. #16 made the field optional, so this compiles — but it means the real
estate exercises none of `ansible_host`'s rules, and the invented reference estate is the only
place they will ever be tested.

### 14. Datum's bare-string shorthand has no Reverie form

`WindowsServer: hash` and `LcmConfig\ReportServerWeb: deep` use a shorthand where the value is
the strategy rather than a map. Two of `Datum.yml`'s entries are written this way. Only the map
form appears anywhere in the spec. Trivially resolved by writing the map form — but whoever
fixes the declaration language (finding 1) should say whether shorthand exists, because it
interacts with `configure.unknown_strategy`'s exact case-sensitive matching.
