"""Issue #62: a key at the root of `reverie.yml` that `configure` never reads.

[Name the malformed reverie.yml declarations the compiler drops in
silence](https://github.com/camusicjunkie/Reverie/issues/58) and [Name the
remaining reverie.yml declarations the compiler still drops in
silence](https://github.com/camusicjunkie/Reverie/issues/59) swept the
malformed *values* under the keys the schema knows. Neither checked the
key set itself, so a misspelled field declared nothing and the read passed
over it -- the same silent degradation one level up.

Found by compiling the hand-written translation in
`docs/real-estate-translation/` for the first time: its whole
`lookup_options:` block went by without a word.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import assert_diagnostic, run_reverie

REVERIE_YML = 'layout: ""\nchain: []\ndefaults: defaults/common.yml\n'


def compile_document(fixture_dir, document: str):
    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(document, encoding="utf-8", newline="")

    return source, run_reverie("compile", str(source))


def failed_compile(fixture_dir, document: str):
    source, result = compile_document(fixture_dir, document)

    assert result.returncode != 0, f"expected a failed compile, got:\n{result.stdout}"
    return source, json.loads(result.stderr)


def test_an_unknown_declaration_is_a_configure_error(fixture_dir):
    source, diagnostics = failed_compile(fixture_dir, REVERIE_YML + "lookup_options:\n  tagging: deep\n")

    assert_diagnostic(
        diagnostics,
        "configure.unknown_declaration",
        file=str(source / "reverie.yml"),
        key="lookup_options",
        # The key's own line, not the line its block value starts on.
        line=4,
    )


def test_a_misspelled_merge_is_reported_rather_than_silently_declaring_no_policy(fixture_dir):
    # The slip that found this: `merges:` declares no merge policy, so
    # every key path falls back to ambient `first` and the artifact comes
    # out quietly different from the one the author declared.
    _source, diagnostics = failed_compile(fixture_dir, REVERIE_YML + "merges:\n  tagging: deep\n")

    assert_diagnostic(diagnostics, "configure.unknown_declaration", key="merges")


@pytest.mark.story(19)
def test_every_unknown_declaration_is_named_not_just_the_first(fixture_dir):
    _source, diagnostics = failed_compile(fixture_dir, REVERIE_YML + "version: 1\nlayers: []\n")

    assert [
        (d["key"], d["line"])
        for d in diagnostics
        if d["id"] == "configure.unknown_declaration"
    ] == [("version", 4), ("layers", 5)]


def test_every_field_the_schema_declares_is_accepted(fixture_dir):
    # The guard on the closed list itself: a field dropped from it would
    # turn a legal document into an error, which is the opposite fault.
    document = (
        'layout: ""\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  '**': first\n"
        "secrets: []\n"
        "secret_backend:\n"
        "  lookup: community.hashi_vault.vault_kv2_get\n"
        "  options: {mount_point: secret}\n"
        "inventory:\n"
        "  groups: []\n"
    )
    _source, result = compile_document(fixture_dir, document)

    assert result.returncode == 0, result.stderr
