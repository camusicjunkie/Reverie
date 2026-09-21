"""Phase 6: emit -- write host_vars/ and inventory/hosts.yml, all-or-nothing.

The compiler owns both output directories outright (ADR 0004): any file
in them without the generated header is left untouched and reported as
an error, never deleted as part of a "cleanup." Emission itself is
all-or-nothing (ADR 0009) -- a failed compile, including one that fails
because of an unmanaged file, leaves the directory byte-identical to
before the run, so every existing file is checked before anything is
written.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from reverie.errors import DiagnosticCollector
from reverie.phases.configure import SourceConfig
from reverie.phases.resolve import ResolvedHost
from reverie.version import COMPILER_VERSION, SPEC_VERSION
from reverie.yaml_io import has_generated_header, write_generated_file

PHASE = "emit"


def _host_artifact(config: SourceConfig, host: ResolvedHost) -> bytes:
    digest = hashlib.sha256()
    for address in host.layers_walked:
        digest.update((config.root / address).read_bytes())

    document = {
        "reverie": host.data,
        "reverie_meta": {
            "compiler_version": COMPILER_VERSION,
            "spec_version": SPEC_VERSION,
            "source_digest": f"sha256:{digest.hexdigest()}",
            "layers": host.layers_walked,
        },
    }
    return write_generated_file(document)


def _inventory(hosts: list[ResolvedHost]) -> bytes:
    document = {"all": {"hosts": {host.name: None for host in hosts}}}
    return write_generated_file(document)


def _write_atomic(dest: Path, content: bytes) -> None:
    """Write `content` to `dest` via a same-directory temp file + rename.

    A crash or write error mid-flight then leaves either the old file or
    the new one, never a truncated one -- part of emission's all-or-nothing
    guarantee (ADR 0009).
    """

    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(tmp_name, dest)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _plan_owned_directory(directory: Path, planned: dict[str, bytes], collector: DiagnosticCollector) -> list[Path]:
    """Check `directory` for unmanaged files; return the stale generated files to delete."""

    stale: list[Path] = []
    if not directory.is_dir():
        return stale

    for existing in sorted(directory.iterdir()):
        if not existing.is_file():
            # A directory, symlink, or anything else can't carry the
            # generated header, so it's always unmanaged.
            collector.add(
                "emit.unmanaged_file_in_owned_directory",
                file=str(existing),
            )
            continue
        if not has_generated_header(existing):
            collector.add(
                "emit.unmanaged_file_in_owned_directory",
                file=str(existing),
            )
            continue
        if existing.name not in planned:
            stale.append(existing)

    return stale


def emit(config: SourceConfig, hosts: list[ResolvedHost]) -> None:
    collector = DiagnosticCollector(PHASE)

    host_vars_dir = config.root / "host_vars"
    inventory_dir = config.root / "inventory"

    planned_host_files = {f"{host.name}.yml": _host_artifact(config, host) for host in hosts}
    planned_inventory_files = {"hosts.yml": _inventory(hosts)}

    stale_host_files = _plan_owned_directory(host_vars_dir, planned_host_files, collector)
    stale_inventory_files = _plan_owned_directory(inventory_dir, planned_inventory_files, collector)

    collector.raise_if_any()

    host_vars_dir.mkdir(parents=True, exist_ok=True)
    inventory_dir.mkdir(parents=True, exist_ok=True)

    for name, content in planned_host_files.items():
        _write_atomic(host_vars_dir / name, content)
    for name, content in planned_inventory_files.items():
        _write_atomic(inventory_dir / name, content)

    for stale in (*stale_host_files, *stale_inventory_files):
        stale.unlink()
