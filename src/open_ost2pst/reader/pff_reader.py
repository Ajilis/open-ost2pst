"""Read-only OST/PST inspection and extraction through libpff."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import struct
from uuid import UUID
from email.utils import parseaddr
import mimetypes
from pathlib import Path
from typing import Any

from open_ost2pst.model import (
    Attachment,
    Folder,
    Mailbox,
    Message,
    NamedPropertyValue,
    Recipient,
)

# Common MAPI property IDs used by Outlook message/recipient/attachment rows.
PR_IMPORTANCE = 0x0017
PR_MESSAGE_CLASS = 0x001A
PR_SENSITIVITY = 0x0036
PR_CONVERSATION_TOPIC = 0x0070
PR_CONVERSATION_INDEX = 0x0071
PR_TRANSPORT_MESSAGE_HEADERS = 0x007D
PR_INTERNET_MESSAGE_ID = 0x1035
PR_DISPLAY_NAME = 0x3001
PR_EMAIL_ADDRESS = 0x3003
PR_RECIPIENT_TYPE = 0x0C15
PR_SENDER_EMAIL_ADDRESS = 0x0C1F
PR_MESSAGE_FLAGS = 0x0E07
PR_ATTACH_FILENAME = 0x3704
PR_ATTACH_LONG_FILENAME = 0x3707
PR_ATTACH_METHOD = 0x3705
PR_ATTACH_MIME_TAG = 0x370E
PR_ATTACH_CONTENT_ID = 0x3712
PR_ATTACH_CONTENT_LOCATION = 0x3713
PR_SMTP_ADDRESS = 0x39FE
PR_SENDER_SMTP_ADDRESS = 0x5D01

MESSAGE_FLAG_READ = 0x00000001
ATTACH_EMBEDDED_MESSAGE = 5
RECIPIENT_TYPES = {1: "to", 2: "cc", 3: "bcc"}

NID_ROOT_FOLDER = 0x0122
NID_IPM_SUBTREE = 0x8022

PR_NAMEID_STREAM_GUID = 0x0002
PR_NAMEID_STREAM_ENTRY = 0x0003
PR_NAMEID_STREAM_STRING = 0x0004
FIRST_NAMED_PROPERTY_ID = 0x8000
LAST_NAMED_PROPERTY_ID = 0x8FFF
PS_MAPI = UUID("00020328-0000-0000-c000-000000000046")
PS_PUBLIC_STRINGS = UUID("00020329-0000-0000-c000-000000000046")

PT_INTEGER16 = 0x0002
PT_INTEGER32 = 0x0003
PT_FLOAT32 = 0x0004
PT_FLOAT64 = 0x0005
PT_BOOLEAN = 0x000B
PT_INTEGER64 = 0x0014
PT_STRING8 = 0x001E
PT_UNICODE = 0x001F
PT_SYSTIME = 0x0040
PT_GUID = 0x0048
PT_BINARY = 0x0102


@dataclass(frozen=True, slots=True)
class _NameIdDefinition:
    guid: str | None
    name: str | int


class PffUnavailableError(RuntimeError):
    """Raised when the pypff bindings are not available."""


@dataclass(slots=True)
class InspectionStats:
    path: str
    folders: int = 0
    messages: int = 0
    attachments: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExtractionReport:
    """Best-effort extraction counters and non-fatal warnings."""

    path: str
    folders_seen: int = 0
    folders_loaded: int = 0
    folders_failed: int = 0
    messages_seen: int = 0
    messages_loaded: int = 0
    messages_failed: int = 0
    attachments_seen: int = 0
    attachments_loaded: int = 0
    attachments_failed: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        # Keep reports bounded for heavily damaged stores.
        if len(self.warnings) < 100:
            self.warnings.append(message)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_pypff() -> Any:
    try:
        import pypff  # type: ignore
    except ImportError as exc:
        raise PffUnavailableError(
            "pypff is required for OST/PST inspection. "
            "Install libpff and its Python bindings, then retry."
        ) from exc
    return pypff


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, name, default)
        return value() if callable(value) else value
    except Exception:
        return default


def _int_attr(obj: Any, name: str) -> int:
    value = _safe_attr(obj, name, 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _record_set(obj: Any) -> Any | None:
    """Return a record set for a pypff item or an existing record set."""

    if obj is None:
        return None

    if hasattr(obj, "get_entry_by_type"):
        return obj

    try:
        return obj.get_record_set(0)
    except Exception:
        return None


def _entry(obj: Any, property_id: int) -> Any | None:
    record_set = _record_set(obj)
    if record_set is None:
        return None

    if hasattr(record_set, "get_entry_by_type"):
        try:
            return record_set.get_entry_by_type(property_id)
        except Exception:
            return None

    count = _int_attr(record_set, "number_of_entries")
    for index in range(count):
        try:
            entry = record_set.get_entry(index)
        except Exception:
            continue
        if _int_attr(entry, "entry_type") == property_id:
            return entry

    return None


def _property_string(obj: Any, property_id: int) -> str | None:
    entry = _entry(obj, property_id)
    if entry is None:
        return None

    value = _safe_attr(entry, "data_as_string")
    if value is None:
        try:
            value = entry.get_data_as_string()
        except Exception:
            return None

    return str(value) if value is not None else None


def _property_integer(obj: Any, property_id: int) -> int | None:
    entry = _entry(obj, property_id)
    if entry is None:
        return None

    value = _safe_attr(entry, "data_as_integer")
    if value is None:
        try:
            value = entry.get_data_as_integer()
        except Exception:
            return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _property_binary(obj: Any, property_id: int) -> bytes | None:
    entry = _entry(obj, property_id)
    if entry is None:
        return None

    value = _safe_attr(entry, "data")
    if value is None:
        try:
            value = entry.get_data()
        except Exception:
            return None

    if value is None:
        return None
    try:
        return bytes(value)
    except Exception:
        return None


def _iter_record_entries(obj: Any) -> list[Any]:
    record_set = _record_set(obj)
    if record_set is None:
        return []

    entries: list[Any] = []
    count = _int_attr(record_set, "number_of_entries")
    for index in range(count):
        try:
            entries.append(record_set.get_entry(index))
        except Exception:
            continue
    return entries


def _nameid_guid(
    guid_index: int,
    custom_guids: list[UUID],
) -> str | None:
    if guid_index == 0:
        return None
    if guid_index == 1:
        return str(PS_MAPI)
    if guid_index == 2:
        return str(PS_PUBLIC_STRINGS)

    custom_index = guid_index - 3
    if not 0 <= custom_index < len(custom_guids):
        raise ValueError(f"invalid NameID GUID index: {guid_index}")
    return str(custom_guids[custom_index])


def _nameid_string(stream: bytes, offset: int) -> str:
    if offset < 0 or offset + 4 > len(stream):
        raise ValueError("NameID string offset is out of bounds")
    size = struct.unpack_from("<I", stream, offset)[0]
    start = offset + 4
    end = start + size
    if end > len(stream):
        raise ValueError("NameID string data is truncated")
    return stream[start:end].decode("utf-16-le")


def _extract_nameid_definitions(
    store: Any,
    report: ExtractionReport,
) -> dict[int, _NameIdDefinition]:
    item = _safe_attr(store, "name_to_id_map")
    if item is None:
        try:
            item = store.get_name_to_id_map()
        except Exception:
            return {}
    if item is None:
        return {}

    guid_stream = _property_binary(item, PR_NAMEID_STREAM_GUID) or b""
    entry_stream = _property_binary(item, PR_NAMEID_STREAM_ENTRY) or b""
    string_stream = _property_binary(item, PR_NAMEID_STREAM_STRING) or b""

    if len(guid_stream) % 16:
        report.warn("Name-to-ID GUID stream has invalid length")
        return {}
    if len(entry_stream) % 8:
        report.warn("Name-to-ID Entry stream has invalid length")
        return {}

    custom_guids = [
        UUID(bytes_le=guid_stream[offset : offset + 16])
        for offset in range(0, len(guid_stream), 16)
    ]

    definitions: dict[int, _NameIdDefinition] = {}
    for offset in range(0, len(entry_stream), 8):
        property_id_or_offset, packed_guid, property_index = struct.unpack_from(
            "<IHH",
            entry_stream,
            offset,
        )
        property_id = FIRST_NAMED_PROPERTY_ID + property_index
        if property_id > LAST_NAMED_PROPERTY_ID:
            report.warn(
                f"Name-to-ID property index out of range: {property_index}"
            )
            continue

        guid_index = packed_guid >> 1
        is_string = bool(packed_guid & 1)

        try:
            guid = _nameid_guid(guid_index, custom_guids)
            name: str | int
            if is_string:
                name = _nameid_string(
                    string_stream,
                    property_id_or_offset,
                )
            else:
                name = property_id_or_offset
        except (UnicodeDecodeError, ValueError) as exc:
            report.warn(
                f"Name-to-ID entry {property_id:#06x} skipped: {exc}"
            )
            continue

        definitions[property_id] = _NameIdDefinition(
            guid=guid,
            name=name,
        )

    return definitions


def _entry_named_property_value(
    entry: Any,
    value_type: int,
) -> Any:
    if value_type in (PT_INTEGER16, PT_INTEGER32, PT_INTEGER64):
        value = _safe_attr(entry, "data_as_integer")
        return None if value is None else int(value)
    if value_type == PT_BOOLEAN:
        value = _safe_attr(entry, "data_as_boolean")
        if value is None:
            value = _safe_attr(entry, "data_as_integer")
        return None if value is None else bool(value)
    if value_type in (PT_FLOAT32, PT_FLOAT64):
        value = _safe_attr(entry, "data_as_floating_point")
        return None if value is None else float(value)
    if value_type in (PT_STRING8, PT_UNICODE):
        value = _safe_attr(entry, "data_as_string")
        return None if value is None else str(value)
    if value_type == PT_SYSTIME:
        value = _safe_attr(entry, "data_as_datetime")
        return value if isinstance(value, datetime) else None
    if value_type in (PT_GUID, PT_BINARY):
        value = _safe_attr(entry, "data")
        return None if value is None else bytes(value)
    return None


def _extract_named_properties(
    message: Any,
    definitions: dict[int, _NameIdDefinition],
    report: ExtractionReport,
) -> list[NamedPropertyValue]:
    if not definitions:
        return []

    result: list[NamedPropertyValue] = []
    for entry in _iter_record_entries(message):
        property_id = _int_attr(entry, "entry_type")
        definition = definitions.get(property_id)
        if definition is None:
            continue

        value_type = _int_attr(entry, "value_type")
        value = _entry_named_property_value(entry, value_type)
        if value is None:
            report.warn(
                "named property "
                f"{property_id:#06x} type {value_type:#06x} skipped"
            )
            continue

        result.append(
            NamedPropertyValue(
                guid=definition.guid,
                name=definition.name,
                property_type=value_type,
                value=value,
            )
        )
    return result


def _decode_body(value: Any) -> str | None:
    """Decode pypff body bytes without failing the whole message."""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return str(value)

    data = bytes(value)
    if not data:
        return ""

    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass

    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass

    # UTF-16 data without a BOM usually contains many NUL bytes.
    if len(data) >= 4 and data.count(b"\x00") > len(data) // 4:
        for encoding in ("utf-16-le", "utf-16-be"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _datetime_attr(obj: Any, name: str) -> datetime | None:
    value = _safe_attr(obj, name)
    return value if isinstance(value, datetime) else None


def _sender_email(message: Any) -> str | None:
    for property_id in (PR_SENDER_SMTP_ADDRESS, PR_SENDER_EMAIL_ADDRESS):
        value = _property_string(message, property_id)
        if value:
            return value

    headers = _safe_attr(message, "transport_headers")
    if headers:
        try:
            for line in str(headers).splitlines():
                if line.lower().startswith("from:"):
                    _name, address = parseaddr(line[5:].strip())
                    if address:
                        return address
        except Exception:
            pass

    return None


def _extract_recipients(message: Any) -> list[Recipient]:
    recipients_item = _safe_attr(message, "recipients")
    if recipients_item is None:
        return []

    recipients: list[Recipient] = []
    count = _int_attr(recipients_item, "number_of_recipients")

    for index in range(count):
        try:
            row = recipients_item.get_recipient(index)
        except Exception:
            continue

        recipient_type = _property_integer(row, PR_RECIPIENT_TYPE)
        address = (
            _property_string(row, PR_SMTP_ADDRESS)
            or _property_string(row, PR_EMAIL_ADDRESS)
        )

        recipients.append(
            Recipient(
                name=_property_string(row, PR_DISPLAY_NAME),
                email=address,
                recipient_type=RECIPIENT_TYPES.get(recipient_type, "unknown"),
            )
        )

    return recipients


def _attachment_data(attachment: Any) -> bytes:
    size = _int_attr(attachment, "size")
    if size == 0:
        return b""

    try:
        attachment.seek_offset(0, 0)
    except Exception:
        pass

    chunks: list[bytes] = []
    remaining = size
    chunk_size = 1024 * 1024

    while remaining > 0:
        request_size = min(chunk_size, remaining)
        data = attachment.read_buffer(request_size)
        if not data:
            break

        chunk = bytes(data)
        chunks.append(chunk)
        remaining -= len(chunk)

        if len(chunk) < request_size:
            break

    return b"".join(chunks)


def _extract_attachment(
    attachment: Any,
    report: ExtractionReport,
    nameid_definitions: dict[int, _NameIdDefinition],
) -> Attachment:
    filename = _safe_attr(attachment, "long_filename")
    if not filename:
        filename = (
            _property_string(attachment, PR_ATTACH_LONG_FILENAME)
            or _property_string(attachment, PR_ATTACH_FILENAME)
        )

    mime_type = _property_string(attachment, PR_ATTACH_MIME_TAG)
    if not mime_type and filename:
        mime_type = mimetypes.guess_type(str(filename))[0]

    method = _property_integer(attachment, PR_ATTACH_METHOD)
    embedded_message = None

    if method == ATTACH_EMBEDDED_MESSAGE:
        embedded_item = None
        try:
            if _int_attr(attachment, "number_of_sub_items") > 0:
                embedded_item = attachment.get_sub_item(0)
            else:
                embedded_item = attachment.get_sub_item(0)
        except Exception:
            embedded_item = None

        if embedded_item is not None:
            embedded_message = _extract_message(
                embedded_item,
                report,
                nameid_definitions,
            )
        else:
            report.warn(
                f"embedded attachment {filename!r} could not expose its message"
            )

    return Attachment(
        filename=str(filename) if filename else None,
        data=(
            b""
            if embedded_message is not None
            else _attachment_data(attachment)
        ),
        mime_type=mime_type,
        content_id=_property_string(attachment, PR_ATTACH_CONTENT_ID),
        content_location=_property_string(
            attachment,
            PR_ATTACH_CONTENT_LOCATION,
        ),
        embedded_message=embedded_message,
    )


def _normalize_rtf_body(value: Any) -> bytes | None:
    if value is None:
        return None
    raw = bytes(value)
    if raw.endswith(b"\x00"):
        raw = raw[:-1]
    return raw


def _extract_message(
    message: Any,
    report: ExtractionReport,
    nameid_definitions: dict[int, _NameIdDefinition],
) -> Message:
    flags = _property_integer(message, PR_MESSAGE_FLAGS)

    transport_headers = (
        _property_string(message, PR_TRANSPORT_MESSAGE_HEADERS)
        or _decode_body(_safe_attr(message, "transport_headers"))
    )

    result = Message(
        subject=_safe_attr(message, "subject"),
        sender_name=_safe_attr(message, "sender_name"),
        sender_email=_sender_email(message),
        body_text=_decode_body(_safe_attr(message, "plain_text_body")),
        body_html=_decode_body(_safe_attr(message, "html_body")),
        body_rtf=_normalize_rtf_body(_safe_attr(message, "rtf_body")),
        message_class=(
            _property_string(message, PR_MESSAGE_CLASS)
            or _safe_attr(message, "message_class")
        ),
        internet_message_id=_property_string(
            message,
            PR_INTERNET_MESSAGE_ID,
        ),
        transport_headers=transport_headers,
        conversation_topic=_property_string(
            message,
            PR_CONVERSATION_TOPIC,
        ),
        conversation_index=_property_binary(
            message,
            PR_CONVERSATION_INDEX,
        ),
        importance=_property_integer(message, PR_IMPORTANCE),
        sensitivity=_property_integer(message, PR_SENSITIVITY),
        delivery_time=_datetime_attr(message, "delivery_time"),
        creation_time=_datetime_attr(message, "creation_time"),
        is_read=bool(flags & MESSAGE_FLAG_READ) if flags is not None else None,
        recipients=_extract_recipients(message),
        named_properties=_extract_named_properties(
            message,
            nameid_definitions,
            report,
        ),
    )

    attachment_count = _int_attr(message, "number_of_attachments")
    report.attachments_seen += attachment_count

    for index in range(attachment_count):
        try:
            attachment = message.get_attachment(index)
            result.attachments.append(
                _extract_attachment(
                    attachment,
                    report,
                    nameid_definitions,
                )
            )
            report.attachments_loaded += 1
        except Exception as exc:
            report.attachments_failed += 1
            report.warn(f"attachment {index} failed in message {result.subject!r}: {exc}")

    return result


def _extract_folder(
    folder: Any,
    report: ExtractionReport,
    fallback_name: str,
    nameid_definitions: dict[int, _NameIdDefinition],
) -> Folder:
    report.folders_seen += 1
    name = _safe_attr(folder, "name") or fallback_name
    result = Folder(name=str(name))
    report.folders_loaded += 1

    message_count = _int_attr(folder, "number_of_sub_messages")
    report.messages_seen += message_count

    for index in range(message_count):
        try:
            message = folder.get_sub_message(index)
            result.messages.append(
                _extract_message(
                    message,
                    report,
                    nameid_definitions,
                )
            )
            report.messages_loaded += 1
        except Exception as exc:
            report.messages_failed += 1
            report.warn(f"message {index} failed in folder {result.name!r}: {exc}")

    child_count = _int_attr(folder, "number_of_sub_folders")
    for index in range(child_count):
        try:
            child = folder.get_sub_folder(index)
        except Exception as exc:
            report.folders_seen += 1
            report.folders_failed += 1
            report.warn(f"subfolder {index} failed in folder {result.name!r}: {exc}")
            continue

        result.folders.append(
            _extract_folder(
                child,
                report,
                fallback_name=f"Folder {index + 1}",
                nameid_definitions=nameid_definitions,
            )
        )

    return result


def _select_logical_root(root: Any) -> Any:
    """Return the user-visible IPM subtree when a standard PST root exists."""

    root_identifier = _int_attr(root, "identifier")
    if root_identifier != NID_ROOT_FOLDER:
        return root

    child_count = _int_attr(root, "number_of_sub_folders")
    fallback = None

    for index in range(child_count):
        try:
            child = root.get_sub_folder(index)
        except Exception:
            continue

        identifier = _int_attr(child, "identifier")
        if identifier == NID_IPM_SUBTREE:
            return child

        name = _safe_attr(child, "name")
        if name == "Top of Personal Folders":
            fallback = child

    return fallback or root


def _walk_folder(folder: Any, stats: InspectionStats) -> None:
    stats.folders += 1

    message_count = _int_attr(folder, "number_of_sub_messages")
    stats.messages += message_count

    for index in range(message_count):
        try:
            message = folder.get_sub_message(index)
            stats.attachments += _int_attr(message, "number_of_attachments")
        except Exception:
            continue

    child_count = _int_attr(folder, "number_of_sub_folders")
    for index in range(child_count):
        try:
            child = folder.get_sub_folder(index)
        except Exception:
            continue
        _walk_folder(child, stats)


def inspect_store(path: str | Path) -> InspectionStats:
    """Inspect an OST/PST without modifying it."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    pypff = _load_pypff()
    store = pypff.file()
    stats = InspectionStats(path=str(source))

    try:
        store.open(str(source))
        root = store.get_root_folder()
        _walk_folder(root, stats)
    finally:
        try:
            store.close()
        except Exception:
            pass

    return stats


def load_mailbox(path: str | Path) -> tuple[Mailbox, ExtractionReport]:
    """Load an OST/PST into the format-neutral mailbox model.

    Extraction is best-effort: corrupt messages, folders, or attachments are
    recorded in the report and skipped where possible. The source file is
    always opened read-only by libpff and is never modified.
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    pypff = _load_pypff()
    store = pypff.file()
    report = ExtractionReport(path=str(source))

    try:
        store.open(str(source))
        nameid_definitions = _extract_nameid_definitions(store, report)
        root = _select_logical_root(store.get_root_folder())
        mailbox = Mailbox(
            root=_extract_folder(
                root,
                report,
                fallback_name="Top of Personal Folders",
                nameid_definitions=nameid_definitions,
            )
        )
    finally:
        try:
            store.close()
        except Exception:
            pass

    return mailbox, report
