"""Phase 3: load -- read every layer file's content under the closed value domain."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from reverie.errors import DiagnosticCollector
from reverie.phases.configure import SecretBackend
from reverie.phases.enumerate import HostPlan, LayerRef
from reverie.yaml_io import (
    Remove,
    Secret,
    SourceConditionError,
    load_closed_domain,
)

PHASE = "load"


def _contains_secret(value: object) -> bool:
    if isinstance(value, Secret):
        return True
    if isinstance(value, Remove):
        return _contains_secret(value.value)
    if isinstance(value, dict):
        return any(_contains_secret(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_secret(v) for v in value)
    return False


@dataclass(frozen=True)
class LoadedHost:
    name: str
    # Ordered most-general to most-specific, paired with parsed content.
    layers: list[tuple[LayerRef, dict]]


def load_layers(plans: list[HostPlan], secret_backend: SecretBackend | None = None) -> list[LoadedHost]:
    collector = DiagnosticCollector(PHASE)
    cache: dict[Path, dict | None] = {}
    host_files = {plan.file for plan in plans}

    def read(layer: LayerRef) -> dict | None:
        if layer.path in cache:
            return cache[layer.path]

        text = layer.path.read_text(encoding="utf-8")
        try:
            data = load_closed_domain(text, host_file=layer.path in host_files)
        except SourceConditionError as exc:
            # The condition names itself and names its own fields; the
            # file is this phase's to add, being the one field it knows
            # and the read doesn't.
            collector.add(exc.condition, **exc.declared_fields(file=str(layer.path)))
            data = None
        except yaml.YAMLError as exc:
            # PyYAML's own exception, the one violation that genuinely
            # needs translating -- malformed YAML is reported by a foreign
            # library that knows nothing of Reverie's conditions.
            mark = getattr(exc, "problem_mark", None)
            collector.add(
                "load.invalid_yaml",
                file=str(layer.path),
                line=(mark.line + 1) if mark else None,
                detail=str(exc),
            )
            data = None
        else:
            if data is None:
                data = {}
            elif not isinstance(data, dict):
                collector.add(
                    "load.document_not_a_map",
                    file=str(layer.path),
                    line=None,
                )
                data = None

        cache[layer.path] = data
        return data

    seen_names: set[str] = set()
    for plan in plans:
        # A host's identity is its filename stem (CONTEXT.md "Host"), so two
        # files at different depths under hosts/ can claim the same host.
        if plan.name in seen_names:
            collector.add("load.duplicate_host_name")
        seen_names.add(plan.name)

    loaded: list[LoadedHost] = []
    for plan in plans:
        layers: list[tuple[LayerRef, dict]] = []
        for layer in plan.layers:
            data = read(layer)
            layers.append((layer, data if data is not None else {}))
        loaded.append(LoadedHost(name=plan.name, layers=layers))

    if secret_backend is None and any(
        _contains_secret(data) for host in loaded for _layer, data in host.layers
    ):
        # Detectable only now that layer files are parsed, but fixed by
        # the design tracker as a `configure` condition -- a `!secret` tag
        # is a reverie.yml-declaration problem, not a load-mechanics one.
        collector.add("configure.no_secret_backend", phase="configure")

    collector.raise_if_any()
    return loaded
