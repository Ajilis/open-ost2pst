import json
import tempfile
from pathlib import Path

import pytest

from open_ost2pst.cli import _cmd_convert
from open_ost2pst.pst.messaging import MessagingBuilder
from tests._libpff_helpers import get_child_by_name, get_ipm_subtree


pypff = pytest.importorskip("pypff")


def test_end_to_end_convert_reader_model_writer_libpff() -> None:
    source_builder = MessagingBuilder(
        store_name="Source Store",
        root_name="Source Root",
    )
    inbox = source_builder.add_folder(source_builder.root, "Inbox")
    message = source_builder.add_message(
        inbox,
        subject="End-to-end subject",
        body="End-to-end body",
        sender_name="Alice",
        sender_email="alice@example.com",
        is_read=False,
    )
    payload = b"end-to-end-attachment"
    source_builder.add_attachment(
        message,
        filename="e2e.bin",
        data=payload,
        mime_type="application/octet-stream",
    )

    source_bytes = source_builder.build().data

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.pst"
        destination = root / "converted.pst"
        report_path = root / "converted.report.json"
        source.write_bytes(source_bytes)

        exit_code = _cmd_convert(source, destination, report_path)

        assert exit_code == 0
        assert destination.is_file()

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["extraction"]["messages_loaded"] == 1
        assert report["extraction"]["attachments_loaded"] == 1
        assert report["writing"]["messages_written"] == 1
        assert report["writing"]["attachments_written"] == 1

        store = pypff.file()
        store.open(str(destination))
        try:
            converted_root = get_ipm_subtree(store)
            assert converted_root.get_name() == "Source Root"

            converted_inbox = get_child_by_name(converted_root, "Inbox")
            assert converted_inbox.get_name() == "Inbox"
            assert converted_inbox.get_number_of_sub_messages() == 1

            converted_message = converted_inbox.get_sub_message(0)
            assert converted_message.get_subject() == "End-to-end subject"
            assert converted_message.get_plain_text_body() == b"End-to-end body"
            assert converted_message.get_number_of_attachments() == 1

            attachment = converted_message.get_attachment(0)
            if hasattr(attachment, "seek_offset"):
                attachment.seek_offset(0, 0)
            assert attachment.read_buffer(len(payload)) == payload
        finally:
            store.close()
