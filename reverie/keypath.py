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


def winner(policies, key_path: str):
    """The single declared policy that wins for `key_path`, or None.

    Convenience over `best_match` for callers that only care about the
    outright winner and don't need to distinguish "no match" from an
    unresolved tie.
    """

    matches = best_match(policies, key_path)
    return matches[0] if matches else None


def _consume(tokens: tuple[str, ...], i: int) -> tuple[int, int, int, str | None]:
    """One token's contribution when it accounts for one shared path segment.

    Returns (next_index, literal_delta, star_delta, literal_value_or_None).
    """

    token = tokens[i]
    if token == "**":
        return i, 0, 0, None
    if token == "*":
        return i + 1, 0, 1, None
    return i + 1, 1, 0, token


def patterns_tie(first: str, second: str) -> bool:
    """Whether two distinct merge-policy patterns could tie in specificity
    on some shared concrete key path.

    Modeled as a joint automaton walking a hypothetical shared path one
    segment at a time: each pattern's `**` may either absorb the segment
    (staying put) or step aside without consuming one (an epsilon move),
    while `*` and literal tokens always consume exactly one segment. This
    searches the resulting state graph for a way to fully parse both
    patterns ending with equal (literal, star) specificity scores -- the
    same score `specificity` would compute for each, on the same concrete
    path.
    """

    a = _tokenize(first)
    b = _tokenize(second)
    la, lb = len(a), len(b)

    start = (0, 0, 0, 0, 0, 0)
    seen = {start}
    stack = [start]
    while stack:
        i, j, lit_a, star_a, lit_b, star_b = stack.pop()

        if i == la and j == lb and lit_a == lit_b and star_a == star_b:
            return True

        if i < la and a[i] == "**":
            nxt = (i + 1, j, lit_a, star_a, lit_b, star_b)
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
        if j < lb and b[j] == "**":
            nxt = (i, j + 1, lit_a, star_a, lit_b, star_b)
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)

        if i < la and j < lb:
            ni, dla, dsa, tok_a = _consume(a, i)
            nj, dlb, dsb, tok_b = _consume(b, j)
            if tok_a is None or tok_b is None or tok_a == tok_b:
                nxt = (ni, nj, lit_a + dla, star_a + dsa, lit_b + dlb, star_b + dsb)
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)

    return False


def tied_patterns(patterns) -> list[tuple[str, str]]:
    """Every pair of `patterns` that could tie in specificity on some
    shared concrete key path, earlier pattern first within each pair.
    """

    patterns = list(patterns)
    pairs: list[tuple[str, str]] = []
    for i, first in enumerate(patterns):
        for second in patterns[i + 1 :]:
            if patterns_tie(first, second):
                pairs.append((first, second))
    return pairs
