"""Loads the closed vocabularies declared under spec/.

spec/error-conditions.yml is the authoritative list of every diagnostic id
the compiler can raise; the other spec/*.yml files are its sibling closed
lists (merge strategies, tags, value shapes, RSOP vocabulary). Nothing in
this module hand-maintains a copy of that data -- tests and prose docs
both read it from here.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

SPEC_DIR = Path(__file__).resolve().parent.parent / "spec"

PHASES = ("configure", "enumerate", "load", "validate", "resolve", "emit")


def _load_yaml(name: str):
    return yaml.safe_load((SPEC_DIR / name).read_text(encoding="utf-8"))


@functools.lru_cache
def _raw_error_conditions() -> tuple[dict, ...]:
    return tuple(_load_yaml("error-conditions.yml"))


def raw_error_conditions() -> list[dict]:
    """The error-conditions.yml entries as a plain list, duplicates included."""

    return list(_raw_error_conditions())


@functools.lru_cache
def error_conditions() -> dict[str, dict]:
    """Map of diagnostic id -> its registry entry (phase, fields, implemented)."""

    return {entry["id"]: entry for entry in _raw_error_conditions()}


@functools.lru_cache
def warnings() -> dict[str, dict]:
    return {entry["id"]: entry for entry in _load_yaml("warnings.yml")}


@functools.lru_cache
def strategies() -> dict[str, dict]:
    return {entry["id"]: entry for entry in _load_yaml("strategies.yml")}


@functools.lru_cache
def tags() -> dict[str, dict]:
    return {entry["id"]: entry for entry in _load_yaml("tags.yml")}


@functools.lru_cache
def value_shapes() -> list[str]:
    return list(_load_yaml("value-shapes.yml"))


@functools.lru_cache
def contributor_outcomes() -> list[str]:
    return list(_load_yaml("contributor-outcomes.yml"))


@functools.lru_cache
def rsop_vocabulary() -> dict[str, list[str]]:
    return dict(_load_yaml("rsop-vocabulary.yml"))


def implemented_error_conditions() -> dict[str, dict]:
    return {id: entry for id, entry in error_conditions().items() if entry.get("implemented")}
