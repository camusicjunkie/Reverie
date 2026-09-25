# Reverie is implemented directly in Python; Datum is reference material, not a reused engine

The original plan was Datum-first — reuse Datum's ~1,100-line PowerShell resolver for a v1, with a Python port behind one language-neutral spec later. Both halves of that case fell to research: the reference Datum tree showed the "thin compiler" premise was false (it is a full DSC composition driver, not a pass-through), and cataloguing Datum 0.40.1 found twelve points where its own implementation silently diverges from its documentation — the oracle fails quietly. Reusing it would only have deferred writing the Python that must be written anyway, at the price of a PowerShell build container, a shim per divergence, and an interpolation syntax confined to the PowerShell/Python intersection.

Reverie therefore goes straight to Python. Datum remains reference material — cited as evidence for a choice, never as a compatibility target — so "divergence from Datum" is not a spec concept; correctness comes from language-neutral conformance fixtures plus golden artifacts, both first-class spec deliverables.

## Consequences

The chain's interpolation syntax is free of the PowerShell/Python intersection constraint — Jinja2 is live. Every item in Datum's resolution semantics gets decided once for Reverie, positively, rather than inherited or noted as a divergence.
