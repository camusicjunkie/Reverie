"""Issue #31: structural integrity of the closed vocabularies under spec/.

Complements tests/conftest.py's assert_diagnostic-driven coverage check
(every registry id marked implemented needs a fixture case, and every
fixture case must cite a registered id) with checks on the registry's own
shape, and that generated prose docs aren't stale.
"""

from __future__ import annotations

import sys
from pathlib import Path

from reverie import spec_registry

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_every_error_condition_id_matches_a_registered_phase():
    for id, entry in spec_registry.error_conditions().items():
        assert entry["phase"] in spec_registry.PHASES, f"{id}: unregistered phase {entry['phase']!r}"
        assert id.startswith(f"{entry['phase']}."), f"{id}: id doesn't start with its own phase"


def test_resolve_phase_has_no_error_conditions():
    # By design (docs/adr + reverie/phases/resolve.py): anything that could
    # go wrong with merge data is caught earlier, in validate.
    assert not any(entry["phase"] == "resolve" for entry in spec_registry.error_conditions().values())


def test_error_condition_ids_are_unique():
    ids = [entry["id"] for entry in spec_registry.raw_error_conditions()]
    assert len(ids) == len(set(ids))


def test_strategies_are_the_closed_set_of_seven():
    assert set(spec_registry.strategies()) == {
        "first",
        "shallow",
        "deep",
        "append",
        "unique",
        "unique_tuple",
        "deep_tuple",
    }


def test_tags_are_the_closed_set_of_three():
    assert set(spec_registry.tags()) == {"!remove", "!vault", "!secret"}


def test_every_strategy_binds_to_a_registered_value_shape():
    shapes = set(spec_registry.value_shapes())
    for id, entry in spec_registry.strategies().items():
        assert entry["shape"] in shapes, f"{id}: unregistered shape {entry['shape']!r}"


def test_deleted_ids_never_reappear():
    # Named in issue #31 as deleted with no replacement -- if one of these
    # comes back, it must be under a new id (or this test updated
    # deliberately), never silently re-added under its old name.
    deleted = {
        "enumerate.orphan_layer_file",
        "load.forbidden_tag",
        "configure.unknown_mode",
        "resolve.secret_not_comparable",
        "resolve.host_has_no_keys",
    }
    assert deleted.isdisjoint(spec_registry.error_conditions())
    assert deleted.isdisjoint(spec_registry.warnings())


def test_generated_docs_are_not_stale():
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.generate_spec_docs import OUTPUT, render

    assert OUTPUT.read_text(encoding="utf-8") == render(), (
        "docs/spec-registry.md is stale -- run `python scripts/generate_spec_docs.py`"
    )
