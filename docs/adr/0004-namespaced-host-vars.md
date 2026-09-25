# All resolved data is namespaced under one `reverie:` key in `host_vars/`

The compiled artifact is `host_vars/<host>.yml`, with every resolved value nested under a single top-level `reverie:` key (`reverie_meta:` sits beside it, never inside it). This lands at inventory precedence rung 9, not Echelon's rung 19 — the only choice that leaves every native Ansible tool working with zero task or play changes — and the namespace is what makes that rung safe: a role's `vars/main.yml` defines `ntp_servers`, not `reverie.ntp_servers`, so any collision is deliberate rather than accidental.

## Consequences

`-e` can no longer override a single resolved key directly, and plays must wire roles explicitly (`ntp_servers: "{{ reverie.ntp_servers }}"`) instead of relying on bare variable names arriving from `host_vars/`. Both are accepted costs of keeping the artifact collision-safe. The compiler owns `host_vars/` outright: any file there without its generated header is an error, not a cleanup target.
