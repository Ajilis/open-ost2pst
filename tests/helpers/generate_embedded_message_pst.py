"""Generate a PST containing one embedded-message attachment."""

from __future__ import annotations

import argparse
from pathlib import Path

from open_ost2pst.pst.messaging import MessagingBuilder, MessagingMessage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

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

    args.output.write_bytes(builder.build().data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
