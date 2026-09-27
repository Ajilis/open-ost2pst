import struct

import pytest

from open_ost2pst.pst.ltp.tc import read_heap_allocation
from open_ost2pst.pst.messaging import (
    NID_ATTACHMENT_TABLE,
    NID_RECIPIENT_TABLE,
    RECIPIENT_TYPE_CC,
    PR_DISPLAY_NAME,
    PR_EMAIL_ADDRESS,
    PR_RECIPIENT_TYPE,
    PR_SMTP_ADDRESS,
    RECIPIENT_TYPE_TO,
    MessagingBuilder,
    _build_recipient_table,
)


def test_messaging_builder_tracks_recipients_and_attachments() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(inbox, subject="Hello", body="Body")

    to = builder.add_recipient(
        message,
        name="Bob",
        email="bob@example.com",
        recipient_type=RECIPIENT_TYPE_TO,
    )
    cc = builder.add_recipient(
        message,
        name="Carol",
        email="carol@example.com",
        recipient_type=RECIPIENT_TYPE_CC,
    )
    attachment = builder.add_attachment(
        message,
        filename="hello.txt",
        data=b"hello attachment",
        mime_type="text/plain",
    )

    assert [recipient.email for recipient in message.recipients] == [
        "bob@example.com",
        "carol@example.com",
    ]
    assert to.recipient_type == RECIPIENT_TYPE_TO
    assert cc.recipient_type == RECIPIENT_TYPE_CC
    assert attachment.data == b"hello attachment"

    result = builder.build()
    assert result.message_count == 1
    assert result.attachment_count == 1
    assert result.data[:4] == b"!BDN"


def test_invalid_recipient_type_is_rejected() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(inbox)

    with pytest.raises(ValueError, match="recipient_type"):
        builder.add_recipient(
            message,
            name="Nobody",
            email="nobody@example.com",
            recipient_type=99,
        )


def test_local_table_ids_match_pst_conventions() -> None:
    assert NID_ATTACHMENT_TABLE == 0x0671
    assert NID_RECIPIENT_TABLE == 0x0692


def test_large_attachment_waits_for_external_property_storage() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(inbox)
    builder.add_attachment(
        message,
        filename="large.bin",
        data=b"x" * 3581,
    )

    with pytest.raises(ValueError, match="subnode storage"):
        builder.build()


def test_recipient_table_contains_expected_rows_and_properties() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(inbox)
    builder.add_recipient(
        message,
        name="Bob",
        email="bob@example.com",
        recipient_type=RECIPIENT_TYPE_TO,
    )
    builder.add_recipient(
        message,
        name="Carol",
        email="carol@example.com",
        recipient_type=RECIPIENT_TYPE_CC,
    )

    image = _build_recipient_table(message).build()
    assert image.row_count == 2

    columns = {
        column.property_id: column
        for column in image.layout.descriptors
    }
    assert PR_RECIPIENT_TYPE in columns
    assert PR_DISPLAY_NAME in columns
    assert PR_EMAIL_ADDRESS in columns
    assert PR_SMTP_ADDRESS in columns

    matrix = read_heap_allocation(image.heap, image.row_matrix_hnid)
    row_size = image.layout.row_size

    for row_index, expected in enumerate(
        [
            ("Bob", "bob@example.com", RECIPIENT_TYPE_TO),
            ("Carol", "carol@example.com", RECIPIENT_TYPE_CC),
        ]
    ):
        row = matrix[row_index * row_size:(row_index + 1) * row_size]
        name_col = columns[PR_DISPLAY_NAME]
        email_col = columns[PR_EMAIL_ADDRESS]
        smtp_col = columns[PR_SMTP_ADDRESS]
        type_col = columns[PR_RECIPIENT_TYPE]

        recipient_type = struct.unpack_from("<I", row, type_col.ib_data)[0]
        name_hid = struct.unpack_from("<I", row, name_col.ib_data)[0]
        email_hid = struct.unpack_from("<I", row, email_col.ib_data)[0]
        smtp_hid = struct.unpack_from("<I", row, smtp_col.ib_data)[0]

        assert recipient_type == expected[2]
        assert read_heap_allocation(image.heap, name_hid) == (
            expected[0].encode("utf-16-le") + b"\x00\x00"
        )
        assert read_heap_allocation(image.heap, email_hid) == (
            expected[1].encode("utf-16-le") + b"\x00\x00"
        )
        assert read_heap_allocation(image.heap, smtp_hid) == (
            expected[1].encode("utf-16-le") + b"\x00\x00"
        )
