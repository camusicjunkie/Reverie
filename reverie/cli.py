from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reverie.pipeline import compile_source
from reverie.rsop import rsop_source


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reverie")
    subparsers = parser.add_subparsers(dest="verb", required=True)

    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("source", nargs="?", default=None)

    rsop_parser = subparsers.add_parser("rsop")
    rsop_parser.add_argument("source")
    rsop_parser.add_argument("host")
    rsop_parser.add_argument("--output", dest="output", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.verb == "rsop":
        result = rsop_source(args.source, args.host, args.output)
        if result.diagnostics:
            print(json.dumps([d.to_dict() for d in result.diagnostics], indent=2), file=sys.stderr)
            return 1
        if args.output:
            Path(args.output).write_bytes(result.text.encode("utf-8"))
        else:
            sys.stdout.buffer.write(result.text.encode("utf-8"))
        return 0

    result = compile_source(args.source)
    if result.diagnostics:
        print(json.dumps([d.to_dict() for d in result.diagnostics], indent=2), file=sys.stderr)
        return 1
    if result.warnings:
        print(json.dumps([w.to_dict() for w in result.warnings], indent=2), file=sys.stderr)
    return 0
