from __future__ import annotations

import argparse
import json
import sys

from reverie.pipeline import compile_source


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reverie")
    subparsers = parser.add_subparsers(dest="verb", required=True)

    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("source", nargs="?", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # "compile" is the only registered subparser, so args.verb is always "compile".
    diagnostics = compile_source(args.source)
    if diagnostics:
        print(json.dumps([d.to_dict() for d in diagnostics], indent=2), file=sys.stderr)
        return 1
    return 0
