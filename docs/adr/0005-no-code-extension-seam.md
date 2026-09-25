# Reverie has no code extension seam of any kind

There are no plugins, handlers, entry points, or value transformers. The only extension contract is declarative configuration: a `reverie.yml` block and one tag (`!secret`, for the one external secret-store backend). The decisive argument is that a code seam cannot be specified — a Python entry-point contract is unfixturable, and would be the one part of a fixture-backed spec with nothing behind it.

This is a direct consequence of resolution having no expression evaluator (see [ADR-0003](0003-no-expression-evaluator.md)): once expressions are gone and Reverie decrypts nothing itself, purity stops needing enforcement — no sandbox, no withheld capability — because nothing executes.

## Consequences

Multiple secret backends and routing between them are out of scope for v1: one backend per estate, with no store name carried in an address, so adding a second later costs a `reverie.yml` change and zero layer-file edits. Backend authentication is supplied by the execution environment, not carried by Reverie; `reverie.yml`'s `options:` block is public by construction (it lands in every host's artifact and in git history).
