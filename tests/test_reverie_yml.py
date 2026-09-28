"""Issue #54: `reverie.reverie_yml` -- `reverie.yml` read once, with every
field carrying its position.

Exercised directly against literal documents, as `keypath` and `merge_plan`
are: what `configure` gets from a field is its value and its line together,
and a diagnostic about a field is reported through one path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from reverie import reverie_yml
from reverie.errors import DiagnosticCollector, PhaseFailed
from reverie.phases.configure import configure


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "reverie.yml"
    path.write_text(text, encoding="utf-8", newline="")
    return path


def test_a_field_yields_its_value_and_its_line_together(tmp_path):
    document = reverie_yml.read(write(tmp_path, 'layout: ""\nchain: []\ndefaults: d/c.yml\n'))

    defaults = document.field("defaults")

    assert defaults.value == "d/c.yml"
    assert defaults.line == 3
    assert defaults.present is True
    assert defaults.file == str(tmp_path / "reverie.yml")


def test_an_absent_field_has_no_value_no_line_and_is_not_present(tmp_path):
    document = reverie_yml.read(write(tmp_path, 'layout: ""\n'))

    defaults = document.field("defaults")

    assert defaults.value is None
    assert defaults.line is None
    assert defaults.present is False


def test_a_field_written_with_no_value_is_present_and_null(tmp_path):
    """`defaults:` with nothing after it is a declared field holding null --
    distinct from an absent one, because `configure`'s defaults differ
    between the two (`layout:` alone is malformed; no `layout:` at all is
    an empty layout)."""

    document = reverie_yml.read(write(tmp_path, "defaults:\n"))

    defaults = document.field("defaults")

    assert defaults.present is True
    assert defaults.value is None
    assert defaults.line == 1


def test_a_nested_field_carries_its_own_line(tmp_path):
    document = reverie_yml.read(write(tmp_path, "inventory:\n  groups:\n    - dc\n"))

    groups = document.field("inventory").field("groups")

    assert groups.value == ["dc"]
    assert groups.line == 3


def test_every_element_of_a_sequence_carries_its_own_line(tmp_path):
    document = reverie_yml.read(
        write(tmp_path, "chain:\n  - dcs/{{ host.dc }}.yml\n  - roles/{{ host.role }}.yml\n")
    )

    elements = document.field("chain").elements()

    assert [element.value for element in elements] == [
        "dcs/{{ host.dc }}.yml",
        "roles/{{ host.role }}.yml",
    ]
    assert [element.line for element in elements] == [2, 3]


def test_every_entry_of_a_mapping_carries_its_key_and_its_own_line(tmp_path):
    document = reverie_yml.read(write(tmp_path, "merge:\n  a: first\n  b/c: deep\n"))

    entries = document.field("merge").entries()

    assert [(key, entry.value, entry.line) for key, entry in entries] == [
        ("a", "first", 2),
        ("b/c", "deep", 3),
    ]


def test_navigating_into_a_field_of_the_wrong_shape_yields_absent_fields(tmp_path):
    document = reverie_yml.read(write(tmp_path, "inventory: nonsense\nchain: nonsense\n"))

    assert document.field("inventory").field("groups").present is False
    assert document.field("chain").elements() == []
    assert document.field("inventory").entries() == []


def test_shaped_yields_the_value_only_when_the_shape_matches(tmp_path):
    document = reverie_yml.read(write(tmp_path, "layout: dcs/{{ host.dc }}\nchain: []\n"))

    assert document.field("layout").shaped(str) == "dcs/{{ host.dc }}"
    assert document.field("layout").shaped(list) is None
    assert document.field("chain").shaped(list) == []
    assert document.field("nothing").shaped(str) is None


def test_reporting_against_a_field_carries_the_document_file_and_nothing_uninvited(tmp_path):
    document = reverie_yml.read(write(tmp_path, "layout: 7\n"))
    collector = DiagnosticCollector("configure")

    document.field("layout").report(collector, "configure.malformed_layout", layout=7)

    with pytest.raises(PhaseFailed) as raised:
        collector.raise_if_any()
    (diagnostic,) = raised.value.diagnostics
    assert diagnostic.id == "configure.malformed_layout"
    assert diagnostic.phase == "configure"
    assert diagnostic.fields == {"file": str(tmp_path / "reverie.yml"), "layout": 7}


def test_a_positioned_report_takes_its_line_from_the_field(tmp_path):
    document = reverie_yml.read(write(tmp_path, 'layout: ""\nchain:\n  - "{{ layer.team }}.yml"\n'))
    collector = DiagnosticCollector("configure")
    (entry,) = document.field("chain").elements()

    entry.report(collector, "configure.chain_template_unknown_namespace", line=entry.line)

    with pytest.raises(PhaseFailed) as raised:
        collector.raise_if_any()
    (diagnostic,) = raised.value.diagnostics
    assert diagnostic.fields == {"file": str(tmp_path / "reverie.yml"), "line": 3}


def test_a_malformed_document_raises_pyyaml_s_own_error(tmp_path):
    with pytest.raises(yaml.YAMLError):
        reverie_yml.read(write(tmp_path, "layout: [\n"))


def test_reverie_yml_is_read_from_disk_once_per_compile(fixture_dir, monkeypatch):
    source = fixture_dir("minimal")
    reads: list[str] = []
    original = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        reads.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    configure(str(source))

    assert reads.count(str(source / "reverie.yml")) == 1
