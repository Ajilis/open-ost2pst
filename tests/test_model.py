from open_ost2pst.model import Attachment, Folder, Mailbox, Message


def test_mailbox_counts_nested_items() -> None:
    root = Folder(
        "root",
        messages=[Message(subject="root")],
        folders=[
            Folder(
                "Inbox",
                messages=[
                    Message(
                        subject="hello",
                        attachments=[Attachment(filename="one.txt", data=b"1")],
                    ),
                    Message(
                        subject="world",
                        attachments=[
                            Attachment(filename="two.txt", data=b"2"),
                            Attachment(filename="three.txt", data=b"3"),
                        ],
                    ),
                ],
            )
        ],
    )

    mailbox = Mailbox(root)

    assert mailbox.folder_count == 2
    assert mailbox.message_count == 3
    assert mailbox.attachment_count == 3
