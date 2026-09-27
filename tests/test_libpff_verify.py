from datetime import datetime, timezone
import tempfile
from pathlib import Path

import pytest

from open_ost2pst.cli import _cmd_convert
from open_ost2pst.pst.bridge import datetime_to_filetime
from open_ost2pst.pst.messaging import MessagingBuilder
from open_ost2pst.verification import verify_store


pypff = pytest.importorskip("pypff")


def _write_source(
    path: Path,
    *,
    attachment_data: bytes,
    subject: str = "Verified subject",
) -> None:
    builder = MessagingBuilder(
        store_name="Verification Store",
        root_name="Verification Root",
    )
    inbox = builder.add_folder(builder.root, "Inbox")

    message = builder.add_message(
        inbox,
        subject=subject,
        body="Verified body",
        sender_name="Alice",
        sender_email="alice@example.com",
        delivery_filetime=datetime_to_filetime(
            datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        ),
        creation_filetime=datetime_to_filetime(
            datetime(2026, 1, 1, 3, 4, 5, tzinfo=timezone.utc)
        ),
        is_read=False,
    )
    builder.add_attachment(
        message,
        filename="verified.bin",
        data=attachment_data,
        mime_type="application/octet-stream",
    )

    path.write_bytes(builder.build().data)


def test_verify_matches_converted_pst_with_source() -> None:
    payload = bytes((index * 13) & 0xFF for index in range(100_000))

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.pst"
        destination = root / "converted.pst"

        _write_source(source, attachment_data=payload)

        assert _cmd_convert(source, destination) == 0

        report = verify_store(destination, source=source)

        assert report.ok is True
        assert report.mismatch_count == 0
        assert report.destination_manifest.folder_count == 3
        assert report.destination_manifest.message_count == 1
        assert report.destination_manifest.attachment_count == 1

        attachment = (
            next(
                folder
                for folder in report.destination_manifest.folders
                if folder.path.endswith("/Inbox")
            )
            .messages[0]
            .attachments[0]
        )
        assert attachment.size == len(payload)
        assert len(attachment.sha256) == 64


def test_verify_detects_attachment_hash_mismatch() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.pst"
        destination = root / "destination.pst"

        _write_source(source, attachment_data=b"source-bytes")
        _write_source(destination, attachment_data=b"changed-data")

        report = verify_store(destination, source=source)

        assert report.ok is False
        assert report.mismatch_count >= 1
        assert any(
            mismatch.kind == "attachment"
            and mismatch.field == "sha256"
            for mismatch in report.mismatches
        )
