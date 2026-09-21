"""Phase 3: load -- read every layer file's content under the closed value domain."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from reverie.errors import DiagnosticCollector
from reverie.phases.enumerate import HostPlan, LayerRef
from reverie.yaml_io import UnknownTagError, ValueDomainError, load_closed_domain

PHASE = "load"


@dataclass(frozen=True)
class LoadedHost:
    name: str
    # Ordered most-general to most-specific, paired with parsed content.
    layers: list[tuple[LayerRef, dict]]


def load_layers(plans: list[HostPlan]) -> list[LoadedHost]:
    collector = DiagnosticCollector(PHASE)
    cache: dict[Path, dict | None] = {}

    def read(layer: LayerRef) -> dict | None:
        if layer.path in cache:
            return cache[layer.path]

        text = layer.path.read_text(encoding="utf-8")
        try:
            data = load_closed_domain(text)
        except ValueDomainError as exc:
            collector.add(
                "load.value_outside_domain",
                file=str(layer.path),
                line=exc.line,
                kind=exc.kind,
            )
            data = None
        except UnknownTagError as exc:
            collector.add(
                "load.unknown_tag",
                file=str(layer.path),
                line=exc.line,
                tag=exc.tag,
            )
            data = None
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            collector.add(
                "load.malformed_yaml",
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
                    "load.layer_must_be_a_map",
                    file=str(layer.path),
                )
                data = None

        cache[layer.path] = data
        return data

    loaded: list[LoadedHost] = []
    for plan in plans:
        layers: list[tuple[LayerRef, dict]] = []
        for layer in plan.layers:
            data = read(layer)
            layers.append((layer, data if data is not None else {}))
        loaded.append(LoadedHost(name=plan.name, layers=layers))

    collector.raise_if_any()
    return loaded
