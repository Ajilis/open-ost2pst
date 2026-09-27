import tempfile

import pytest

from open_ost2pst.pst.messaging import MessagingBuilder
from open_ost2pst.pst.subnodes import SLBLOCK_MAX_ENTRIES
from tests._libpff_helpers import get_child_by_name, get_ipm_subtree


pypff = pytest.importorskip("pypff")


def test_libpff_resolves_attachments_through_siblock() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(
        inbox,
        subject="SIBLOCK attachments",
        body="Subnode tree test",
    )

    attachment_count = SLBLOCK_MAX_ENTRIES + 1
    expected_last = b"last-attachment-payload"

    for index in range(attachment_count):
        payload = (
            expected_last
            if index == attachment_count - 1
            else bytes([index & 0xFF])
        )
        builder.add_attachment(
            message,
            filename=f"attachment-{index:03d}.bin",
            data=payload,
            mime_type="application/octet-stream",
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
            item = inbox_item.get_sub_message(0)

            assert item.get_number_of_attachments() == attachment_count

            first = item.get_attachment(0)
            if hasattr(first, "seek_offset"):
                first.seek_offset(0, 0)
            assert first.read_buffer(1) == b"\x00"

            last = item.get_attachment(attachment_count - 1)
            if hasattr(last, "seek_offset"):
                last.seek_offset(0, 0)
            assert last.read_buffer(len(expected_last)) == expected_last

            if hasattr(last, "long_filename"):
                assert last.long_filename == (
                    f"attachment-{attachment_count - 1:03d}.bin"
                )
        finally:
            store.close()
