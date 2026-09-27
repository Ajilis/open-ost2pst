import json

from types import SimpleNamespace

from open_ost2pst.cli import _cmd_convert, _cmd_verify, build_parser
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
    monkeypatch.setattr(
        "open_ost2pst.cli.verify_against_mailbox",
        lambda destination, mailbox, source_label="": SimpleNamespace(
            ok=True,
            mismatch_count=0,
            to_dict=lambda: {
                "ok": True,
                "mismatch_count": 0,
                "source": source_label,
                "destination": str(destination),
            },
        ),
    )

    result = _cmd_convert(source, destination, report_path)

    assert result == 0
    assert destination.read_bytes()[:4] == b"!BDN"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["source"] == str(source)
    assert report["destination"] == str(destination)
    assert report["extraction"]["messages_loaded"] == 1
    assert report["writing"]["messages_written"] == 1
    assert report["verification"]["ok"] is True
    assert report["verification"]["mismatch_count"] == 0


def test_verify_command_parses_source_json_and_report() -> None:
    args = build_parser().parse_args(
        [
            "verify",
            "output.pst",
            "--source",
            "source.ost",
            "--json",
            "--report",
            "verify.json",
        ]
    )

    assert args.command == "verify"
    assert args.pst.name == "output.pst"
    assert args.source.name == "source.ost"
    assert args.as_json is True
    assert args.report.name == "verify.json"


def test_verify_command_writes_report(tmp_path, monkeypatch, capsys) -> None:
    pst = tmp_path / "output.pst"
    pst.write_bytes(b"placeholder")
    source = tmp_path / "source.ost"
    source.write_bytes(b"placeholder")
    report_path = tmp_path / "verify.json"

    fake_report = SimpleNamespace(
        ok=True,
        mismatch_count=0,
        mismatches=(),
        mismatches_truncated=False,
        destination_manifest=SimpleNamespace(
            folder_count=2,
            message_count=1,
            attachment_count=1,
        ),
        to_dict=lambda: {
            "destination": str(pst),
            "source": str(source),
            "ok": True,
            "mismatch_count": 0,
        },
    )

    monkeypatch.setattr(
        "open_ost2pst.cli.verify_store",
        lambda destination, source=None: fake_report,
    )

    result = _cmd_verify(
        pst,
        source=source,
        as_json=True,
        report_path=report_path,
    )

    assert result == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["mismatch_count"] == 0

    stdout = capsys.readouterr().out
    assert '"ok": true' in stdout.lower()


def test_verify_command_returns_failure_for_mismatch(
    tmp_path,
    monkeypatch,
) -> None:
    pst = tmp_path / "output.pst"
    pst.write_bytes(b"placeholder")

    fake_report = SimpleNamespace(
        ok=False,
        mismatch_count=1,
        mismatches=(object(),),
        mismatches_truncated=False,
        destination_manifest=SimpleNamespace(
            folder_count=1,
            message_count=1,
            attachment_count=0,
        ),
        to_dict=lambda: {"ok": False, "mismatch_count": 1},
    )

    monkeypatch.setattr(
        "open_ost2pst.cli.verify_store",
        lambda destination, source=None: fake_report,
    )

    assert _cmd_verify(pst) == 6
