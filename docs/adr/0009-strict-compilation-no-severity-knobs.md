# Compilation is strict always, with no severity knobs

A compile runs through six named phases (configure, enumerate, load, validate, resolve, emit) and collects every error within a phase but aborts at the phase boundary — there is no degrade-and-continue mode, and no flag to downgrade an error to a warning. This is deliberate: a severity switch would be invisible exactly where it matters most, since a downgraded artifact is byte-identical to a correct one and CI's recompile-no-diff check would pass regardless of what got silently swallowed.

Warnings survive only under a two-part bar — legitimate in isolation, and resting on estate-wide knowledge the author of a single layer file couldn't have — and are never fatal. Emission itself is all-or-nothing: a failed compile leaves the output directory byte-identical to before, because a half-written directory produces a diff indistinguishable from a real change.

## Consequences

A clean compile may take several rounds to reach, since there's no way to push through with warnings and fix the rest later. This is accepted as the cost of an artifact whose "no diff" CI check is actually trustworthy — a strict-by-default tool that quietly has a bypass isn't strict.
