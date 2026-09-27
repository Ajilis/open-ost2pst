"""Format-neutral mailbox model used between readers and writers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Literal

RecipientType = Literal["to", "cc", "bcc", "unknown"]


@dataclass(slots=True)
class Attachment:
    filename: str | None = None
    data: bytes = b""
    mime_type: str | None = None


@dataclass(slots=True)
class Recipient:
    name: str | None = None
    email: str | None = None
    recipient_type: RecipientType = "unknown"


@dataclass(slots=True)
class Message:
    subject: str | None = None
    sender_name: str | None = None
    sender_email: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    body_rtf: bytes | None = None
    delivery_time: datetime | None = None
    creation_time: datetime | None = None
    is_read: bool | None = None
    recipients: list[Recipient] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)


@dataclass(slots=True)
class Folder:
    name: str
    messages: list[Message] = field(default_factory=list)
    folders: list["Folder"] = field(default_factory=list)

    def walk(self) -> Iterator["Folder"]:
        yield self
        for child in self.folders:
            yield from child.walk()


@dataclass(slots=True)
class Mailbox:
    root: Folder

    @property
    def folder_count(self) -> int:
        return sum(1 for _ in self.root.walk())

    @property
    def message_count(self) -> int:
        return sum(len(folder.messages) for folder in self.root.walk())

    @property
    def attachment_count(self) -> int:
        return sum(
            len(message.attachments)
            for folder in self.root.walk()
            for message in folder.messages
        )
