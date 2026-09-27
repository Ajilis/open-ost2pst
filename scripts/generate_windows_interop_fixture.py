"""Generate a deterministic PST fixture for Windows interoperability tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from open_ost2pst.pst.messaging import (
    RECIPIENT_TYPE_CC,
    RECIPIENT_TYPE_TO,
    MessagingBuilder,
)


ROOT_NAME = "Open OST2PST Interop"
UNICODE_SUBJECT = "Unicode ✓ – 日本語 – العربية"
SIBLOCK_SUBJECT = "SIBLOCK 341 attachments"
NESTED_SUBJECT = "Nested folder message"


def build_fixture(output: Path, manifest_path: Path) -> None:
    builder = MessagingBuilder(
        store_name="Open OST2PST Windows Interop",
        root_name=ROOT_NAME,
    )

    inbox = builder.add_folder(builder.root, "Inbox")
    archive = builder.add_folder(inbox, "Archive")

    unicode_message = builder.add_message(
        inbox,
        subject=UNICODE_SUBJECT,
        body=(
            "Unicode body: café, naïve, Ελληνικά, 日本語, العربية. "
            + ("large-body-" * 2500)
        ),
        sender_name="Alice Example",
        sender_email="alice@example.com",
        display_to="Bob Example",
        display_cc="Carol Example",
        is_read=False,
    )
    builder.add_recipient(
        unicode_message,
        name="Bob Example",
        email="bob@example.com",
        recipient_type=RECIPIENT_TYPE_TO,
    )
    builder.add_recipient(
        unicode_message,
        name="Carol Example",
        email="carol@example.com",
        recipient_type=RECIPIENT_TYPE_CC,
    )
    large_attachment = bytes(
        (index * 17 + 3) & 0xFF for index in range(150_000)
    )
    builder.add_attachment(
        unicode_message,
        filename="large-unicode-✓.bin",
        data=large_attachment,
        mime_type="application/octet-stream",
    )

    siblock_message = builder.add_message(
        inbox,
        subject=SIBLOCK_SUBJECT,
        body="Forces more than one SLBLOCK in the message subnode tree.",
    )
    for index in range(341):
        builder.add_attachment(
            siblock_message,
            filename=f"part-{index:03d}.bin",
            data=bytes([index & 0xFF]),
            mime_type="application/octet-stream",
        )

    builder.add_message(
        archive,
        subject=NESTED_SUBJECT,
        body="Nested folder traversal test.",
        is_read=True,
    )

    result = builder.build()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.data)

    manifest = {
        "root_name": ROOT_NAME,
        "folder_count": 3,
        "message_count": 3,
        "attachment_count": 342,
        "subjects": [
            UNICODE_SUBJECT,
            SIBLOCK_SUBJECT,
            NESTED_SUBJECT,
        ],
        "required_folders": [
            "Inbox",
            "Archive",
        ],
        "large_attachment": {
            "filename": "large-unicode-✓.bin",
            "size": len(large_attachment),
        },
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    build_fixture(args.output, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
