import tempfile

import pytest

from open_ost2pst.pst.messaging import MessagingBuilder
from tests._libpff_helpers import get_child_by_name, get_ipm_subtree


pypff = pytest.importorskip("pypff")


def test_libpff_reads_large_body_attachment_and_external_contents_matrix() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")

    large_body = "B" * 20_000
    large_attachment = bytes((index * 17) & 0xFF for index in range(150_000))

    first = builder.add_message(
        inbox,
        subject="Large data",
        body=large_body,
        sender_name="Alice",
        sender_email="alice@example.com",
    )
    builder.add_attachment(
        first,
        filename="large.bin",
        data=large_attachment,
        mime_type="application/octet-stream",
    )

    # Force the Contents Table Row Matrix above the HN allocation limit so it
    # is stored as an LTP subnode rather than an HID allocation.
    for index in range(350):
        builder.add_message(
            inbox,
            subject=f"Message {index}",
            body="small",
        )

    result = builder.build()

    with tempfile.NamedTemporaryFile(suffix=".pst") as handle:
        handle.write(result.data)
        handle.flush()

        store = pypff.file()
        store.open(handle.name)
        try:
            root = get_ipm_subtree(store)
            inbox_item = get_child_by_name(root, "Inbox")

            assert inbox_item.get_number_of_sub_messages() == 351

            message = inbox_item.get_sub_message(0)
            assert message.get_subject() == "Large data"
            assert message.get_plain_text_body() == large_body.encode("utf-8")
            assert message.get_number_of_attachments() == 1

            attachment = message.get_attachment(0)
            if hasattr(attachment, "seek_offset"):
                attachment.seek_offset(0, 0)

            chunks = []
            remaining = len(large_attachment)
            while remaining:
                chunk = attachment.read_buffer(min(32768, remaining))
                assert chunk
                chunks.append(bytes(chunk))
                remaining -= len(chunk)

            assert b"".join(chunks) == large_attachment
        finally:
            store.close()
