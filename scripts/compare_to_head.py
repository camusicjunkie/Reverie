"""Shows that a refactor changed no observable behaviour.

Runs the CLI from a git ref (HEAD by default) and from the working tree over
the same fixture estates, then compares everything a user can see: each
`compile`'s exit code, stdout, stderr and owned output (host_vars/,
inventory/), and each host's `rsop`. Prints every difference and exits 1 if
there is one, 0 if the two are byte-identical.

    python scripts/compare_to_head.py                       # every fixture under tests/fixtures
    python scripts/compare_to_head.py reference_estate      # named fixtures only
    python scripts/compare_to_head.py --ref HEAD~1 layered  # compare against another ref

Use it on a behaviour-preserving change (a refactor, a module move). A change
that is meant to alter behaviour will, correctly, show differences.
"""

from __future__ import annotations

import argparse
import difflib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
OWNED_DIRECTORIES = ("host_vars", "inventory")
SOURCE_TOKEN = "<source>"


def _extract_ref(ref: str, into: Path) -> Path:
    archive = subprocess.run(
        ["git", "archive", ref, "reverie"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(into, filter="data")
    return into


def _run(code_root: Path, source: Path, *args: str) -> dict[str, bytes]:
    env = dict(os.environ, PYTHONPATH=str(code_root))
    result = subprocess.run(
        [sys.executable, "-m", "reverie", *args], cwd=source.parent, capture_output=True, env=env
    )

    def scrub(data: bytes) -> bytes:
        # Diagnostics name files by absolute path; the two runs live in
        # different temporary copies, so the copy's root is not a difference.
        text = data.decode("utf-8", errors="replace")
        for spelling in (str(source), str(source).replace("\\", "\\\\"), source.as_posix()):
            text = text.replace(spelling, SOURCE_TOKEN)
        return text.encode("utf-8")

    return {
        "exit code": str(result.returncode).encode(),
        "stdout": scrub(result.stdout),
        "stderr": scrub(result.stderr),
    }


def _owned_output(source: Path) -> dict[str, bytes]:
    snapshot = {}
    for directory in OWNED_DIRECTORIES:
        root = source / directory
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    snapshot[path.relative_to(source).as_posix()] = path.read_bytes()
    return snapshot


def _observe(code_root: Path, fixture: Path, scratch: Path) -> dict[str, bytes]:
    source = scratch / fixture.name
    shutil.copytree(fixture, source)
    observed = {}
    for key, value in _run(code_root, source, "compile", str(source)).items():
        observed[f"compile {key}"] = value
    for path, data in _owned_output(source).items():
        observed[f"compile wrote {path}"] = data
    hosts = sorted(p.stem for p in (source / "hosts").rglob("*.yml")) if (source / "hosts").is_dir() else []
    for host in hosts:
        for key, value in _run(code_root, source, "rsop", str(source), host).items():
            observed[f"rsop {host} {key}"] = value
    return observed


def _report(fixture: str, before: dict[str, bytes], after: dict[str, bytes]) -> int:
    differences = 0
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        differences += 1
        print(f"--- {fixture}: {key}")
        if old is None or new is None:
            print("    only in", "working tree" if old is None else "ref")
            continue
        diff = difflib.unified_diff(
            old.decode("utf-8", errors="replace").splitlines(),
            new.decode("utf-8", errors="replace").splitlines(),
            "ref",
            "working tree",
            lineterm="",
        )
        print("\n".join(f"    {line}" for line in diff))
    return differences


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fixtures", nargs="*", help="fixture names under tests/fixtures (default: all)")
    parser.add_argument("--ref", default="HEAD", help="git ref to compare against (default: HEAD)")
    args = parser.parse_args()

    names = args.fixtures or sorted(p.name for p in FIXTURES.iterdir() if (p / "reverie.yml").is_file())
    differences = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        ref_code = _extract_ref(args.ref, tmp_root / "ref-code")
        for name in names:
            fixture = FIXTURES / name
            before = _observe(ref_code, fixture, tmp_root / "ref" / name)
            after = _observe(REPO_ROOT, fixture, tmp_root / "work" / name)
            found = _report(name, before, after)
            print(f"{name}: {'identical' if not found else f'{found} difference(s)'} ({len(after)} observations)")
            differences += found
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
