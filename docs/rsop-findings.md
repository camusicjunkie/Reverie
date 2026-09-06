# What Datum's resolved output actually looks like

Prototype notes for [Datum RSOP output prototype](https://github.com/camusicjunkie/Reverie/issues/3).

The question was whether Datum's resolved-per-node document is close enough to
Ansible host vars that Reverie's first compiler is a thin shim. The answer is
**mostly yes for the resolver, no for `Get-DatumRsop` itself** — the RSOP command
is DSC-shaped in ways that decide things Reverie has not decided yet.

## Where the evidence comes from

The tree at `D:\PowerShell\Modules\DscPlayground\source` already carries a
**committed build output** under `output/RSOP` and `output/RsopWithSource`,
produced on a machine that had the `A428BD0C…` certificate and both handler
modules present. That is better evidence than a re-run here, because this
machine has neither: the certificate is in no store, and `Datum.ProtectedData`
and `Datum.InvokeCommand` are not installed.

Both files are reproduced verbatim beside this note:

- [`NIPAT-PL-PULL01.rsop.yml`](rsop-prototype/NIPAT-PL-PULL01.rsop.yml) — the machine-consumed artifact.
- [`NIPAT-PL-PULL01.rsop-with-source.txt`](rsop-prototype/NIPAT-PL-PULL01.rsop-with-source.txt) — the human report. `.txt`, not `.yml`, for reasons in §5.

Caveats on scope: the tree holds **three nodes, all in one environment
(`Production`) and one team (`Platforms`)**, differing only by `Role`
(`Dfs`, `Dhcp`, `Pull`), and only `NIPAT-PL-PULL01` was built. `AllNodes\Staging`
and `AllNodes\Production\SQL` exist as empty directories. So this is one node's
worth of evidence, not a cross-environment sample. Every finding below is either
visible in that artifact or read off the source tree and Datum 0.40.1.

## 1. The top-level shape

One YAML document per node: a **flat, un-namespaced map**, filename = node name.
Its top-level keys are exactly three groups and nothing else:

1. **The node's own facts**, carried over verbatim from the `AllNodes` file —
   `NodeName`, `Environment`, `Team`, `Role`, `Location`, `OsStig`, `Baseline`,
   `Description`, `PSDscAllowDomainUser`, `CertificateFile` — plus `Name`, which
   `Get-DatumRsop` synthesises from `NodeName` if absent.
2. **`Configurations`**, the composition list, merged `Unique` across layers.
3. **One key per entry in `Configurations`**, each holding that composite's
   resolved map — plus `LcmConfig`, added separately because `Datum.yml` names it
   in `DscLocalConfigurationManagerKeyName`.

## 2. The composition key decides what is in the artifact — this is the big one

`Get-DatumRsop` does **not** resolve the node's whole document. It resolves
`Configurations`, then resolves *only the keys that list names*. Anything else in
the hierarchy is never looked up and never appears.

The tree proves it. These keys are defined in layers this node resolves through,
and are **absent from its artifact**:

| Key | Defined in | Why absent |
| --- | --- | --- |
| `WindowsFeatures` | `Roles/Pull.yml` | not named in any `Configurations` list |
| `InternetExplorer` | `Stigs/Server2019Core.yml` | same |
| `FilesAndFolders` | `Environments/Production.yml` | same |
| `RegistryValues` | nowhere, but `Datum.yml` declares merge options for it | same |

`Datum.yml` carries a full `lookup_options` block for `FilesAndFolders\Items`
(`UniqueKeyValTuples` on `DestinationPath`) that this node's artifact can never
exercise. **Merge policy exists for keys the RSOP never reaches.**

This matters to Reverie because **Ansible has no `Configurations` analogue.**
There is no per-node list of "things to apply" that doubles as the key manifest.
So Reverie must answer a question DscWorkshop answered implicitly:

> Which keys land in a host's artifact?

Two candidate rules, and this prototype does not settle which:

- **Resolve everything** — the union of top-level keys across every layer the
  node walks. Complete and predictable; but it resolves keys nobody asked for,
  and every key then needs a defined merge policy or a safe default.
- **Resolve what is declared** — keep a manifest key like `Configurations`.
  Cheap and explicit; but it duplicates knowledge Ansible already has in the
  play's role list, and a key missing from the manifest is invisible.

This is properly the [Compiled artifact contract](https://github.com/camusicjunkie/Reverie/issues/6)'s
first question, and it is sharper now than when that ticket was written.

Note also `DscDiagnostic: {}` in the artifact: a composed name that no layer
defines. `Get-DatumRsop` passes `-DefaultValue @{}`, so an undefined composite
becomes an **empty map** rather than an absence or an error — and it is typed as
a map even if that key is a list everywhere else.

## 3. Single-element arrays lose their list-ness

Two keys in the source are lists of one element. Both come out as **maps**.

`Baselines/Server.yml`:

```yaml
LocalGroups:
  Groups:
    - GroupName: Administrators
      Members:
        - SG-SA-ServerAdmins
        - SG-SA-ServerAdminServiceAccounts
      Credential: '[x={ $Datum.Global.Domain.DomainAdminCredentials }=]'
```

artifact:

```yaml
LocalGroups:
  Groups:
    Credential: install@contoso:*********
    GroupName: Administrators
    Members:
    - SG-SA-ServerAdmins
    - SG-SA-ServerAdminServiceAccounts
```

Same for `DscLcmMaintenanceWindows.MaintenanceWindows`. Every list with **more
than one** element survived as a list — `Configurations` (9), `DscTagging.Layers`
(8), `Members` (2).

`LocalGroups\Groups` is declared `merge_hash_array: DeepTuple`, so its collapse
is the tuple-mode data loss already catalogued. But
`DscLcmMaintenanceWindows.MaintenanceWindows` has **no `lookup_options` entry at
all** — it falls to `default_lookup_options: MostSpecific`. So this is not tuple
mode misbehaving; it is PowerShell pipeline unrolling on the way through, and it
applies to *any* single-element list anywhere in the tree.

For Ansible this is not cosmetic. A role doing `loop: "{{ LocalGroups.Groups }}"`
iterates the keys of a map instead of one group, or fails outright, purely
because the estate happened to define one group rather than two. **Reverie's spec
must state that a list of one is a list**, and the Datum-backed compiler needs a
shim, not a deferral.

## 4. Handler values are computed at resolve time — and resolution is not pure

`Datum.yml` sets `SkipDuringLoad: true` on `Datum.InvokeCommand`, so `[x={ … }=]`
values stay symbolic while the tree loads and are evaluated during the RSOP pass.
The artifact shows them fully evaluated:

| Source | Artifact |
| --- | --- |
| `Description: '[x= "$($Node.Role) in $($Node.Environment)" =]'` | `Description: Pull in Production` |
| `CertificateFile: '[x={ "C:\Temp\$($Node.NodeName).cer" }=]'` | `CertificateFile: C:\Temp\NIPAT-PL-PULL01.cer` |
| `DscTagging.Layers: ['[x={ Get-DatumSourceFile -Path $File } =]']` | the 8 layer paths, in precedence order |

The scriptblocks read node facts (`$Node.Environment`), the current file
(`$File`), and the whole tree by absolute path — `Baselines/Server.yml` reaches
the credential with `'[x={ $Datum.Global.Domain.DomainAdminCredentials }=]'`.
That last one is a **cross-tree absolute reference**, not hierarchy resolution,
and it is the only reason `Global/` is reachable at all: `Global` is not in
`ResolutionPrecedence`.

And one of them does real I/O:

```yaml
CertificateID: '[x={ [X509Certificate2]::new("C:\Temp\$($Node.Name).cer").Thumbprint } =]'
```

The artifact shows `CertificateID: A428BD0CDE918995D330D15FA0656E9CBB58236F` —
a thumbprint read off a file on the **build machine's** disk. So Datum's
resolution is not a pure function of the source tree. Two artifacts built from
identical sources on different machines can differ, and nothing in the output
records that.

Reverie has to decide whether its expression mechanism (the fog item on what
replaces `Datum.InvokeCommand`) is pure — tree and node facts only — or may touch
the environment. Purity is the precondition for a reproducible, reviewable
artifact, which is the whole reason for compiling ahead of the run.

## 5. `RsopWithSource` is a report, not data — and its attribution is unreliable

The with-source output appends the originating layer as right-aligned trailing
text on the same line. It is not parseable as the data it describes:

```
Description: Pull in Production                     AllNodes\Production\Platforms\NIPAT-PL-PULL01
DependsOn: '[DscLcmController]DscLcmController                             Baselines\DscLcm'
IisVersion: 10.0
```

Line 1 parses to a value with the path glued on. Line 2 has the annotation
**inside the quotes**. Line 3 has lost the quoting the machine artifact keeps
(`IisVersion: "10.0"`), so it would read as a float. It is a text report that
happens to look like YAML.

Worse, the attribution is **incomplete, with no discernible rule**. Values with
no layer recorded include `WindowsServer.OrgSettings`, `WindowsServer.OsRole`,
`WindowsServer.SkipRuleType`, `ComputerSettings.TimeZone`, and
`LcmConfig.ConfigurationRepositoryWeb.Server.RegistrationKey` / `ServerURL` —
while their structural siblings *are* attributed. `WindowsServer.StigVersion` and
`WindowsServer.OrgSettings` come from the same file, same map, same merge; one is
annotated and one is not. `ReportServerWeb.RegistrationKey` is annotated,
`ConfigurationRepositoryWeb.Server.RegistrationKey` is not.

And where it does annotate, it can be wrong: all eight `DscTagging.Layers`
entries are attributed to the node file, though each was contributed by a
different layer.

**Conclusion:** Datum's source attribution cannot be the provenance mechanism
Reverie relies on. Provenance has to come out of Reverie's own resolver, as
structured data, and be tested. That firms up the last bullet of the
[Compiled artifact contract](https://github.com/camusicjunkie/Reverie/issues/6).

The one provenance mechanism here that *does* work is the estate's own trick:
`DscTagging.Layers` collects `Get-DatumSourceFile -Path $File` under
`merge_basetype_array: Unique`, yielding the exact ordered layer list the node
resolved through. Reliable, but it records which layers were *walked*, not which
layer set any given key.

## 6. Key names and YAML typing

**Names are legal, not idiomatic.** Every key in the artifact matches
`[A-Za-z0-9]+` — PascalCase, no dots, dashes or spaces — so all of them are valid
Ansible variable names with no transform required. Two problems remain:

- The top-level names are **generic to the point of hazard**: `Name`,
  `Description`, `Environment`, `Role`, `Location`, `Team`, `Baseline`,
  `Configurations`. Dropped into `host_vars` unnamespaced, these collide with
  role defaults and with anything else in the estate. `Name` and `NodeName`
  additionally duplicate each other.
- PascalCase against Ansible's snake_case convention is a decision, not an
  accident — worth taking deliberately in
  [Reverie source tree layout](https://github.com/camusicjunkie/Reverie/issues/5).

**Typing does not survive the crossing, and does so selectively.** The artifact
is written by PowerShell's YAML writer and would be read by Ansible's PyYAML.
Feeding the artifact's own values to PyYAML 6:

| Value in artifact | PyYAML reads |
| --- | --- |
| `MonitorInterval: 00:15:00` | `'00:15:00'` (string) |
| `StartTime: 00:00:00` | `'00:00:00'` (string) |
| `Timespan: 24:00:00` | **`86400` (int)** |
| `LogHistoryTimeSpan: 7.00:00:00` | `'7.00:00:00'` (string) |
| `StigVersion: 2.4` | **`2.4` (float)** |
| `IisVersion: "10.0"` | `'10.0'` (string — quoted by the writer) |
| `Version: 0.3.0` | `'0.3.0'` (string) |

YAML 1.1's sexagesimal integer resolver requires a leading non-zero digit, so
`24:00:00` becomes `86400` while `00:15:00` — same key family, same file — stays
a string. Version numbers become floats unless the writer happens to quote them,
and it quotes `"10.0"` only because Datum loaded it from a quoted scalar.

So the compiler cannot rely on "emit YAML, Ansible reads YAML". It needs an
explicit serialisation rule: quote every scalar whose source type was string, or
carry types out of band. This is a constraint on the
[Compiled artifact contract](https://github.com/camusicjunkie/Reverie/issues/6),
and it is invisible until something is compared against a compiled artifact.

## 7. Secrets: the plaintext stayed out by accident

`Baselines/Server.yml` pulls the domain credential through
`Datum.ProtectedData`, which decrypts against the certificate and returns a live
`PSCredential`. The artifact shows:

```yaml
Credential: install@contoso:*********
```

The password did **not** land in the file — but only because PowerShell's YAML
writer had no representation for `PSCredential` and fell back to a masked string.
That is not a guardrail; it is a serialiser limitation, and it produced a value
that is neither the secret nor a usable reference to it. The artifact is silently
lossy.

Reverie has no `PSCredential` to hide behind. Whatever it emits for a secret must
be *chosen*. Confirms the framing of
[Secrets after ProtectedData](https://github.com/camusicjunkie/Reverie/issues/7)
and adds a requirement: **an unresolvable or unserialisable value must be an
error, not a masked string.**

## 8. Key order is not specified

The artifact's top-level order is `DscDiagnostic, Description, OsStig,
WindowsServer, Name, DscLcmController, DscTagging, …` — not source order, not
precedence order, not alphabetical. It is hash enumeration order. Both output
files from that build agree, so it is at least stable within a run, but nothing
specifies it.

Committed, reviewable, diffable artifacts were the property the compile-ahead
decision exists to preserve. A diff is only readable if key order is defined.
**Reverie must sort.**

Positive counterpart: array order *is* meaningful and correct. `Configurations`
comes out most-specific-first (`IisServer` from `Roles\Pull`, then
`Stigs\Server2019Core`, then `Baselines\Server`, then `Baselines\DscLcm`), and
`DscTagging.Layers` is in exact `ResolutionPrecedence` order. `Unique` array
merge preserves precedence order.

## 9. A missing handler module makes a node vanish silently

Reproducing the RSOP here failed in an instructive way. With
`Datum.ProtectedData` not installed and `DatumHandlersThrowOnError: true`,
`Get-FileProviderData` throws — but the tree exposes each file as a
`ScriptProperty`, so `$datum.AllNodes.Production.Platforms.'NIPAT-PL-PULL01'`
simply evaluates to **`$null`**. No error reaches the caller. A compiler looping
over nodes would emit nothing for that host and report success.

Separately, `Get-DatumRsop` sets `$node.Name = $node.NodeName` before evaluating
handlers. In this tree `NodeName` is itself `'[x={ $Node.Name }=]'`, so `Name` is
assigned an unevaluated expression referring to `Name` — evaluating it overflows
the call stack. The build only works because DscWorkshop's
`Get-FilteredConfigurationData` sets `Name` from the file's base name first.
**Node identity comes from the file path, and must be established before any
expression is evaluated.** Reverie should make that ordering explicit rather than
leaving it to a helper outside the resolver.

## 10. Is the thin-compiler assumption wrong?

Not wrong, but narrower than assumed. `Resolve-NodeProperty` — the actual
resolver — is sound, and is what the compiler should call. `Get-DatumRsop` is not
a general "resolve this node" command: it is a DSC composition driver with
`Configurations` and `LcmConfig` baked into its parameters.

So v1's compiler is thin, but it is **not** `Get-DatumRsop | ConvertTo-Yaml`. It
is:

1. Enumerate nodes from `AllNodes`, taking identity from the file path (§9).
2. Decide the key set — Reverie's own rule, not `Configurations` (§2).
3. Call `Resolve-NodeProperty` per key.
4. Re-list single-element arrays (§3).
5. Serialise with defined key order and explicit scalar quoting (§6, §8).
6. Fail loudly on unresolvable or unserialisable values (§7, §9).

Steps 2 and 4–6 are Reverie decisions the Datum-backed compiler has to implement
itself. That is still a small amount of code, and it keeps PowerShell confined to
the build container as planned — but it means the compiler is **not** a
pass-through, and the differential-test harness has to compare against
*Reverie's* output rules, not Datum's raw RSOP.
