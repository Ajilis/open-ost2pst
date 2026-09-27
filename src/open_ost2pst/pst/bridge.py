"""Bridge from the format-neutral Mailbox model to PST Messaging."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from open_ost2pst.model import Folder, Mailbox, Message, Recipient

from .messaging import (
    RECIPIENT_TYPE_BCC,
    RECIPIENT_TYPE_CC,
    RECIPIENT_TYPE_TO,
    MessagingBuilder,
    MessagingFolder,
)


FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


@dataclass(slots=True)
class WriteReport:
    folders_read: int = 0
    folders_written: int = 0
    messages_read: int = 0
    messages_written: int = 0
    recipients_read: int = 0
    recipients_written: int = 0
    attachments_read: int = 0
    attachments_written: int = 0
    attachments_failed: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if len(self.warnings) < 100:
            self.warnings.append(message)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def mailbox_to_messaging(
    mailbox: Mailbox,
    *,
    store_name: str = "Open OST2PST Store",
) -> tuple[MessagingBuilder, WriteReport]:
    """Translate a format-neutral mailbox into Messaging objects."""

    report = WriteReport(
        folders_read=mailbox.folder_count,
        messages_read=mailbox.message_count,
        attachments_read=mailbox.attachment_count,
        recipients_read=sum(
            len(message.recipients)
            for folder in mailbox.root.walk()
            for message in folder.messages
        ),
    )

    builder = MessagingBuilder(
        store_name=store_name,
        root_name=mailbox.root.name,
    )

    _copy_folder_contents(
        mailbox.root,
        builder.root,
        builder,
        report,
    )

    return builder, report


def datetime_to_filetime(value: datetime | None) -> int | None:
    if value is None:
        return None

    if value.tzinfo is None:
        utc_value = value.replace(tzinfo=timezone.utc)
    else:
        utc_value = value.astimezone(timezone.utc)

    delta = utc_value - FILETIME_EPOCH
    if delta.total_seconds() < 0:
        raise ValueError("datetime predates the Windows FILETIME epoch")

    return (
        delta.days * 86400 * 10_000_000
        + delta.seconds * 10_000_000
        + delta.microseconds * 10
    )


def _copy_folder_contents(
    source: Folder,
    destination: MessagingFolder,
    builder: MessagingBuilder,
    report: WriteReport,
) -> None:
    report.folders_written += 1

    for message in source.messages:
        _copy_message(message, destination, builder, report)

    for child in source.folders:
        child_destination = builder.add_folder(
            destination,
            child.name,
        )
        _copy_folder_contents(
            child,
            child_destination,
            builder,
            report,
        )


def _copy_message(
    source: Message,
    folder: MessagingFolder,
    builder: MessagingBuilder,
    report: WriteReport,
) -> None:
    to_values = [
        _recipient_label(recipient)
        for recipient in source.recipients
        if recipient.recipient_type == "to"
    ]
    cc_values = [
        _recipient_label(recipient)
        for recipient in source.recipients
        if recipient.recipient_type == "cc"
    ]

    try:
        delivery = datetime_to_filetime(source.delivery_time)
    except ValueError as exc:
        delivery = None
        report.warn(f"delivery time skipped for {source.subject!r}: {exc}")

    try:
        created = datetime_to_filetime(source.creation_time)
    except ValueError as exc:
        created = None
        report.warn(f"creation time skipped for {source.subject!r}: {exc}")

    target = builder.add_message(
        folder,
        subject=source.subject or "",
        body=source.body_text or "",
        sender_name=source.sender_name or "",
        sender_email=source.sender_email or "",
        display_to="; ".join(value for value in to_values if value),
        display_cc="; ".join(value for value in cc_values if value),
        html_body=(
            source.body_html.encode("utf-8")
            if source.body_html is not None
            else None
        ),
        rtf_body=source.body_rtf,
        delivery_filetime=delivery,
        creation_filetime=created,
        is_read=True if source.is_read is None else source.is_read,
    )

    for recipient in source.recipients:
        recipient_type = _recipient_type(recipient, report)
        builder.add_recipient(
            target,
            name=recipient.name or "",
            email=recipient.email or "",
            recipient_type=recipient_type,
        )
        report.recipients_written += 1

    for attachment in source.attachments:
        builder.add_attachment(
            target,
            filename=attachment.filename or "attachment.bin",
            data=attachment.data,
            mime_type=attachment.mime_type,
        )
        report.attachments_written += 1

    report.messages_written += 1


def _recipient_label(recipient: Recipient) -> str:
    return recipient.name or recipient.email or ""


def _recipient_type(
    recipient: Recipient,
    report: WriteReport,
) -> int:
    mapping = {
        "to": RECIPIENT_TYPE_TO,
        "cc": RECIPIENT_TYPE_CC,
        "bcc": RECIPIENT_TYPE_BCC,
    }
    result = mapping.get(recipient.recipient_type)
    if result is not None:
        return result

    report.warn(
        f"recipient type {recipient.recipient_type!r} mapped to To "
        f"for {recipient.email or recipient.name or 'unnamed recipient'}"
    )
    return RECIPIENT_TYPE_TO
