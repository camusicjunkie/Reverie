"""Issue #66: a key written twice in `reverie.yml`.

A layer file with a repeated key already fails the compile
(`load.duplicate_key`), because the second declaration silently discarding
the first is the quiet difference Reverie refuses to ship. `reverie.yml`
decides how every other file is read and was read under laxer rules: PyYAML
keeps the last copy, so a duplicated `merge:` dropped its policies and a
duplicated `chain:` replaced the whole layer stack, with nothing said.
"""

from __future__ import annotations

from tests.conftest import assert_diagnostic, failed_compile

REVERIE_YML = 'layout: ""\nchain: []\ndefaults: defaults/common.yml\n'


def test_a_duplicate_at_the_document_root_names_the_key_and_the_second_line(fixture_dir):
    source, diagnostics = failed_compile(fixture_dir, REVERIE_YML + "chain: []\n")

    assert [d["id"] for d in diagnostics] == ["configure.duplicate_key"]
    assert_diagnostic(
        diagnostics,
        "configure.duplicate_key",
        file=str(source / "reverie.yml"),
        key="chain",
        line=4,
    )


def test_a_duplicate_pattern_inside_merge_is_reported(fixture_dir):
    document = REVERIE_YML + "merge:\n  app/ports: append\n  app/ports: unique\n"

    source, diagnostics = failed_compile(fixture_dir, document)

    assert [d["id"] for d in diagnostics] == ["configure.duplicate_key"]
    assert_diagnostic(
        diagnostics,
        "configure.duplicate_key",
        file=str(source / "reverie.yml"),
        key="app/ports",
        line=6,
    )


def test_a_duplicate_inside_inventory_is_reported(fixture_dir):
    document = REVERIE_YML + "inventory:\n  groups: []\n  groups: []\n"

    source, diagnostics = failed_compile(fixture_dir, document)

    assert [d["id"] for d in diagnostics] == ["configure.duplicate_key"]
    assert_diagnostic(
        diagnostics,
        "configure.duplicate_key",
        file=str(source / "reverie.yml"),
        key="groups",
        line=6,
    )


def test_a_duplicate_under_a_block_configure_never_reads_is_still_reported(fixture_dir):
    document = REVERIE_YML + "secrets:\n  backend:\n    a: 1\n    a: 2\n"

    _source, diagnostics = failed_compile(fixture_dir, document)

    assert [(d["id"], d["key"], d["line"]) for d in diagnostics] == [
        ("configure.duplicate_key", "a", 7)
    ]


def test_every_duplicate_is_named_not_just_the_first(fixture_dir):
    document = REVERIE_YML + "chain: []\ndefaults: x\nchain: []\n"

    _source, diagnostics = failed_compile(fixture_dir, document)

    assert sorted((d["key"], d["line"]) for d in diagnostics) == [
        ("chain", 4),
        ("chain", 6),
        ("defaults", 5),
    ]


def test_a_duplicate_inside_an_aliased_mapping_is_reported_once_at_its_anchor(fixture_dir):
    # Issue #75: the fault is the text of the anchored mapping, written once,
    # so it is named once at the repeated declaration there. Naming it again
    # at each `*alias` would point at lines where nothing is written twice.
    document = REVERIE_YML + "x: &shared\n  k: 1\n  k: 2\ny: *shared\nz: *shared\n"

    source, diagnostics = failed_compile(fixture_dir, document)

    assert [d["id"] for d in diagnostics] == ["configure.duplicate_key"]
    assert_diagnostic(
        diagnostics,
        "configure.duplicate_key",
        file=str(source / "reverie.yml"),
        key="k",
        line=6,
    )
