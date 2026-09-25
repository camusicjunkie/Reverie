# Resolution compiles to static artifacts; nothing runs at play time

Ansible has no vocabulary for per-key merge policy at any layer — `hash_behaviour = merge` is global, dicts-only, and deprecated — so a merge engine has to be written regardless of where it runs. Reverie writes the resolved data ahead of time into committed `host_vars/` files rather than resolving it live via a `vars_plugin`, because compiling keeps the resolved-set-of-policy document diffable, testable, and reviewable (the property DscWorkshop had and Echelon lacked), keeps Ansible itself ignorant of the hierarchy so every native tool works unmodified, and every key in the precedence chain is static inventory metadata, so nothing actually needs to run at play time.

## Consequences

A runtime `vars_plugin` is out of scope by construction, not merely unbuilt; it returns only if this decision is revisited, and then as a fresh effort. CI must recompile and assert no diff, so compilation must be fully deterministic (no timestamps in output).
