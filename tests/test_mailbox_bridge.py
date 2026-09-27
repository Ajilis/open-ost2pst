from datetime import datetime, timezone

from open_ost2pst.model import (
    Attachment,
    Folder,
    Mailbox,
    Message,
    Recipient,
)
from open_ost2pst.pst.bridge import (
    datetime_to_filetime,
    mailbox_to_messaging,
)


def test_datetime_to_filetime_known_unix_epoch() -> None:
    assert datetime_to_filetime(
        datetime(1970, 1, 1, tzinfo=timezone.utc)
    ) == 116444736000000000


def test_mailbox_bridge_preserves_hierarchy_message_and_people() -> None:
    message = Message(
        subject="Hello",
        sender_name="Alice",
        sender_email="alice@example.com",
        body_text="Body",
        body_html="<p>Body</p>",
        is_read=False,
        recipients=[
            Recipient(
                name="Bob",
                email="bob@example.com",
                recipient_type="to",
            ),
            Recipient(
                name="Carol",
                email="carol@example.com",
                recipient_type="cc",
            ),
        ],
        attachments=[
            Attachment(
                filename="note.txt",
                data=b"attachment",
                mime_type="text/plain",
            )
        ],
    )
    mailbox = Mailbox(
        Folder(
            "Root",
            folders=[
                Folder("Inbox", messages=[message]),
            ],
        )
    )

    builder, report = mailbox_to_messaging(mailbox)

    assert builder.root.name == "Root"
    assert len(builder.root.folders) == 1

    inbox = builder.root.folders[0]
    assert inbox.name == "Inbox"
    assert len(inbox.messages) == 1

    target = inbox.messages[0]
    assert target.subject == "Hello"
    assert target.body == "Body"
    assert target.html_body == b"<p>Body</p>"
    assert target.is_read is False
    assert target.display_to == "Bob"
    assert target.display_cc == "Carol"
    assert [recipient.email for recipient in target.recipients] == [
        "bob@example.com",
        "carol@example.com",
    ]
    assert target.attachments[0].data == b"attachment"

    assert report.folders_read == 2
    assert report.folders_written == 2
    assert report.messages_read == 1
    assert report.messages_written == 1
    assert report.recipients_read == 2
    assert report.recipients_written == 2
    assert report.attachments_read == 1
    assert report.attachments_written == 1
    assert report.attachments_failed == 0


def test_mailbox_bridge_preserves_large_attachment() -> None:
    mailbox = Mailbox(
        Folder(
            "Root",
            messages=[
                Message(
                    subject="Large",
                    attachments=[
                        Attachment(
                            filename="large.bin",
                            data=b"x" * 100_000,
                        )
                    ],
                )
            ],
        )
    )

    builder, report = mailbox_to_messaging(mailbox)

    assert len(builder.root.messages[0].attachments) == 1
    assert len(builder.root.messages[0].attachments[0].data) == 100_000
    assert report.attachments_read == 1
    assert report.attachments_written == 1
    assert report.attachments_failed == 0


def test_mailbox_bridge_preserves_large_unicode_value() -> None:
    mailbox = Mailbox(
        Folder(
            "Root",
            messages=[
                Message(subject="x" * 4000),
            ],
        )
    )

    builder, report = mailbox_to_messaging(mailbox)

    subject = builder.root.messages[0].subject
    assert subject == "x" * 4000
    assert not any("truncated" in warning for warning in report.warnings)


def test_unknown_recipient_type_is_preserved_as_to_with_warning() -> None:
    mailbox = Mailbox(
        Folder(
            "Root",
            messages=[
                Message(
                    recipients=[
                        Recipient(
                            name="Unknown",
                            email="unknown@example.com",
                            recipient_type="unknown",
                        )
                    ]
                )
            ],
        )
    )

    builder, report = mailbox_to_messaging(mailbox)

    assert builder.root.messages[0].recipients[0].recipient_type == 1
    assert any("mapped to To" in warning for warning in report.warnings)
