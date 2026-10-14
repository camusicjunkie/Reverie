"""The prologue `compile` and `rsop` share: the phases up to and including
`validate`, in one place.

`rsop` promises to report exactly the diagnostics the `compile` it explains
would, so the phase order lives here and neither verb restates it. What the
two verbs do not share are their own argument conditions (`--output` is
`rsop`'s alone, as `<host>` is), and those interleave with the phases: so a
verb names them as hooks, which fire at the point in the sequence they are
for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from reverie import merge_walk
from reverie.phases import configure as configure_phase
from reverie.phases import enumerate as enumerate_phase
from reverie.phases import load as load_phase
from reverie.phases import validate as validate_phase
from reverie.phases.configure import SourceConfig
from reverie.phases.enumerate import EnumerateResult


@dataclass(frozen=True)
class Prologue:
    """Everything a source tree yields once the diagnostics of the first four
    phases have had their say (CONTEXT.md "Prologue")."""

    config: SourceConfig
    enumerated: EnumerateResult
    # Every host's merge walk, produced once and read by every consumer of
    # merges: validate (already run), and resolve or RSOP (issue #60).
    host_merges: list[merge_walk.HostMerges]


def run(
    source_arg: str | None,
    *,
    after_configure: Callable[[SourceConfig], None] | None = None,
    after_enumerate: Callable[[EnumerateResult], None] | None = None,
) -> Prologue:
    """Run configure, enumerate, load, the merge walk and validate.

    `after_configure` fires once `configure` has succeeded and before
    `enumerate`; `after_enumerate` once `enumerate` has. A hook that finds
    a problem raises `PhaseFailed`, ending the prologue there.
    """

    config = configure_phase.configure(source_arg)
    if after_configure is not None:
        after_configure(config)

    enumerated = enumerate_phase.enumerate_hosts(config)
    if after_enumerate is not None:
        after_enumerate(enumerated)

    loaded = load_phase.load_layers(enumerated.hosts, config.secret_backend)
    host_merges = merge_walk.walk_all(loaded, config.merge_policies)
    validate_phase.validate(
        host_merges, config.merge_policies, config.secrets, config.defaults
    )
    return Prologue(config=config, enumerated=enumerated, host_merges=host_merges)
