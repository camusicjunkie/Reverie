"""Issue #64: a `tuple_keys` that declares no identity, and one of the wrong shape.

Element identity under `unique_tuple`/`deep_tuple` *is* the declared keys
(CONTEXT.md "Strategy"), so `tuple_keys: []` asks for an identity that
cannot exist: `list_merge.elements_equal` answers False for every pair,
every group is a group of one, and `deep_tuple` silently becomes `append`.
That is degrade-and-continue, which ADR 0009 forbids -- the same fault
[an unknown declaration at the root of reverie.yml is dropped in
silence](https://github.com/camusicjunkie/Reverie/issues/62) named one
level up.

The sibling case is a `tuple_keys` of the wrong shape, which was reported
under the wrong name: `tuple_keys: name` left the parse at None and the
author was then told they had not declared the thing they are looking
straight at.
"""

from __future__ import annotations

import json

from tests.conftest import assert_diagnostic, run_reverie

DOCUMENT = (
    'layout: "{{ host.dc }}"\n'
    "chain: []\n"
    "defaults: defaults/common.yml\n"
    "merge:\n"
    "  groups:\n"
    "    strategy: {strategy}\n"
    "    tuple_keys: {tuple_keys}\n"
)


def failed_compile(fixture_dir, document: str):
    source = fixture_dir("merge_lists")
    (source / "reverie.yml").write_text(document, encoding="utf-8", newline="")

    result = run_reverie("compile", str(source))

    assert result.returncode != 0, f"expected a failed compile, got:\n{result.stdout}"
    return source, json.loads(result.stderr)


def test_an_empty_tuple_keys_under_deep_tuple_is_a_configure_error(fixture_dir):
    source, diagnostics = failed_compile(
        fixture_dir, DOCUMENT.format(strategy="deep_tuple", tuple_keys="[]")
    )

    assert [d["id"] for d in diagnostics] == ["configure.empty_tuple_keys"]
    assert_diagnostic(
        diagnostics,
        "configure.empty_tuple_keys",
        file=str(source / "reverie.yml"),
        key_path="groups",
    )


def test_an_empty_tuple_keys_under_unique_tuple_is_a_configure_error(fixture_dir):
    _source, diagnostics = failed_compile(
        fixture_dir, DOCUMENT.format(strategy="unique_tuple", tuple_keys="[]")
    )

    assert [d["id"] for d in diagnostics] == ["configure.empty_tuple_keys"]


def test_a_scalar_tuple_keys_is_malformed_not_missing(fixture_dir):
    source, diagnostics = failed_compile(
        fixture_dir, DOCUMENT.format(strategy="deep_tuple", tuple_keys="name")
    )

    assert [d["id"] for d in diagnostics] == ["configure.malformed_tuple_keys"]
    assert_diagnostic(
        diagnostics,
        "configure.malformed_tuple_keys",
        file=str(source / "reverie.yml"),
        key_path="groups",
        line=7,
    )


def test_a_tuple_keys_of_non_strings_is_malformed_not_missing(fixture_dir):
    _source, diagnostics = failed_compile(
        fixture_dir, DOCUMENT.format(strategy="deep_tuple", tuple_keys="[1, 2]")
    )

    assert [d["id"] for d in diagnostics] == ["configure.malformed_tuple_keys"]


def test_a_long_form_entry_that_omits_tuple_keys_is_still_missing(fixture_dir):
    # The guard on the three cases above: "absent", "empty" and "malformed"
    # are three conditions, and the one that was already named keeps its
    # name.
    source, diagnostics = failed_compile(
        fixture_dir,
        'layout: "{{ host.dc }}"\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  groups:\n"
        "    strategy: deep_tuple\n",
    )

    assert [d["id"] for d in diagnostics] == ["configure.missing_tuple_keys"]
    assert_diagnostic(
        diagnostics,
        "configure.missing_tuple_keys",
        file=str(source / "reverie.yml"),
        key_path="groups",
    )


def test_an_empty_tuple_keys_under_a_non_tuple_strategy_is_still_unexpected(fixture_dir):
    # `tuple_keys` means nothing at all outside the two tuple strategies,
    # so its emptiness is not the thing wrong with it here.
    _source, diagnostics = failed_compile(
        fixture_dir, DOCUMENT.format(strategy="append", tuple_keys="[]")
    )

    assert [d["id"] for d in diagnostics] == ["configure.unexpected_tuple_keys"]
