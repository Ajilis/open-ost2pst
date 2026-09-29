from pathlib import Path
from types import SimpleNamespace

import pytest

from open_ost2pst.conversion import (
    ConversionVerificationError,
    convert_file,
)
from open_ost2pst.model import Attachment, Folder, Mailbox, Message
from open_ost2pst.pst.bridge import WriteReport
from open_ost2pst.reader.pff_reader import ExtractionReport, InspectionStats


class _FakePst:
    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_bytes(b"!BDNfake")
        return target


class _FakeBuildResult:
    pst = _FakePst()


class _FakeBuilder:
    def write(self, path: str | Path, *, partial_callback=None) -> Path:
        target = Path(path)
        partial = target.with_name(f".{target.name}.test.partial")
        partial.write_bytes(b"!BDNfake")
        if partial_callback is not None:
            partial_callback(partial)
        partial.replace(target)
        return target


def _mailbox() -> Mailbox:
    return Mailbox(
        Folder(
            "Root",
            messages=[
                Message(
                    subject="Hello",
                    attachments=[
                        Attachment(filename="a.bin", data=b"abc")
                    ],
                )
            ],
            folders=[Folder("Archive")],
        )
    )


def test_convert_file_reports_monotonic_progress(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.ost"
    source.write_bytes(b"source")
    destination = tmp_path / "output.pst"
    report_path = tmp_path / "output.report.json"

    mailbox = _mailbox()

    monkeypatch.setattr(
        "open_ost2pst.conversion.inspect_store",
        lambda path: InspectionStats(
            path=str(path),
            folders=2,
            messages=1,
            attachments=1,
        ),
    )

    def fake_load(path, *, progress_callback=None):
        report = ExtractionReport(path=str(path))
        for field in (
            "folders_loaded",
            "messages_loaded",
            "attachments_loaded",
            "folders_loaded",
        ):
            setattr(report, field, getattr(report, field) + 1)
            if progress_callback is not None:
                progress_callback(report)
        return mailbox, report

    monkeypatch.setattr(
        "open_ost2pst.conversion.load_mailbox",
        fake_load,
    )

    def fake_bridge(_mailbox, *, progress_callback=None):
        report = WriteReport(
            folders_read=2,
            messages_read=1,
            attachments_read=1,
        )
        for field in (
            "folders_written",
            "messages_written",
            "attachments_written",
            "folders_written",
        ):
            setattr(report, field, getattr(report, field) + 1)
            if progress_callback is not None:
                progress_callback(report)
        return _FakeBuilder(), report

    monkeypatch.setattr(
        "open_ost2pst.conversion.mailbox_to_messaging",
        fake_bridge,
    )

    verification = SimpleNamespace(
        ok=True,
        mismatch_count=0,
        to_dict=lambda: {"ok": True, "mismatch_count": 0},
    )
    monkeypatch.setattr(
        "open_ost2pst.conversion.verify_against_mailbox",
        lambda destination, mailbox, source_label="": verification,
    )

    updates = []
    result = convert_file(
        source,
        destination,
        report_path=report_path,
        progress_callback=updates.append,
    )

    assert result.ok is True
    assert destination.read_bytes() == b"!BDNfake"
    assert report_path.is_file()

    checkpoint_path = destination.with_suffix(".conversion-state.json")
    assert checkpoint_path.is_file()
    checkpoint = __import__("json").loads(
        checkpoint_path.read_text(encoding="utf-8")
    )
    assert checkpoint["status"] == "success"
    assert checkpoint["percent"] == 100
    assert checkpoint["output"]["destination_exists"] is True

    report_data = __import__("json").loads(
        report_path.read_text(encoding="utf-8")
    )
    assert report_data["status"] == "success"

    percentages = [update.percent for update in updates]
    assert percentages[0] == 0
    assert percentages[-1] == 100
    assert percentages == sorted(percentages)
    assert 55 in percentages
    assert 80 in percentages
    assert 87 in percentages
    assert 92 in percentages


def test_convert_file_never_overwrites_source(tmp_path) -> None:
    source = tmp_path / "source.pst"
    source.write_bytes(b"source")

    with pytest.raises(ValueError, match="different from the source"):
        convert_file(source, source, overwrite=True)

    assert source.read_bytes() == b"source"


def test_convert_file_refuses_existing_destination(tmp_path) -> None:
    source = tmp_path / "source.ost"
    source.write_bytes(b"source")
    destination = tmp_path / "output.pst"
    destination.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        convert_file(source, destination)

    assert destination.read_bytes() == b"existing"


def test_convert_file_raises_when_verification_fails(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.ost"
    source.write_bytes(b"source")
    destination = tmp_path / "output.pst"
    mailbox = _mailbox()

    monkeypatch.setattr(
        "open_ost2pst.conversion.inspect_store",
        lambda path: InspectionStats(
            path=str(path),
            folders=1,
            messages=1,
            attachments=1,
        ),
    )
    monkeypatch.setattr(
        "open_ost2pst.conversion.load_mailbox",
        lambda path, progress_callback=None: (
            mailbox,
            ExtractionReport(path=str(path)),
        ),
    )
    monkeypatch.setattr(
        "open_ost2pst.conversion.mailbox_to_messaging",
        lambda mailbox, progress_callback=None: (
            _FakeBuilder(),
            WriteReport(),
        ),
    )

    verification = SimpleNamespace(
        ok=False,
        mismatch_count=2,
        to_dict=lambda: {"ok": False, "mismatch_count": 2},
    )
    monkeypatch.setattr(
        "open_ost2pst.conversion.verify_against_mailbox",
        lambda destination, mailbox, source_label="": verification,
    )

    with pytest.raises(ConversionVerificationError) as exc_info:
        convert_file(source, destination)

    assert exc_info.value.result.destination == destination
    assert exc_info.value.result.verification.mismatch_count == 2


def test_convert_file_persists_failure_report_and_checkpoint(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.ost"
    source.write_bytes(b"source")
    destination = tmp_path / "failed.pst"
    report_path = tmp_path / "failed.report.json"

    monkeypatch.setattr(
        "open_ost2pst.conversion.inspect_store",
        lambda path: (_ for _ in ()).throw(RuntimeError("inspection exploded")),
    )

    with pytest.raises(RuntimeError, match="inspection exploded"):
        convert_file(
            source,
            destination,
            report_path=report_path,
            checkpoint_interval_seconds=0,
        )

    import json

    checkpoint = json.loads(
        destination.with_suffix(".conversion-state.json").read_text(
            encoding="utf-8"
        )
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert checkpoint["status"] == "failed"
    assert checkpoint["stage"] == "Analyse de la source"
    assert checkpoint["error"]["type"] == "RuntimeError"
    assert checkpoint["error"]["message"] == "inspection exploded"
    assert "inspection exploded" in checkpoint["error"]["traceback"]
    assert report["status"] == "failed"
    assert report["error"]["type"] == "RuntimeError"
