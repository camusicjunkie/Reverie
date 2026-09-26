# RSOP addresses a fold's interior by tuple key, not by index or by nesting

An RSOP record is keyed by key path, and every element of a list shares one. Under `deep_tuple` — the one strategy that merges its elements as maps — that single path stands for several merges, one per element group, each with its own per-key contests inside it. Two element groups both contributing `members` would collide on `local_groups/groups/members`, so emitting those records at all required deciding how one addresses a path *inside a particular element*.

The decision is **tuple-key addressing**, introduced as its own term: an **RSOP address** is a key path with an *element selector* — `[name=Administrators]`, the fold's declared `tuple_keys` in declaration order — appended to any segment naming a list whose elements a fold merged. Element identity as the merge itself computed it. Two alternatives were weighed and rejected:

- **Positional addressing** (`groups[0]/members`) is the cheapest and the worst to read. The index is an artifact of merge order, so it moves whenever a layer is added or reordered — the exact debugging session RSOP exists to serve is the one where layers are changing.
- **Nested records**, hanging the element group's records inside the list's own record, keeps every map key a literal key path but breaks "a flat map of key path to record", which the RSOP vocabulary states plainly. Trading the document's stated shape for the addressing problem is the wrong way round.

Selectors are deliberately *not* a widening of the **Key path** grammar. A key path is shared syntax for merge policies and declared secret keys, and neither has any use for element selection: a `merge:` pattern addresses `local_groups/groups/members` once and governs every fold of it. Only RSOP needs to tell one fold's merge from another's, so only RSOP's addresses carry selectors, and the policy a record reports is still looked up by plain key path.

A selector's values are written as YAML writes a scalar inside a flow collection — which is what `[name=admins,ttl=30]` is. YAML's own flow rules already quote everything that would otherwise be ambiguous against `[`, `]`, `=` and `,`, so the grammar carries no escape scheme of Reverie's own and two distinct elements can never render to one address. One rule YAML has no reason to apply is added: `/` separates key-path segments, so a value containing one is quoted too, or a `C:\Shares` tuple key would put a spurious segment boundary inside an address.

## Consequences

An address is stable across layer order and across a layer being added, which is what makes it quotable in a review comment or a ticket. The cost is that it is only available where the strategy declares `tuple_keys` — but that is exactly `deep_tuple`, the only strategy whose folds have an interior to address, and `configure.missing_tuple_keys` already rejects a `deep_tuple` policy that declares none, so the notion is total on the cases that need it.

The selector grammar is now a closed vocabulary with a parser obligation: anything reading RSOP addresses back must handle YAML's single-quoted form, not just bare runs. `spec/rsop-vocabulary.yml` declares the delimiters and the rendering rule so a reader is built from the spec rather than from a hand-copied literal, and the conformance case asserts the round trip against tuple keys holding every reserved character rather than only tidy ones.

Records are emitted only for merges that actually happen: nothing under `unique_tuple`, `unique` or `append`, where an element is never merged, and nothing inside an element group of one, whose lone element is already the answer. So an absent address is a positive statement — no merge occurred there — rather than a coverage gap.
