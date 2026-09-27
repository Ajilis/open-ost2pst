from datetime import datetime, timezone

from open_ost2pst.model import Attachment, Folder, Mailbox, Message
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
