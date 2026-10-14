"""The shared prologue of `compile` and `rsop`: the phase order is written
once, and a verb's own checks fire at the points it names."""

from __future__ import annotations

import pytest

from reverie import prologue
from reverie.errors import PhaseFailed
from tests.conftest import FIXTURES_DIR


def test_prologue_yields_config_enumeration_and_every_hosts_merges():
    result = prologue.run(str(FIXTURES_DIR / "inventory"))

    assert {plan.name for plan in result.enumerated.hosts} == {"host1", "host2"}
    assert {walked.name for walked in result.host_merges} == {"host1", "host2"}


def test_verb_checks_fire_between_the_phases_they_are_named_for():
    events: list[str] = []

    prologue.run(
        str(FIXTURES_DIR / "inventory"),
        after_configure=lambda config: events.append(f"configure:{config.root.name}"),
        after_enumerate=lambda enumerated: events.append(f"enumerate:{len(enumerated.hosts)}"),
    )

    assert events == ["configure:inventory", "enumerate:2"]


def test_a_failing_check_stops_the_later_phases():
    def fail(_config):
        raise PhaseFailed([])

    def must_not_run(_enumerated):
        raise AssertionError("enumerate ran after configure's check failed")

    with pytest.raises(PhaseFailed):
        prologue.run(
            str(FIXTURES_DIR / "inventory"), after_configure=fail, after_enumerate=must_not_run
        )
