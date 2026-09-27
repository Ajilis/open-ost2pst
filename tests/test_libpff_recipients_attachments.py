import tempfile

import pytest

from tests._libpff_helpers import get_child_by_name, get_ipm_subtree

from open_ost2pst.pst.messaging import (
    PR_DISPLAY_NAME,
    PR_EMAIL_ADDRESS,
    PR_RECIPIENT_TYPE,
    PR_SMTP_ADDRESS,
    RECIPIENT_TYPE_CC,
    RECIPIENT_TYPE_TO,
    MessagingBuilder,
)


pypff = pytest.importorskip("pypff")


def _entry_by_type(record_set, entry_type):
    if hasattr(record_set, "get_entry_by_type"):
        return record_set.get_entry_by_type(entry_type)

    for index in range(record_set.get_number_of_entries()):
        entry = record_set.get_entry(index)
        if entry.get_entry_type() == entry_type:
            return entry
    return None


def test_libpff_reads_recipients_and_attachment_subnodes() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(
        inbox,
        subject="Recipients and attachment",
        body="Body",
        sender_name="Alice",
        sender_email="alice@example.com",
    )

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

    payload = b"attachment-bytes-123456"
    builder.add_attachment(
        message,
        filename="sample.bin",
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

            # Ubuntu 24.04 currently ships pypff 20180714, whose message
            # wrapper predates get_recipients(). Newer pypff builds expose it.
            if hasattr(item, "get_recipients"):
                recipients = item.get_recipients()
                assert recipients is not None
                assert recipients.get_number_of_recipients() == 2

                first = recipients.get_recipient(0)
                second = recipients.get_recipient(1)

                first_name = _entry_by_type(first, PR_DISPLAY_NAME)
                first_email = _entry_by_type(first, PR_EMAIL_ADDRESS)
                first_smtp = _entry_by_type(first, PR_SMTP_ADDRESS)
                first_type = _entry_by_type(first, PR_RECIPIENT_TYPE)

                second_name = _entry_by_type(second, PR_DISPLAY_NAME)
                second_email = _entry_by_type(second, PR_EMAIL_ADDRESS)
                second_type = _entry_by_type(second, PR_RECIPIENT_TYPE)

                assert first_name.get_data_as_string() == "Bob"
                assert first_email.get_data_as_string() == "bob@example.com"
                assert first_smtp.get_data_as_string() == "bob@example.com"
                assert first_type.get_data_as_integer() == RECIPIENT_TYPE_TO

                assert second_name.get_data_as_string() == "Carol"
                assert second_email.get_data_as_string() == "carol@example.com"
                assert second_type.get_data_as_integer() == RECIPIENT_TYPE_CC

            assert item.get_number_of_attachments() == 1
            attachment = item.get_attachment(0)
            assert attachment is not None

            if hasattr(attachment, "get_long_filename"):
                assert attachment.get_long_filename() == "sample.bin"
            elif hasattr(attachment, "long_filename"):
                assert attachment.long_filename == "sample.bin"

            if hasattr(attachment, "get_size"):
                assert attachment.get_size() == len(payload)
            elif hasattr(attachment, "size"):
                assert attachment.size == len(payload)

            if hasattr(attachment, "seek_offset"):
                attachment.seek_offset(0, 0)
            assert hasattr(attachment, "read_buffer")
            assert attachment.read_buffer(len(payload)) == payload
        finally:
            store.close()
