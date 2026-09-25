# Reverie never holds secret material

Secrets stay opaque to Reverie by construction rather than by policy check, so it structurally cannot leak plaintext it never had. v1 ships two mechanisms: `ansible-vault`-tagged scalars (`!vault`), copied verbatim into the artifact for Ansible to decrypt natively at play time; and, for the one external secret-store backend, `!secret <address>` — a tag, not a reserved map key — translated to the backend's native call at emit time. Whole-file encryption is closed, not merely unchosen: an opaque file cannot be a layer, because a merge engine needs to see the values it's merging.

Merge policy compatibility splits on whether a strategy inspects values: override, deep merge, and list concatenation work on `!vault` scalars; `unique` and tuple matching error, because salting makes ciphertext comparison meaningless and silent non-deduplication is exactly the drift this spec exists to kill. `!secret` addresses, being addresses rather than ciphertext, don't have this problem and support `unique` and tuple matching normally.

The plaintext guardrail against a value that should have been tagged is a declared list of secret key paths in `reverie.yml` — deterministic and fixture-expressible, where an entropy heuristic is not.

## Consequences

RSOP redacts `!vault` values (keeping full attribution) but shows `!secret` addresses in full, since an address isn't material. A shared secret is an ordinary key in the defaults floor — Datum's `$Global` exile for secrets doesn't need to exist here.
