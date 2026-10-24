"""Issue #65: a key below the root of `reverie.yml` that `configure` never reads.

Issue #62 (an unknown declaration dropped in silence) closed the root. The
blocks below it -- `inventory:`, `secret_backend:`, a chain entry's mapping
form -- are closed the same way, by the same mechanism, under
`configure.unknown_entry_key`.
"""

from __future__ import annotations

import pytest

from tests.conftest import assert_diagnostic, failed_compile

HEAD = 'layout: ""\n'
DEFAULTS = "defaults: defaults/common.yml\n"

CASES = {
    "inventory": (
        HEAD + "chain: []\n" + DEFAULTS + "inventory:\n  grups:\n    - role\n",
        [("grups", 5)],
    ),
    "secret_backend": (
        HEAD + "chain: []\n" + DEFAULTS + "secret_backend:\n  lookup: x\n  optons: {}\n",
        [("optons", 6)],
    ),
    "chain_entry": (
        HEAD + "chain:\n  - address: a.yml\n    optionl: true\n" + DEFAULTS,
        [("optionl", 4)],
    ),
    "merge_entry": (
        HEAD + "chain: []\n" + DEFAULTS + "merge:\n  members:\n    strategy: append\n    on_conflict: x\n",
        [("on_conflict", 7)],
    ),
    "several_in_one_block": (
        HEAD + "chain: []\n" + DEFAULTS + "inventory:\n  grups: []\n  ansible_hosts: x\n",
        [("grups", 5), ("ansible_hosts", 6)],
    ),
}


@pytest.mark.parametrize("case", CASES)
def test_an_unknown_key_below_the_root_is_named_with_its_line(fixture_dir, case):
    document, expected = CASES[case]
    source, diagnostics = failed_compile(fixture_dir, document)
    assert [(d["key"], d["line"]) for d in diagnostics] == expected
    first_key, first_line = expected[0]
    assert_diagnostic(
        diagnostics,
        "configure.unknown_entry_key",
        file=str(source / "reverie.yml"),
        key=first_key,
        line=first_line,
    )
