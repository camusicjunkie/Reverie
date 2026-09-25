# Reverie has no expression evaluator; resolution is strictly pure

Resolution is a pure function of `(source tree, host name)`, with no opt-in escape hatch. This is forced, not merely preferred: committed artifacts plus CI's recompile-no-diff check cannot coexist with an expression that touches the build machine at resolve time. Templating happens in exactly one place — the chain, in `reverie.yml` — and evaluates before any layer file is opened, so fact-circularity is impossible by construction. A `{{ … }}` inside a data value is inert deferred Jinja instead: literal text, passed through verbatim for Ansible to evaluate at play time. Position is the discriminator between the two — chain templating and deferred Jinja never share a file.

Absolute cross-tree references (Datum's `$Global` pattern) do not exist for the same reason: every directory is reachable only through the chain, with duplication the accepted cost, and "one value, many consumers" becomes the play's job rather than the resolver's.

## Consequences

A cross-tree secret reference crossing a tree boundary becomes deferred Jinja rather than a real chain address: RSOP provenance, otherwise total and structural, stops at the literal string for that value, and a typo in it compiles clean and fails only at play time (see the corresponding conformance decision on the design-spec tracker). This is accepted as a stated cost, not closed with new machinery, because closing it would require Reverie to validate against Ansible's own variable namespace at compile time — reopening exactly the purity boundary this decision exists to hold.
