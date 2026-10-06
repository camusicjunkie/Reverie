"""Issue #51, user story 11: element equality is exact.

Same type, same value -- no case folding, no coercion. `test_merge_lists`
covers the positive half (a genuine duplicate collapses); these are the
negative half, which is what the story is actually about:

    ... so that two AD group names differing only by a typo in case are
    visibly both present in the artifact rather than silently collapsed.

Its own fixture rather than an extension of `merge_lists`, because several
cases there rewrite that estate's layer files wholesale -- keys added for
these assertions would vanish under them and leave their policies matching
nothing.
"""

from __future__ import annotations

import pytest
import yaml

from tests.conftest import run_reverie


def _resolved(fixture_dir) -> dict:
    source = fixture_dir("exact_equality")
    result = run_reverie("compile", str(source))
    assert result.returncode == 0, result.stderr
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    return artifact["reverie"]


@pytest.mark.story(11)
def test_unique_never_folds_case_so_a_typo_stays_visible(fixture_dir):
    resolved = _resolved(fixture_dir)

    # layers/core.yml: [sg-admins, SG-Admins]; defaults: [SG-Admins, SG-Estate].
    # `SG-Admins` is contributed by both layers and collapses to one entry.
    # `sg-admins` is a different element and survives beside it -- an
    # operator can see the typo in the artifact.
    assert resolved["case_variants"] == ["sg-admins", "SG-Admins", "SG-Estate"]


def test_unique_never_coerces_a_value_to_another_type(fixture_dir):
    resolved = _resolved(fixture_dir)

    # layers/core.yml: [1, true]; defaults: ['1', 'true']. Nothing matches
    # anything: an integer is not its own spelling, and neither is a bool.
    assert resolved["type_variants"] == [1, True, "1", "true"]


def test_the_surviving_elements_keep_their_own_types(fixture_dir):
    resolved = _resolved(fixture_dir)

    # Stated separately because YAML 1.1 equality would let `1 == True`
    # pass the list assertion above while the artifact carried the wrong
    # type -- the round trip has to agree on type, not just value.
    assert [type(element) for element in resolved["type_variants"]] == [int, bool, str, str]


def test_tuple_matching_is_exact_on_the_declared_keys(fixture_dir):
    resolved = _resolved(fixture_dir)

    # The same rule governs tuple_keys: `sg-admins` and `SG-Admins` are
    # different elements, so neither replaces nor merges into the other
    # and both survive whole.
    assert resolved["tuple_variants"] == [
        {"name": "sg-admins", "scope": "layer"},
        {"name": "SG-Admins", "scope": "floor"},
    ]
