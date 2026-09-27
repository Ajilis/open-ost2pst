import pytest

from open_ost2pst.pst.messaging import (
    NID_ATTACHMENT_TABLE,
    NID_RECIPIENT_TABLE,
    RECIPIENT_TYPE_CC,
    RECIPIENT_TYPE_TO,
    MessagingBuilder,
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
