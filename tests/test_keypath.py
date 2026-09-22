"""Issue #39: keypath as the sole owner of the pattern algebra.

Direct unit tests over literal key paths -- no fixture tree or subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass

from reverie import keypath


def test_literal_pattern_matches_only_itself():
    assert keypath.matches("settings/region", "settings/region")
    assert not keypath.matches("settings/region", "settings/timeout")


def test_star_matches_exactly_one_segment():
    assert keypath.matches("settings/*", "settings/region")
    assert not keypath.matches("settings/*", "settings/region/inner")
    assert not keypath.matches("settings/*", "settings")


def test_double_star_matches_zero_or_more_segments():
    assert keypath.matches("settings/**", "settings")
    assert keypath.matches("settings/**", "settings/region")
    assert keypath.matches("settings/**", "settings/region/inner")


def test_specificity_none_when_pattern_does_not_match():
    assert keypath.specificity("settings/region", "settings/timeout") is None


def test_specificity_prefers_literal_over_star():
    literal_score = keypath.specificity("settings/region", "settings/region")
    star_score = keypath.specificity("settings/*", "settings/region")
    assert literal_score > star_score


def test_specificity_finds_the_best_alignment_for_double_star():
    # "a/**" against "a/b/a" -- the "**" can absorb "b/a", "a" trailing
    # aligned with nothing, or absorb just "b" leaving "a" to align with
    # nothing further; the best alignment picks up no extra literal here
    # since the pattern has only the leading "a" literal token.
    assert keypath.specificity("a/**", "a/b/a") == (1, 0)
    assert keypath.specificity("**/b", "a/b") == (1, 0)


def test_winner_returns_none_when_nothing_matches():
    @dataclass(frozen=True)
    class Policy:
        pattern: str
        strategy: str

    policies = [Policy(pattern="settings/region", strategy="first")]
    assert keypath.winner(policies, "does/not/exist") is None


def test_winner_returns_the_most_specific_policy():
    @dataclass(frozen=True)
    class Policy:
        pattern: str
        strategy: str

    general = Policy(pattern="settings/**", strategy="shallow")
    specific = Policy(pattern="settings/region", strategy="first")
    policies = [general, specific]

    assert keypath.winner(policies, "settings/region") is specific
    assert keypath.winner(policies, "settings/timeout") is general


def test_best_match_returns_all_tied_policies():
    @dataclass(frozen=True)
    class Policy:
        pattern: str
        strategy: str

    first = Policy(pattern="a/*", strategy="first")
    second = Policy(pattern="*/b", strategy="shallow")
    policies = [first, second]

    winners = keypath.best_match(policies, "a/b")
    assert set(winners) == {first, second}


def test_identical_patterns_tie():
    assert keypath.patterns_tie("settings/region", "settings/region")


def test_disjoint_patterns_never_tie():
    assert not keypath.patterns_tie("settings/region", "settings/timeout")


def test_star_patterns_can_tie_on_a_shared_shape():
    assert keypath.patterns_tie("a/*", "*/b")


def test_double_star_patterns_can_tie():
    # "a/**" and "**/b" both score (1, 0) against the concrete path "a/b" --
    # a tie a purely structural, no-"**" comparison would miss.
    assert keypath.patterns_tie("a/**", "**/b")


def test_double_star_pattern_does_not_tie_with_unrelated_literal():
    assert not keypath.patterns_tie("a/**", "c/**")


def test_tied_patterns_reports_colliding_pairs_earlier_pattern_first():
    pairs = keypath.tied_patterns(["a/*", "*/b", "c/d"])
    assert pairs == [("a/*", "*/b")]


def test_tied_patterns_empty_when_nothing_collides():
    assert keypath.tied_patterns(["a/region", "b/timeout"]) == []
