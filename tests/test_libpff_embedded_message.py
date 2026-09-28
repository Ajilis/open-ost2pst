import tempfile

import pytest

from open_ost2pst.pst.messaging import (
    ATTACH_EMBEDDED_MESSAGE,
    MessagingBuilder,
    MessagingMessage,
)
from open_ost2pst.reader.pff_reader import load_mailbox
from tests._libpff_helpers import get_child_by_name, get_ipm_subtree


pypff = pytest.importorskip("pypff")
PR_ATTACH_DATA = 0x3701
PR_ATTACH_METHOD = 0x3705
PT_OBJECT = 0x000D


def _entry(item, property_id):
    record_set = item.get_record_set(0)
    if hasattr(record_set, "get_entry_by_type"):
        return record_set.get_entry_by_type(property_id)

    for index in range(record_set.get_number_of_entries()):
        entry = record_set.get_entry(index)
        if entry.get_entry_type() == property_id:
            return entry
    return None


def test_libpff_reads_embedded_message_attachment() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    parent = builder.add_message(
        inbox,
        subject="Parent message",
        body="Parent body",
    )
    embedded = MessagingMessage(
        nid=0,
        subject="Embedded subject",
        body="Embedded body",
        internet_message_id="<embedded@example.com>",
        importance=2,
    )
    builder.add_attachment(
        parent,
        filename="attached-message.msg",
        data=b"",
        mime_type="application/vnd.ms-outlook",
        embedded_message=embedded,
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
            attachment = item.get_attachment(0)

            assert _entry(attachment, PR_ATTACH_METHOD).get_data_as_integer() == ATTACH_EMBEDDED_MESSAGE
            assert _entry(attachment, PR_ATTACH_DATA).get_value_type() == PT_OBJECT
            assert attachment.get_number_of_sub_items() == 1

            attached_item = attachment.get_sub_item(0)
            assert attached_item.get_subject() == "Embedded subject"
            assert attached_item.get_plain_text_body() == b"Embedded body"
        finally:
            store.close()

        mailbox, report = load_mailbox(handle.name)
        assert report.attachments_failed == 0
        inbox_model = next(
            folder for folder in mailbox.root.folders
            if folder.name == "Inbox"
        )
        loaded_attachment = inbox_model.messages[0].attachments[0]
        assert loaded_attachment.embedded_message is not None
        assert loaded_attachment.embedded_message.subject == "Embedded subject"
        assert loaded_attachment.embedded_message.body_text == "Embedded body"
        assert loaded_attachment.embedded_message.internet_message_id == "<embedded@example.com>"
