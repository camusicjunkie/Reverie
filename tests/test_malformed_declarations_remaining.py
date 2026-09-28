"""Issue #59: the `reverie.yml` declarations the previous sweep left behind.

[Name the malformed reverie.yml declarations the compiler drops in
silence](https://github.com/camusicjunkie/Reverie/issues/58) named six
parts of the file that degraded quietly and deliberately stopped there.
These are the remaining five, same failure and same ADR 0009 premise
leaking: a malformed element of `inventory.groups:`, a non-string
`prefix:` within one, a non-string `inventory.ansible_host`, a
`secret_backend.options` that is not a mapping, and an `optional:` read
through `bool(...)` rather than checked.

The rule that ticket settled still holds -- null declares nothing, and
anything else must have the shape the schema says -- so each malformed
case is paired with a null case pinning that the empty declaration stays
legal.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import assert_diagnostic, run_reverie

REVERIE_YML = 'layout: ""\nchain: []\ndefaults: defaults/common.yml\n'


def compile_document(fixture_dir, document: str, fixture: str = "minimal"):
    source = fixture_dir(fixture)
    (source / "reverie.yml").write_text(document, encoding="utf-8", newline="")

    return source, run_reverie("compile", str(source))


def failed_compile(fixture_dir, document: str):
    source, result = compile_document(fixture_dir, document)

    assert result.returncode != 0, f"expected a failed compile, got:\n{result.stdout}"
    return source, json.loads(result.stderr)


def test_a_malformed_group_entry_is_a_configure_error(fixture_dir):
    # The sibling of malformed_chain_entry and malformed_secret_entry, and
    # the only entry-level drop the previous sweep left behind: the walk
    # ended at `if fact is not None:` with no `else`.
    source, diagnostics = failed_compile(
        fixture_dir, REVERIE_YML + "inventory:\n  groups:\n    - env\n    - 3\n"
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_group_entry", file=str(source / "reverie.yml"), line=7
    )


def test_a_non_string_group_prefix_is_a_configure_error(fixture_dir):
    # A discarded prefix emits the group under its unprefixed name -- a
    # silent renaming of every group the entry generates.
    source, diagnostics = failed_compile(
        fixture_dir,
        REVERIE_YML + "inventory:\n  groups:\n    - fact: role\n      prefix: [svc_]\n",
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_group_prefix", file=str(source / "reverie.yml"), line=7
    )


def test_a_non_string_ansible_host_fact_is_a_configure_error(fixture_dir):
    source, diagnostics = failed_compile(
        fixture_dir, REVERIE_YML + "inventory:\n  ansible_host: [ip]\n"
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_ansible_host", file=str(source / "reverie.yml"), line=5
    )


def test_secret_backend_options_that_are_not_a_mapping_is_a_configure_error(fixture_dir):
    # Discarded options call the backend with none rather than the ones
    # declared.
    source, diagnostics = failed_compile(
        fixture_dir,
        REVERIE_YML
        + "secret_backend:\n  lookup: community.hashi_vault.vault_kv2_get\n  options: nope\n",
    )

    assert_diagnostic(
        diagnostics,
        "configure.malformed_secret_backend_options",
        file=str(source / "reverie.yml"),
        line=6,
    )


def test_a_non_boolean_optional_flag_is_a_configure_error(fixture_dir):
    """`bool(...)` coerces rather than checks, so `optional: "no"` read as
    `True` -- a required layer silently turned optional, which is worse
    than a silent drop because it means the opposite of what it says."""

    source, diagnostics = failed_compile(
        fixture_dir,
        'layout: ""\n'
        "chain:\n"
        "  - address: dcs/one.yml\n"
        '    optional: "no"\n'
        "defaults: defaults/common.yml\n",
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_optional_flag", file=str(source / "reverie.yml"), line=4
    )


@pytest.mark.parametrize(
    "document",
    [
        "inventory:\n  ansible_host:\n",
        "secret_backend:\n  lookup: community.hashi_vault.vault_kv2_get\n  options:\n",
    ],
    ids=["ansible_host", "backend_options"],
)
def test_a_field_written_with_no_value_still_declares_nothing(fixture_dir, document):
    """The rule the previous sweep settled, held to across the fields this
    ticket adds."""

    _source, result = compile_document(fixture_dir, REVERIE_YML + document)

    assert result.returncode == 0, f"a null field should declare nothing:\n{result.stderr}"


def test_a_group_prefix_written_with_no_value_still_declares_nothing(fixture_dir):
    """Driven against the `inventory` estate, whose hosts actually carry
    the facts: a group over an ungrounded fact is `enumerate`'s complaint,
    not this ticket's, and `minimal`'s one host declares none."""

    _source, result = compile_document(
        fixture_dir,
        'layout: ""\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "inventory:\n"
        "  ansible_host: ip\n"
        "  groups:\n"
        "    - fact: role\n"
        "      prefix:\n",
        fixture="inventory",
    )

    assert result.returncode == 0, f"a null prefix should declare nothing:\n{result.stderr}"


def test_an_optional_flag_written_with_no_value_still_declares_nothing(fixture_dir):
    _source, result = compile_document(
        fixture_dir,
        'layout: ""\n'
        "chain:\n"
        "  - address: dcs/one.yml\n"
        "    optional:\n"
        "defaults: defaults/common.yml\n",
    )

    # The layer is missing and not optional, so the compile still fails --
    # in `enumerate`, for the absent file, never in `configure` for the flag.
    reported = json.loads(result.stderr) if result.returncode != 0 else []
    assert [d for d in reported if d["phase"] == "configure"] == []
