import tempfile

import pytest

from open_ost2pst.pst.messaging import MessagingBuilder
from open_ost2pst.reader.pff_reader import load_mailbox
from tests._libpff_helpers import get_child_by_name, get_ipm_subtree


pypff = pytest.importorskip("pypff")

PR_IMPORTANCE = 0x0017
PR_MESSAGE_CLASS = 0x001A
PR_SENSITIVITY = 0x0036
PR_CONVERSATION_TOPIC = 0x0070
PR_CONVERSATION_INDEX = 0x0071
PR_TRANSPORT_MESSAGE_HEADERS = 0x007D
PR_INTERNET_MESSAGE_ID = 0x1035
PR_ATTACH_CONTENT_ID = 0x3712
PR_ATTACH_CONTENT_LOCATION = 0x3713


def _entry(item, property_id):
    record_set = item.get_record_set(0)
    return record_set.get_entry_by_type(property_id)


def test_libpff_reads_advanced_message_and_attachment_metadata() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(
        inbox,
        subject="Advanced metadata",
        body="Body",
        message_class="IPM.Note.Custom",
        internet_message_id="<abc123@example.com>",
        transport_headers=(
            "From: alice@example.com\r\n"
            "Message-ID: <abc123@example.com>\r\n"
        ),
        conversation_topic="Advanced metadata",
        conversation_index=b"\x01\x02conversation-index",
        importance=2,
        sensitivity=2,
    )
    builder.add_attachment(
        message,
        filename="inline.png",
        data=b"png-data",
        mime_type="image/png",
        content_id="image001@example.com",
        content_location="images/image001.png",
    )

    result = builder.build()

    with tempfile.NamedTemporaryFile(suffix=".pst") as handle:
        handle.write(result.data)
        handle.flush()

        store = pypff.file()
        store.open(handle.name)
        try:
            ipm = get_ipm_subtree(store)
            item = get_child_by_name(ipm, "Inbox").get_sub_message(0)

            assert _entry(item, PR_MESSAGE_CLASS).get_data_as_string() == "IPM.Note.Custom"
            assert _entry(item, PR_INTERNET_MESSAGE_ID).get_data_as_string() == "<abc123@example.com>"
            assert "Message-ID: <abc123@example.com>" in _entry(
                item, PR_TRANSPORT_MESSAGE_HEADERS
            ).get_data_as_string()
            assert _entry(item, PR_CONVERSATION_TOPIC).get_data_as_string() == "Advanced metadata"
            assert bytes(_entry(item, PR_CONVERSATION_INDEX).get_data()) == b"\x01\x02conversation-index"
            assert _entry(item, PR_IMPORTANCE).get_data_as_integer() == 2
            assert _entry(item, PR_SENSITIVITY).get_data_as_integer() == 2

            attachment = item.get_attachment(0)
            assert _entry(attachment, PR_ATTACH_CONTENT_ID).get_data_as_string() == "image001@example.com"
            assert _entry(attachment, PR_ATTACH_CONTENT_LOCATION).get_data_as_string() == "images/image001.png"
        finally:
            store.close()

        mailbox, report = load_mailbox(handle.name)
        assert report.messages_failed == 0
        inbox_model = next(
            folder for folder in mailbox.root.folders
            if folder.name == "Inbox"
        )
        loaded = inbox_model.messages[0]
        assert loaded.message_class == "IPM.Note.Custom"
        assert loaded.internet_message_id == "<abc123@example.com>"
        assert loaded.conversation_topic == "Advanced metadata"
        assert loaded.conversation_index == b"\x01\x02conversation-index"
        assert loaded.importance == 2
        assert loaded.sensitivity == 2
        assert loaded.attachments[0].content_id == "image001@example.com"
        assert loaded.attachments[0].content_location == "images/image001.png"
