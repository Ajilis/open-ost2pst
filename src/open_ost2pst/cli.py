"""Command-line interface for open-ost2pst."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from open_ost2pst import __version__
from open_ost2pst.pst import PstWriter
from open_ost2pst.reader.pff_reader import (
    PffUnavailableError,
    inspect_store,
    load_mailbox,
)
from open_ost2pst.verification import verify_against_mailbox, verify_store


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
    convert_parser.add_argument(
        "--report",
        type=Path,
        help="Write extraction/write counters and warnings as JSON",
    )

    verify_parser = subparsers.add_parser(
        "verify", help="Verify a generated PST"
    )
    verify_parser.add_argument("pst", type=Path)
    verify_parser.add_argument(
        "--source",
        type=Path,
        help="Compare the PST against its source OST/PST",
    )
    verify_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the verification report as JSON",
    )
    verify_parser.add_argument(
        "--report",
        type=Path,
        help="Write the verification report as JSON",
    )

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


def _cmd_convert(
    source: Path,
    destination: Path,
    report_path: Path | None = None,
) -> int:
    try:
        mailbox, extraction = load_mailbox(source)
    except FileNotFoundError:
        print(f"error: file not found: {source}")
        return 2
    except PffUnavailableError as exc:
        print(f"error: {exc}")
        return 3
    except Exception as exc:
        print(f"error: OST/PST extraction failed: {exc}")
        return 5

    writer = PstWriter()
    try:
        writing = writer.write(mailbox, destination)
    except (OSError, ValueError) as exc:
        print(f"error: PST writing failed: {exc}")
        return 5

    try:
        verification = verify_against_mailbox(
            destination,
            mailbox,
            source_label=str(source),
        )
    except Exception as exc:
        print(f"error: PST was written but automatic verification failed: {exc}")
        return 6

    if report_path is not None:
        payload = {
            "source": str(source),
            "destination": str(destination),
            "extraction": extraction.to_dict(),
            "writing": writing.to_dict(),
            "verification": verification.to_dict(),
        }
        try:
            report_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            print(
                f"error: PST was written but report could not be saved: {exc}"
            )
            return 5

    print(
        f"Wrote {destination}: "
        f"{writing.folders_written} folders, "
        f"{writing.messages_written} messages, "
        f"{writing.attachments_written} attachments"
    )

    if not verification.ok:
        print(
            f"error: automatic verification found "
            f"{verification.mismatch_count} mismatch(es)"
        )
        return 6

    print("Verification OK")
    return 0


def _cmd_verify(
    pst: Path,
    source: Path | None = None,
    as_json: bool = False,
    report_path: Path | None = None,
) -> int:
    try:
        report = verify_store(pst, source=source)
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename or exc.args[0]}")
        return 2
    except PffUnavailableError as exc:
        print(f"error: {exc}")
        return 3
    except Exception as exc:
        print(f"error: PST verification failed: {exc}")
        return 6

    payload = report.to_dict()

    if report_path is not None:
        try:
            report_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"error: verification report could not be saved: {exc}")
            return 6

    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "OK" if report.ok else "FAILED"
        manifest = report.destination_manifest
        print(
            f"Verification {status}: {pst} — "
            f"{manifest.folder_count} folders, "
            f"{manifest.message_count} messages, "
            f"{manifest.attachment_count} attachments"
        )
        if source is not None:
            print(
                f"Compared with {source}: "
                f"{report.mismatch_count} mismatch(es)"
            )
        if report.mismatches_truncated:
            print(
                f"Only the first {len(report.mismatches)} mismatches "
                "are included in the report."
            )

    return 0 if report.ok else 6


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "inspect":
        return _cmd_inspect(args.source, args.as_json)
    if args.command == "convert":
        return _cmd_convert(args.source, args.destination, args.report)
    if args.command == "verify":
        return _cmd_verify(
            args.pst,
            source=args.source,
            as_json=args.as_json,
            report_path=args.report,
        )

    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
