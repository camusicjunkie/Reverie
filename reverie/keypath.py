"""Key-path glob matching and specificity (CONTEXT.md "Key path").

A key path is one `/`-separated glob: `*` matches exactly one segment,
`**` matches zero or more segments, no regex, no list indices. Shared
syntax for merge policies and (later) declared secret keys.

Specificity is computed per concrete path rather than structurally on the
pattern alone, since a `**` absorbs a variable number of segments: the
score is the best (most literal-heavy) alignment among every way the
pattern can match that path.
"""

from __future__ import annotations

from functools import lru_cache


def _tokenize(pattern: str) -> tuple[str, ...]:
    return tuple(pattern.split("/")) if pattern else ()


def _segments(key_path: str) -> tuple[str, ...]:
    return tuple(key_path.split("/")) if key_path else ()


def specificity(pattern: str, key_path: str) -> tuple[int, int] | None:
    """Best (literal_matches, star_matches) score for `pattern` matching `key_path`.

    None if the pattern doesn't match at all. Higher is more specific;
    compare tuples lexicographically.
    """

    pattern_tokens = _tokenize(pattern)
    path_segments = _segments(key_path)

    @lru_cache(maxsize=None)
    def rec(i: int, j: int) -> tuple[int, int] | None:
        if i == len(pattern_tokens):
            return (0, 0) if j == len(path_segments) else None

        token = pattern_tokens[i]

        if token == "**":
            best: tuple[int, int] | None = None
            for k in range(j, len(path_segments) + 1):
                sub = rec(i + 1, k)
                if sub is not None and (best is None or sub > best):
                    best = sub
            return best

        if j == len(path_segments):
            return None

        if token == "*":
            sub = rec(i + 1, j + 1)
            return (sub[0], sub[1] + 1) if sub is not None else None

        if token == path_segments[j]:
            sub = rec(i + 1, j + 1)
            return (sub[0] + 1, sub[1]) if sub is not None else None

        return None

    return rec(0, 0)


def matches(pattern: str, key_path: str) -> bool:
    return specificity(pattern, key_path) is not None


def best_match(policies, key_path: str) -> list:
    """The declared policies with the highest specificity score for `key_path`.

    Empty if none match. More than one entry means an unresolved tie
    (should not occur once configure has rejected duplicate patterns).
    """

    scored = [(specificity(policy.pattern, key_path), policy) for policy in policies]
    scored = [(score, policy) for score, policy in scored if score is not None]
    if not scored:
        return []
    top = max(score for score, _ in scored)
    return [policy for score, policy in scored if score == top]
