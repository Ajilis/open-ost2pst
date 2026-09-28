"""PST verification and source/destination comparison."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from open_ost2pst.model import Attachment, Folder, Mailbox, Message
from open_ost2pst.reader.pff_reader import ExtractionReport, load_mailbox


MAX_REPORTED_MISMATCHES = 1000


@dataclass(frozen=True, slots=True)
class AttachmentFingerprint:
    index: int
    filename: str | None
    mime_type: str | None
    content_id: str | None
    content_location: str | None
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class MessageFingerprint:
    index: int
    subject: str
    message_class: str | None
    internet_message_id: str | None
    transport_headers_sha256: str | None
    conversation_topic: str | None
    conversation_index_sha256: str | None
    importance: int | None
    sensitivity: int | None
    delivery_time: str | None
    creation_time: str | None
    is_read: bool | None
    rtf_size: int | None
    rtf_sha256: str | None
    attachments: tuple[AttachmentFingerprint, ...]

    @property
    def attachment_count(self) -> int:
        return len(self.attachments)


@dataclass(frozen=True, slots=True)
class FolderFingerprint:
    path: str
    message_count: int
    messages: tuple[MessageFingerprint, ...]


@dataclass(frozen=True, slots=True)
class StoreManifest:
    path: str
    folder_count: int
    message_count: int
    attachment_count: int
    folders: tuple[FolderFingerprint, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VerificationMismatch:
    kind: str
    path: str
    field: str
    source: Any
    destination: Any


@dataclass(frozen=True, slots=True)
class VerificationReport:
    destination: str
    source: str | None
    ok: bool
    destination_extraction: ExtractionReport
    source_extraction: ExtractionReport | None
    destination_manifest: StoreManifest
    source_manifest: StoreManifest | None
    mismatches: tuple[VerificationMismatch, ...]
    mismatch_count: int
    mismatches_truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "source": self.source,
            "ok": self.ok,
            "destination_extraction": self.destination_extraction.to_dict(),
            "source_extraction": (
                self.source_extraction.to_dict()
                if self.source_extraction is not None
                else None
            ),
            "destination_manifest": self.destination_manifest.to_dict(),
            "source_manifest": (
                self.source_manifest.to_dict()
                if self.source_manifest is not None
                else None
            ),
            "mismatches": [
                asdict(mismatch) for mismatch in self.mismatches
            ],
            "mismatch_count": self.mismatch_count,
            "mismatches_truncated": self.mismatches_truncated,
        }


def build_manifest(
    mailbox: Mailbox,
    *,
    path: str | Path = "",
) -> StoreManifest:
    """Build a deterministic manifest with SHA-256 attachment hashes."""

    folders: list[FolderFingerprint] = []
    _append_folder_manifest(
        mailbox.root,
        parent_components=(),
        folders=folders,
    )

    return StoreManifest(
        path=str(path),
        folder_count=mailbox.folder_count,
        message_count=mailbox.message_count,
        attachment_count=mailbox.attachment_count,
        folders=tuple(folders),
    )


def compare_manifests(
    source: StoreManifest,
    destination: StoreManifest,
) -> tuple[tuple[VerificationMismatch, ...], int, bool]:
    """Compare manifests while preserving folder/message/attachment order."""

    reported: list[VerificationMismatch] = []
    mismatch_count = 0

    def add(
        kind: str,
        path: str,
        field: str,
        expected: Any,
        actual: Any,
    ) -> None:
        nonlocal mismatch_count
        mismatch_count += 1
        if len(reported) < MAX_REPORTED_MISMATCHES:
            reported.append(
                VerificationMismatch(
                    kind=kind,
                    path=path,
                    field=field,
                    source=expected,
                    destination=actual,
                )
            )

    for field in ("folder_count", "message_count", "attachment_count"):
        expected = getattr(source, field)
        actual = getattr(destination, field)
        if expected != actual:
            add("count", "/", field, expected, actual)

    max_folders = max(len(source.folders), len(destination.folders))
    for folder_index in range(max_folders):
        if folder_index >= len(source.folders):
            extra = destination.folders[folder_index]
            add("folder", extra.path, "presence", None, "extra")
            continue
        if folder_index >= len(destination.folders):
            missing = source.folders[folder_index]
            add("folder", missing.path, "presence", "present", None)
            continue

        expected_folder = source.folders[folder_index]
        actual_folder = destination.folders[folder_index]

        if expected_folder.path != actual_folder.path:
            add(
                "folder",
                expected_folder.path,
                "path",
                expected_folder.path,
                actual_folder.path,
            )

        if expected_folder.message_count != actual_folder.message_count:
            add(
                "folder",
                expected_folder.path,
                "message_count",
                expected_folder.message_count,
                actual_folder.message_count,
            )

        _compare_messages(
            expected_folder,
            actual_folder,
            add,
        )

    return (
        tuple(reported),
        mismatch_count,
        mismatch_count > len(reported),
    )


def verify_against_mailbox(
    destination: str | Path,
    source_mailbox: Mailbox,
    *,
    source_label: str = "<mailbox>",
) -> VerificationReport:
    """Verify a PST against an already-extracted source mailbox."""

    destination_path = Path(destination)
    destination_mailbox, destination_extraction = load_mailbox(destination_path)

    source_manifest = build_manifest(
        source_mailbox,
        path=source_label,
    )
    destination_manifest = build_manifest(
        destination_mailbox,
        path=destination_path,
    )
    (
        mismatches,
        mismatch_count,
        mismatches_truncated,
    ) = compare_manifests(source_manifest, destination_manifest)

    return VerificationReport(
        destination=str(destination_path),
        source=source_label,
        ok=(
            not _has_extraction_failures(destination_extraction)
            and mismatch_count == 0
        ),
        destination_extraction=destination_extraction,
        source_extraction=None,
        destination_manifest=destination_manifest,
        source_manifest=source_manifest,
        mismatches=mismatches,
        mismatch_count=mismatch_count,
        mismatches_truncated=mismatches_truncated,
    )


def verify_store(
    destination: str | Path,
    *,
    source: str | Path | None = None,
) -> VerificationReport:
    """Open a PST through libpff and optionally compare it with its source."""

    destination_path = Path(destination)
    destination_mailbox, destination_extraction = load_mailbox(destination_path)
    destination_manifest = build_manifest(
        destination_mailbox,
        path=destination_path,
    )

    source_extraction: ExtractionReport | None = None
    source_manifest: StoreManifest | None = None
    mismatches: tuple[VerificationMismatch, ...] = ()
    mismatch_count = 0
    mismatches_truncated = False

    if source is not None:
        source_path = Path(source)
        source_mailbox, source_extraction = load_mailbox(source_path)
        source_manifest = build_manifest(
            source_mailbox,
            path=source_path,
        )
        (
            mismatches,
            mismatch_count,
            mismatches_truncated,
        ) = compare_manifests(
            source_manifest,
            destination_manifest,
        )

    destination_clean = not _has_extraction_failures(destination_extraction)
    source_clean = (
        source_extraction is None
        or not _has_extraction_failures(source_extraction)
    )

    return VerificationReport(
        destination=str(destination_path),
        source=str(source) if source is not None else None,
        ok=destination_clean and source_clean and mismatch_count == 0,
        destination_extraction=destination_extraction,
        source_extraction=source_extraction,
        destination_manifest=destination_manifest,
        source_manifest=source_manifest,
        mismatches=mismatches,
        mismatch_count=mismatch_count,
        mismatches_truncated=mismatches_truncated,
    )


def _append_folder_manifest(
    folder: Folder,
    *,
    parent_components: tuple[str, ...],
    folders: list[FolderFingerprint],
) -> None:
    components = parent_components + (_escape_path_component(folder.name),)
    path = "/" + "/".join(components)

    messages = tuple(
        _message_fingerprint(index, message)
        for index, message in enumerate(folder.messages)
    )
    folders.append(
        FolderFingerprint(
            path=path,
            message_count=len(messages),
            messages=messages,
        )
    )

    for child in folder.folders:
        _append_folder_manifest(
            child,
            parent_components=components,
            folders=folders,
        )


def _message_fingerprint(
    index: int,
    message: Message,
) -> MessageFingerprint:
    return MessageFingerprint(
        index=index,
        subject=message.subject or "",
        message_class=message.message_class,
        internet_message_id=message.internet_message_id,
        transport_headers_sha256=(
            hashlib.sha256(
                message.transport_headers.encode("utf-8")
            ).hexdigest()
            if message.transport_headers is not None
            else None
        ),
        conversation_topic=message.conversation_topic,
        conversation_index_sha256=(
            hashlib.sha256(message.conversation_index).hexdigest()
            if message.conversation_index is not None
            else None
        ),
        importance=message.importance,
        sensitivity=message.sensitivity,
        delivery_time=_normalize_datetime(message.delivery_time),
        creation_time=_normalize_datetime(message.creation_time),
        is_read=message.is_read,
        rtf_size=(
            len(message.body_rtf)
            if message.body_rtf is not None
            else None
        ),
        rtf_sha256=(
            hashlib.sha256(message.body_rtf).hexdigest()
            if message.body_rtf is not None
            else None
        ),
        attachments=tuple(
            _attachment_fingerprint(attachment_index, attachment)
            for attachment_index, attachment in enumerate(message.attachments)
        ),
    )


def _attachment_fingerprint(
    index: int,
    attachment: Attachment,
) -> AttachmentFingerprint:
    data = bytes(attachment.data)
    return AttachmentFingerprint(
        index=index,
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        content_id=attachment.content_id,
        content_location=attachment.content_location,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _compare_messages(
    source: FolderFingerprint,
    destination: FolderFingerprint,
    add: Any,
) -> None:
    max_messages = max(len(source.messages), len(destination.messages))

    for message_index in range(max_messages):
        path = f"{source.path}/message[{message_index}]"

        if message_index >= len(source.messages):
            add("message", path, "presence", None, "extra")
            continue
        if message_index >= len(destination.messages):
            add("message", path, "presence", "present", None)
            continue

        expected = source.messages[message_index]
        actual = destination.messages[message_index]

        if expected.subject != actual.subject:
            add("message", path, "subject", expected.subject, actual.subject)

        for field in (
            "message_class",
            "internet_message_id",
            "transport_headers_sha256",
            "conversation_topic",
            "conversation_index_sha256",
            "importance",
            "sensitivity",
            "delivery_time",
            "creation_time",
            "is_read",
        ):
            expected_value = getattr(expected, field)
            actual_value = getattr(actual, field)

            # Missing source metadata means libpff could not provide a value,
            # so it is not meaningful to require a destination match.
            if expected_value is None:
                continue
            if expected_value is None:
                continue
            if expected_value != actual_value:
                add(
                    "message",
                    path,
                    field,
                    expected_value,
                    actual_value,
                )

        for field in ("rtf_size", "rtf_sha256"):
            expected_value = getattr(expected, field)
            actual_value = getattr(actual, field)
            if expected_value is None:
                continue
            if expected_value != actual_value:
                add(
                    "message",
                    path,
                    field,
                    expected_value,
                    actual_value,
                )

        if expected.attachment_count != actual.attachment_count:
            add(
                "message",
                path,
                "attachment_count",
                expected.attachment_count,
                actual.attachment_count,
            )

        _compare_attachments(
            expected,
            actual,
            path,
            add,
        )


def _compare_attachments(
    source: MessageFingerprint,
    destination: MessageFingerprint,
    message_path: str,
    add: Any,
) -> None:
    max_attachments = max(
        len(source.attachments),
        len(destination.attachments),
    )

    for attachment_index in range(max_attachments):
        path = f"{message_path}/attachment[{attachment_index}]"

        if attachment_index >= len(source.attachments):
            add("attachment", path, "presence", None, "extra")
            continue
        if attachment_index >= len(destination.attachments):
            add("attachment", path, "presence", "present", None)
            continue

        expected = source.attachments[attachment_index]
        actual = destination.attachments[attachment_index]

        if (
            expected.filename is not None
            and expected.filename != actual.filename
        ):
            add(
                "attachment",
                path,
                "filename",
                expected.filename,
                actual.filename,
            )

        for field in (
            "mime_type",
            "content_id",
            "content_location",
            "size",
            "sha256",
        ):
            expected_value = getattr(expected, field)
            actual_value = getattr(actual, field)
            if expected_value != actual_value:
                add(
                    "attachment",
                    path,
                    field,
                    expected_value,
                    actual_value,
                )


def _normalize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _has_extraction_failures(report: ExtractionReport) -> bool:
    return any(
        (
            report.folders_failed,
            report.messages_failed,
            report.attachments_failed,
        )
    )


def _escape_path_component(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
