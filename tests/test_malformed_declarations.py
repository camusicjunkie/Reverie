"""Issue #58: the `reverie.yml` declarations the compiler used to drop in silence.

Six parts of the file degraded quietly when they held the wrong shape --
`secrets:`, `secret_backend:`, `inventory:`, `chain:`, `merge:`, and a
document root holding a falsy non-mapping. Silently discarding a malformed
declaration is degrade-and-continue, which ADR 0009 forbids outright, and
for `secrets:` it disarms the plaintext guardrail (ADR 0006) while the
compile still passes.

Every case drives the real CLI (the one test seam) and asserts the
diagnostic's exact field set, per the conformance fixture shape. Each
asserts the `line` too: a shape check that cannot point at the offending
line is only half a diagnostic.

The companion cases are the ones that must *not* report -- a block written
with no value, and a blank document. Null declares nothing, which the
schema allows everywhere it allows the block to be absent; only a field
holding something of the wrong shape is malformed.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import assert_diagnostic, run_reverie

# The blocks that are a container when declared, and so have both a wrong
# shape to report and an empty declaration to allow.
CONTAINER_BLOCKS = ["chain", "merge", "secrets", "inventory", "secret_backend"]


def compile_document(fixture_dir, document: str):
    """Compile `minimal` with `document` as its whole reverie.yml."""

    source = fixture_dir("minimal")
    (source / "reverie.yml").write_text(document, encoding="utf-8", newline="")

    return source, run_reverie("compile", str(source))


def failed_compile(fixture_dir, document: str):
    source, result = compile_document(fixture_dir, document)

    assert result.returncode != 0, f"expected a failed compile, got:\n{result.stdout}"
    return source, json.loads(result.stderr)


def test_a_secrets_block_of_the_wrong_shape_is_a_configure_error(fixture_dir):
    # A `secrets:` typo'd into a mapping used to yield an empty list, which
    # disarms the plaintext guardrail without saying so (ADR 0006).
    source, diagnostics = failed_compile(
        fixture_dir,
        'layout: ""\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "secrets:\n"
        "  domain_admin: password\n",
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_secrets", file=str(source / "reverie.yml"), line=5
    )


def test_a_non_string_secret_entry_is_a_configure_error(fixture_dir):
    source, diagnostics = failed_compile(
        fixture_dir,
        'layout: ""\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "secrets:\n"
        "  - domain_admin_password\n"
        "  - {name: domain_join_password}\n",
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_secret_entry", file=str(source / "reverie.yml"), line=6
    )


def test_a_secret_backend_without_a_usable_lookup_is_a_configure_error(fixture_dir):
    source, diagnostics = failed_compile(
        fixture_dir,
        'layout: ""\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "secret_backend:\n"
        "  options: {mount_point: secret}\n",
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_secret_backend", file=str(source / "reverie.yml"), line=5
    )
    # "rather than deferring to configure.no_secret_backend" -- a backend was
    # declared, so the condition that says none was must not be what reports.
    assert [d["id"] for d in diagnostics] == ["configure.malformed_secret_backend"]


def test_an_inventory_block_of_the_wrong_shape_is_a_configure_error(fixture_dir):
    source, diagnostics = failed_compile(
        fixture_dir,
        'layout: ""\nchain: []\ndefaults: defaults/common.yml\ninventory: ip\n',
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_inventory", file=str(source / "reverie.yml"), line=4
    )


def test_inventory_groups_of_the_wrong_shape_is_a_configure_error(fixture_dir):
    source, diagnostics = failed_compile(
        fixture_dir,
        'layout: ""\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "inventory:\n"
        "  groups: env\n",
    )

    assert_diagnostic(
        diagnostics,
        "configure.malformed_inventory_groups",
        file=str(source / "reverie.yml"),
        line=5,
    )


def test_a_chain_that_is_not_a_sequence_is_a_configure_error(fixture_dir):
    # Worse than silent before the #54 prefactor: the loop was
    # `enumerate(chain_raw)`, so a mapping had its keys read as layer
    # addresses and a scalar had its characters read as one address each.
    source, diagnostics = failed_compile(
        fixture_dir, 'layout: ""\nchain: abc\ndefaults: defaults/common.yml\n'
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_chain", file=str(source / "reverie.yml"), line=2
    )


def test_a_merge_block_that_is_not_a_mapping_is_a_configure_error(fixture_dir):
    # Every declared policy discarded, so most-specific-wins quietly becomes
    # ambient `first` everywhere.
    source, diagnostics = failed_compile(
        fixture_dir,
        'layout: ""\n'
        "chain: []\n"
        "defaults: defaults/common.yml\n"
        "merge:\n"
        "  - settings: shallow\n",
    )

    assert_diagnostic(
        diagnostics, "configure.malformed_merge", file=str(source / "reverie.yml"), line=5
    )


@pytest.mark.parametrize("root", ["[]", '""', "0", "false"])
def test_a_document_root_holding_a_falsy_non_mapping_is_malformed(fixture_dir, root):
    # The check used to be `if document.value and not isinstance(...)`, so a
    # root that is a non-empty non-mapping reported while an empty one was
    # read as an empty declaration.
    source, diagnostics = failed_compile(fixture_dir, root + "\n")

    assert_diagnostic(
        diagnostics, "configure.malformed_reverie_yml", file=str(source / "reverie.yml")
    )


@pytest.mark.parametrize("block", CONTAINER_BLOCKS)
def test_a_block_written_with_no_value_declares_nothing(fixture_dir, block):
    """`secrets:` with nothing after it is a block with no secrets in it --
    the same as no `secrets:` line, and not a shape to complain about.

    The rule the document root follows, applied to every block: null
    declares nothing, anything else must have the shape the schema says.
    """

    _source, result = compile_document(
        fixture_dir, f'layout: ""\n{block}:\ndefaults: defaults/common.yml\n'
    )

    assert result.returncode == 0, f"a null `{block}:` should declare nothing:\n{result.stderr}"


@pytest.mark.parametrize("document", ["", "null\n"])
def test_a_document_root_holding_nothing_is_an_empty_declaration_not_a_malformed_root(
    fixture_dir, document
):
    """A blank file and a bare `null` declare nothing, which is a document
    the schema allows -- distinct from a root of the wrong shape.

    Such a document declares no chain and no floor, so the compile still
    fails; what it must not do is fail in `configure`.
    """

    _source, result = compile_document(fixture_dir, document)

    reported = json.loads(result.stderr) if result.returncode != 0 else []
    assert [d for d in reported if d["phase"] == "configure"] == []
