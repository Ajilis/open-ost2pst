import json

from open_ost2pst.cli import _cmd_convert, build_parser
from open_ost2pst.model import Folder, Mailbox, Message
from open_ost2pst.reader.pff_reader import ExtractionReport


def test_inspect_command_parses() -> None:
    args = build_parser().parse_args(["inspect", "mailbox.ost", "--json"])

    assert args.command == "inspect"
    assert args.source.name == "mailbox.ost"
    assert args.as_json is True


def test_convert_command_parses() -> None:
    args = build_parser().parse_args(
        [
            "convert",
            "source.ost",
            "target.pst",
            "--report",
            "report.json",
        ]
    )

    assert args.command == "convert"
    assert args.source.name == "source.ost"
    assert args.destination.name == "target.pst"
    assert args.report.name == "report.json"


def test_convert_command_writes_pst_and_report(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.ost"
    source.write_bytes(b"placeholder")
    destination = tmp_path / "target.pst"
    report_path = tmp_path / "report.json"

    mailbox = Mailbox(
        Folder(
            "Root",
            messages=[
                Message(
                    subject="Hello",
                    body_text="Body",
                )
            ],
        )
    )
    extraction = ExtractionReport(
        path=str(source),
        folders_seen=1,
        folders_loaded=1,
        messages_seen=1,
        messages_loaded=1,
    )

    monkeypatch.setattr(
        "open_ost2pst.cli.load_mailbox",
        lambda _source: (mailbox, extraction),
    )

    result = _cmd_convert(source, destination, report_path)

    assert result == 0
    assert destination.read_bytes()[:4] == b"!BDN"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["source"] == str(source)
    assert report["destination"] == str(destination)
    assert report["extraction"]["messages_loaded"] == 1
    assert report["writing"]["messages_written"] == 1
