# Reverie emits inventory groups for targeting only; it never emits `group_vars`

Reverie emits one static `inventory/hosts.yml` carrying host names, group membership, and `ansible_host` — nothing else. Groups are generated one per distinct value of each fact declared in `inventory.groups:`, but they carry no data of their own.

This is arithmetic, not taste: `host_vars/` sits at precedence rung 9 (see [ADR-0004](0004-namespaced-host-vars.md)), and every group rung in Ansible's precedence order sits below it. A chain-mirroring group hierarchy that also carried data would be structurally incapable of overriding Reverie's resolved values — a lie about precedence baked into the inventory itself. Emitting the inventory at all is mandatory, since `host_vars/` is inert unless a host appears in it.

## Consequences

`groups[...]` / `group_names` remains the only cross-host query mechanism available to plays. Hand-written `group_vars/`, sitting below rung 9, stays legitimate as playbook-adjacent configuration — beneath Reverie, which is the correct relationship.
