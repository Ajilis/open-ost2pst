"""Command-line interface for open-ost2pst."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from open_ost2pst import __version__
from open_ost2pst.pst import PstWriter
from open_ost2pst.reader.pff_reader import PffUnavailableError, inspect_store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open-ost2pst",
        description="Inspect, recover, and convert Outlook OST data.",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect an OST/PST using libpff"
    )
    inspect_parser.add_argument("source", type=Path)
    inspect_parser.add_argument(
        "--json", action="store_true", dest="as_json", help="Emit JSON"
    )

    convert_parser = subparsers.add_parser(
        "convert", help="Convert an OST to a Unicode PST"
    )
    convert_parser.add_argument("source", type=Path)
    convert_parser.add_argument("destination", type=Path)

    verify_parser = subparsers.add_parser(
        "verify", help="Verify a generated PST"
    )
    verify_parser.add_argument("pst", type=Path)

    return parser


def _cmd_inspect(source: Path, as_json: bool) -> int:
    try:
        stats = inspect_store(source)
    except FileNotFoundError:
        print(f"error: file not found: {source}")
        return 2
    except PffUnavailableError as exc:
        print(f"error: {exc}")
        return 3

    if as_json:
        print(json.dumps(stats.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"File:        {stats.path}")
        print(f"Folders:     {stats.folders}")
        print(f"Messages:    {stats.messages}")
        print(f"Attachments: {stats.attachments}")

    return 0


def _cmd_convert(source: Path, destination: Path) -> int:
    if not source.is_file():
        print(f"error: file not found: {source}")
        return 2

    writer = PstWriter()
    try:
        # The reader-to-model conversion will be connected here when the
        # mailbox extraction layer is complete.
        writer.write(None, destination)  # type: ignore[arg-type]
    except NotImplementedError as exc:
        print(f"not implemented: {exc}")
        return 4

    return 0


def _cmd_verify(pst: Path) -> int:
    if not pst.is_file():
        print(f"error: file not found: {pst}")
        return 2
    print("not implemented: PST verification is planned for the next milestone")
    return 4


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "inspect":
        return _cmd_inspect(args.source, args.as_json)
    if args.command == "convert":
        return _cmd_convert(args.source, args.destination)
    if args.command == "verify":
        return _cmd_verify(args.pst)

    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
