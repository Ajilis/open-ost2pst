from datetime import datetime, timezone

from open_ost2pst.model import (
    Attachment,
    Folder,
    Mailbox,
    Message,
    NamedPropertyValue,
)
from open_ost2pst.verification import build_manifest, compare_manifests


def _mailbox(*, subject: str = "Hello", attachment: bytes = b"abc") -> Mailbox:
    return Mailbox(
        Folder(
            "Root",
            folders=[
                Folder(
                    "Inbox",
                    messages=[
                        Message(
                            subject=subject,
                            delivery_time=datetime(
                                2026, 1, 2, 3, 4, 5,
                                tzinfo=timezone.utc,
                            ),
                            creation_time=datetime(
                                2026, 1, 1, 3, 4, 5,
                                tzinfo=timezone.utc,
                            ),
                            is_read=False,
                            body_rtf=b"{\\rtf1\\ansi Hello}",
                            attachments=[
                                Attachment(
                                    filename="data.bin",
                                    data=attachment,
                                )
                            ],
                        )
                    ],
                )
            ],
        )
    )


def test_manifest_contains_paths_dates_sizes_and_sha256() -> None:
    manifest = build_manifest(_mailbox(), path="source.ost")

    assert manifest.folder_count == 2
    assert manifest.message_count == 1
    assert manifest.attachment_count == 1
    assert [folder.path for folder in manifest.folders] == [
        "/Root",
        "/Root/Inbox",
    ]

    message = manifest.folders[1].messages[0]
    assert message.subject == "Hello"
    assert message.delivery_time == "2026-01-02T03:04:05.000000Z"
    assert message.creation_time == "2026-01-01T03:04:05.000000Z"
    assert message.is_read is False
    assert message.rtf_size == len(b"{\\rtf1\\ansi Hello}")
    assert len(message.rtf_sha256) == 64

    attachment = message.attachments[0]
    assert attachment.filename == "data.bin"
    assert attachment.size == 3
    assert (
        attachment.sha256
        == "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )


def test_identical_manifests_have_no_mismatches() -> None:
    source = build_manifest(_mailbox(), path="source.ost")
    destination = build_manifest(_mailbox(), path="output.pst")

    mismatches, count, truncated = compare_manifests(source, destination)

    assert mismatches == ()
    assert count == 0
    assert truncated is False


def test_comparison_detects_subject_and_attachment_hash_changes() -> None:
    source = build_manifest(
        _mailbox(subject="Source", attachment=b"abc"),
        path="source.ost",
    )
    destination = build_manifest(
        _mailbox(subject="Destination", attachment=b"abd"),
        path="output.pst",
    )

    mismatches, count, truncated = compare_manifests(source, destination)

    fields = {(item.kind, item.field) for item in mismatches}
    assert ("message", "subject") in fields
    assert ("attachment", "sha256") in fields
    assert count == 2
    assert truncated is False


def test_missing_source_metadata_is_not_required_to_match() -> None:
    source = Mailbox(
        Folder(
            "Root",
            messages=[
                Message(
                    subject="Hello",
                    delivery_time=None,
                    creation_time=None,
                    is_read=None,
                )
            ],
        )
    )
    destination = Mailbox(
        Folder(
            "Root",
            messages=[
                Message(
                    subject="Hello",
                    delivery_time=datetime(
                        2026, 1, 1, tzinfo=timezone.utc
                    ),
                    creation_time=datetime(
                        2026, 1, 1, tzinfo=timezone.utc
                    ),
                    is_read=True,
                )
            ],
        )
    )

    mismatches, count, _ = compare_manifests(
        build_manifest(source),
        build_manifest(destination),
    )

    assert mismatches == ()
    assert count == 0


def test_manifest_escapes_folder_path_components() -> None:
    mailbox = Mailbox(
        Folder("Root/A", folders=[Folder("B~C")])
    )

    manifest = build_manifest(mailbox)

    assert [folder.path for folder in manifest.folders] == [
        "/Root~1A",
        "/Root~1A/B~0C",
    ]


def test_comparison_detects_rtf_hash_change() -> None:
    source = _mailbox()
    destination = _mailbox()
    source.root.folders[0].messages[0].body_rtf = b"{\\rtf1\\ansi Source}"
    destination.root.folders[0].messages[0].body_rtf = b"{\\rtf1\\ansi Destination}"

    mismatches, count, truncated = compare_manifests(
        build_manifest(source),
        build_manifest(destination),
    )

    assert any(
        item.kind == "message" and item.field == "rtf_sha256"
        for item in mismatches
    )
    assert count == 2
    assert truncated is False



def test_manifest_contains_advanced_message_and_attachment_metadata() -> None:
    mailbox = _mailbox()
    message = mailbox.root.folders[0].messages[0]
    message.message_class = "IPM.Note.Custom"
    message.internet_message_id = "<message@example.com>"
    message.transport_headers = "Message-ID: <message@example.com>\r\n"
    message.conversation_topic = "Conversation"
    message.conversation_index = b"conversation-index"
    message.importance = 2
    message.sensitivity = 2

    attachment = message.attachments[0]
    attachment.mime_type = "application/octet-stream"
    attachment.content_id = "part@example.com"
    attachment.content_location = "parts/data.bin"

    manifest = build_manifest(mailbox)
    fingerprint = manifest.folders[1].messages[0]

    assert fingerprint.message_class == "IPM.Note.Custom"
    assert fingerprint.internet_message_id == "<message@example.com>"
    assert len(fingerprint.transport_headers_sha256) == 64
    assert fingerprint.conversation_topic == "Conversation"
    assert len(fingerprint.conversation_index_sha256) == 64
    assert fingerprint.importance == 2
    assert fingerprint.sensitivity == 2

    attachment_fingerprint = fingerprint.attachments[0]
    assert attachment_fingerprint.mime_type == "application/octet-stream"
    assert attachment_fingerprint.content_id == "part@example.com"
    assert attachment_fingerprint.content_location == "parts/data.bin"


def test_comparison_detects_advanced_metadata_changes() -> None:
    source = _mailbox()
    destination = _mailbox()

    source_message = source.root.folders[0].messages[0]
    destination_message = destination.root.folders[0].messages[0]

    source_message.internet_message_id = "<source@example.com>"
    destination_message.internet_message_id = "<destination@example.com>"
    source_message.importance = 2
    destination_message.importance = 0

    source_attachment = source_message.attachments[0]
    destination_attachment = destination_message.attachments[0]
    source_attachment.content_id = "source-part@example.com"
    destination_attachment.content_id = "destination-part@example.com"

    mismatches, count, truncated = compare_manifests(
        build_manifest(source),
        build_manifest(destination),
    )

    fields = {(item.kind, item.field) for item in mismatches}
    assert ("message", "internet_message_id") in fields
    assert ("message", "importance") in fields
    assert ("attachment", "content_id") in fields
    assert count == 3
    assert truncated is False


def test_missing_optional_advanced_metadata_is_not_required_to_match() -> None:
    source = _mailbox()
    destination = _mailbox()

    destination_message = destination.root.folders[0].messages[0]
    destination_message.message_class = "IPM.Note"
    destination_message.internet_message_id = "<generated@example.com>"
    destination_message.conversation_topic = "Generated"
    destination_message.importance = 1
    destination_message.sensitivity = 0

    destination_attachment = destination_message.attachments[0]
    destination_attachment.mime_type = "application/octet-stream"
    destination_attachment.content_id = "generated@example.com"
    destination_attachment.content_location = "generated/data.bin"

    mismatches, count, truncated = compare_manifests(
        build_manifest(source),
        build_manifest(destination),
    )

    assert mismatches == ()
    assert count == 0
    assert truncated is False



def test_named_property_manifest_and_comparison() -> None:
    source = _mailbox()
    destination = _mailbox()

    source_message = source.root.folders[0].messages[0]
    destination_message = destination.root.folders[0].messages[0]

    named = NamedPropertyValue(
        guid="00062002-0000-0000-c000-000000000046",
        name=0x8208,
        property_type=0x001F,
        value="Room 42",
    )
    source_message.named_properties.append(named)
    destination_message.named_properties.append(
        NamedPropertyValue(
            guid=named.guid,
            name=named.name,
            property_type=named.property_type,
            value="Room 42",
        )
    )

    source_manifest = build_manifest(source)
    destination_manifest = build_manifest(destination)
    fingerprint = source_manifest.folders[1].messages[0].named_properties[0]

    assert fingerprint.name == 0x8208
    assert fingerprint.value_fingerprint == "str:Room 42"

    mismatches, count, truncated = compare_manifests(
        source_manifest,
        destination_manifest,
    )
    assert mismatches == ()
    assert count == 0
    assert truncated is False


def test_named_property_value_change_is_detected() -> None:
    source = _mailbox()
    destination = _mailbox()

    for mailbox, value in (
        (source, "Room 42"),
        (destination, "Room 43"),
    ):
        mailbox.root.folders[0].messages[0].named_properties.append(
            NamedPropertyValue(
                guid="00062002-0000-0000-c000-000000000046",
                name=0x8208,
                property_type=0x001F,
                value=value,
            )
        )

    mismatches, count, truncated = compare_manifests(
        build_manifest(source),
        build_manifest(destination),
    )

    assert any(
        item.kind == "named_property"
        and item.field == "value"
        for item in mismatches
    )
    assert count == 1
    assert truncated is False


def test_folder_comparison_is_path_based_and_ignores_synthetic_deleted_items() -> None:
    source = Mailbox(
        Folder(
            "Top of Personal Folders",
            folders=[
                Folder(
                    "Root - Public",
                    messages=[Message(subject="Public")],
                ),
                Folder(
                    "Root - Mailbox",
                    folders=[
                        Folder(
                            "IPM_SUBTREE",
                            messages=[Message(subject="Inbox item")],
                        )
                    ],
                ),
            ],
        )
    )
    destination = Mailbox(
        Folder(
            "Top of Personal Folders",
            folders=[
                Folder("Deleted Items"),
                Folder(
                    "Root - Public",
                    messages=[Message(subject="Public")],
                ),
                Folder(
                    "Root - Mailbox",
                    folders=[
                        Folder(
                            "IPM_SUBTREE",
                            messages=[Message(subject="Inbox item")],
                        )
                    ],
                ),
            ],
        )
    )

    mismatches, count, truncated = compare_manifests(
        build_manifest(source),
        build_manifest(destination),
    )

    assert mismatches == ()
    assert count == 0
    assert truncated is False


def test_extra_non_synthetic_folder_is_still_reported() -> None:
    source = Mailbox(Folder("Root"))
    destination = Mailbox(
        Folder("Root", folders=[Folder("Unexpected")])
    )

    mismatches, count, truncated = compare_manifests(
        build_manifest(source),
        build_manifest(destination),
    )

    assert any(
        item.kind == "folder"
        and item.field == "presence"
        and item.path == "/Root/Unexpected"
        for item in mismatches
    )
    assert count == 2
    assert truncated is False


def test_message_comparison_uses_internet_message_id_before_position() -> None:
    first = Message(
        subject="First",
        internet_message_id="<first@example.com>",
        importance=1,
    )
    second = Message(
        subject="Second",
        internet_message_id="<second@example.com>",
        importance=2,
    )
    source = Mailbox(Folder("Root", messages=[first, second]))
    destination = Mailbox(
        Folder(
            "Root",
            messages=[
                Message(
                    subject="Second",
                    internet_message_id="<second@example.com>",
                    importance=2,
                ),
                Message(
                    subject="First",
                    internet_message_id="<first@example.com>",
                    importance=1,
                ),
            ],
        )
    )

    mismatches, count, truncated = compare_manifests(
        build_manifest(source),
        build_manifest(destination),
    )

    assert mismatches == ()
    assert count == 0
    assert truncated is False


def test_missing_message_is_reported_without_order_cascade() -> None:
    source = Mailbox(
        Folder(
            "Root",
            messages=[
                Message(subject="One", internet_message_id="<1@example.com>"),
                Message(subject="Two", internet_message_id="<2@example.com>"),
                Message(subject="Three", internet_message_id="<3@example.com>"),
            ],
        )
    )
    destination = Mailbox(
        Folder(
            "Root",
            messages=[
                Message(subject="One", internet_message_id="<1@example.com>"),
                Message(subject="Three", internet_message_id="<3@example.com>"),
            ],
        )
    )

    mismatches, count, truncated = compare_manifests(
        build_manifest(source),
        build_manifest(destination),
    )

    presence = [
        item for item in mismatches
        if item.kind == "message" and item.field == "presence"
    ]
    assert len(presence) == 1
    assert "<2@example.com>" in presence[0].path
    assert count == 2
    assert truncated is False
