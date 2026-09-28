"""Format-neutral mailbox model used between readers and writers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator, Literal

RecipientType = Literal["to", "cc", "bcc", "unknown"]


@dataclass(slots=True)
class Attachment:
    filename: str | None = None
    data: bytes = b""
    mime_type: str | None = None
    content_id: str | None = None
    content_location: str | None = None
    embedded_message: "Message | None" = None


@dataclass(slots=True)
class Recipient:
    name: str | None = None
    email: str | None = None
    recipient_type: RecipientType = "unknown"


@dataclass(slots=True)
class StandardPropertyValue:
    property_id: int
    property_type: int
    value: Any


@dataclass(slots=True)
class NamedPropertyValue:
    guid: str | None
    name: str | int
    property_type: int
    value: Any


@dataclass(slots=True)
class Message:
    subject: str | None = None
    sender_name: str | None = None
    sender_email: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    body_rtf: bytes | None = None
    message_class: str | None = None
    internet_message_id: str | None = None
    transport_headers: str | None = None
    conversation_topic: str | None = None
    conversation_index: bytes | None = None
    importance: int | None = None
    sensitivity: int | None = None
    delivery_time: datetime | None = None
    creation_time: datetime | None = None
    is_read: bool | None = None
    recipients: list[Recipient] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    standard_properties: list[StandardPropertyValue] = field(
        default_factory=list
    )
    named_properties: list[NamedPropertyValue] = field(default_factory=list)


@dataclass(slots=True)
class Folder:
    name: str
    container_class: str | None = None
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
