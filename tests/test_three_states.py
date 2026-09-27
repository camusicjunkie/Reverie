"""Issue #51, user story 9: absent, `null`, and `[]` are three distinct states.

Only *absent* continues the walk to a less specific layer. `null` and `[]`
are values a layer really set, so they win their contest like any other
value and stop the walk -- "not set" and "explicitly set to null" are never
conflated.

Worth pinning precisely because all three are falsy in Python: a merge
written with `if not value` instead of a membership test would conflate
them and every other test in this suite would still pass.
"""

from __future__ import annotations

import pytest
import yaml

from tests.conftest import run_reverie


def _resolved(fixture_dir) -> dict:
    source = fixture_dir("three_states")
    result = run_reverie("compile", str(source))
    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    return artifact["reverie"]


def test_an_explicit_null_overrides_a_more_general_value(fixture_dir):
    resolved = _resolved(fixture_dir)

    # The chain layer set `null`. That is a value, so it wins and the walk
    # stops -- the floor's string is not resurrected.
    assert "nulled" in resolved
    assert resolved["nulled"] is None


def test_an_absent_key_continues_the_walk_to_a_less_specific_layer(fixture_dir):
    resolved = _resolved(fixture_dir)

    # The chain layer never mentions `untouched`, so the floor's value
    # stands. This is the one state that defers.
    assert resolved["untouched"] == "floor-value"


def test_an_empty_list_wins_outright_where_no_list_strategy_applies(fixture_dir):
    resolved = _resolved(fixture_dir)

    # `emptied` has no declared policy, so it is a most-specific-wins
    # contest. The chain layer's `[]` is the winner, not a no-op that lets
    # the floor's two elements through.
    assert resolved["emptied"] == []


def test_an_empty_list_contributes_no_elements_under_a_list_strategy(fixture_dir):
    resolved = _resolved(fixture_dir)

    # Under `append` the same `[]` behaves differently, and correctly: it
    # is merged rather than winning, and contributes nothing to the merge,
    # so the floor's element survives. The subtlest of the three states.
    assert resolved["appended"] == ["floor-element"]


@pytest.mark.story(9)
def test_the_three_states_are_pairwise_distinct_on_one_host(fixture_dir):
    resolved = _resolved(fixture_dir)

    # Stated as one assertion too, so a change that collapsed any two of
    # them fails here with the whole picture rather than in isolation.
    assert {
        "nulled": resolved["nulled"],
        "emptied": resolved["emptied"],
        "untouched": resolved["untouched"],
        "appended": resolved["appended"],
    } == {
        "nulled": None,
        "emptied": [],
        "untouched": "floor-value",
        "appended": ["floor-element"],
    }
