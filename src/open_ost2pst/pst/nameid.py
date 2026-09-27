"""MS-PST Name-to-ID map and named-property allocation."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from uuid import UUID

from .crc import compute_crc
from .ltp.pc import PropertyContext


NID_NAME_TO_ID_MAP = 0x0061

PR_NAMEID_BUCKET_COUNT = 0x0001
PR_NAMEID_STREAM_GUID = 0x0002
PR_NAMEID_STREAM_ENTRY = 0x0003
PR_NAMEID_STREAM_STRING = 0x0004
PR_NAMEID_BUCKET_BASE = 0x1000

DEFAULT_BUCKET_COUNT = 251
FIRST_NAMED_PROPERTY_ID = 0x8000
LAST_NAMED_PROPERTY_ID = 0x8FFF

PS_MAPI = UUID("00020328-0000-0000-c000-000000000046")
PS_PUBLIC_STRINGS = UUID("00020329-0000-0000-c000-000000000046")


@dataclass(frozen=True, slots=True)
class NameIdRecord:
    property_id_or_offset: int
    guid_index: int
    property_index: int
    is_string: bool

    @property
    def named_property_id(self) -> int:
        return FIRST_NAMED_PROPERTY_ID + self.property_index

    @property
    def packed_guid(self) -> int:
        if not 0 <= self.guid_index <= 0x7FFF:
            raise ValueError("NAMEID GUID index must fit in 15 bits")
        return (self.guid_index << 1) | (1 if self.is_string else 0)

    def pack(self) -> bytes:
        if not 0 <= self.property_id_or_offset <= 0xFFFFFFFF:
            raise ValueError("NAMEID property ID/offset must fit in 32 bits")
        if not 0 <= self.property_index <= 0xFFFF:
            raise ValueError("NAMEID property index must fit in 16 bits")
        return struct.pack(
            "<IHH",
            self.property_id_or_offset,
            self.packed_guid,
            self.property_index,
        )


@dataclass(frozen=True, slots=True)
class NamedProperty:
    property_id: int
    guid: UUID | None
    name: str | int


class NameIdMap:
    """Allocate and serialize PST named-property mappings."""

    def __init__(self, *, bucket_count: int = DEFAULT_BUCKET_COUNT) -> None:
        if not 1 <= bucket_count <= 0x0FFF:
            raise ValueError("bucket_count must be between 1 and 4095")
        self.bucket_count = bucket_count
        self._properties: list[NamedProperty] = []
        self._lookup: dict[tuple[UUID | None, str | int], int] = {}

    @property
    def property_count(self) -> int:
        return len(self._properties)

    @property
    def properties(self) -> tuple[NamedProperty, ...]:
        return tuple(self._properties)

    def register_string(
        self,
        name: str,
        *,
        guid: UUID | str | None = None,
    ) -> int:
        if not name:
            raise ValueError("named property string cannot be empty")
        return self._register(_coerce_guid(guid), name)

    def register_numeric(
        self,
        lid: int,
        *,
        guid: UUID | str,
    ) -> int:
        if not 0 <= lid <= 0xFFFF:
            raise ValueError("named property LID must fit in 16 bits")
        return self._register(_coerce_guid(guid), lid)

    def build_property_context(self) -> PropertyContext:
        pc = PropertyContext()
        pc.set_integer32(PR_NAMEID_BUCKET_COUNT, self.bucket_count)

        if not self._properties:
            return pc

        guid_stream, guid_indices = self._build_guid_stream()
        string_stream = bytearray()
        entry_stream = bytearray()
        buckets: list[bytearray] = [
            bytearray() for _ in range(self.bucket_count)
        ]

        for property_index, prop in enumerate(self._properties):
            is_string = isinstance(prop.name, str)
            guid_index = _guid_index(prop.guid, guid_indices, is_string)

            if is_string:
                encoded = prop.name.encode("utf-16-le")
                stream_offset = len(string_stream)
                string_stream.extend(struct.pack("<I", len(encoded)))
                string_stream.extend(encoded)
                while len(string_stream) % 4:
                    string_stream.append(0)

                entry_record = NameIdRecord(
                    property_id_or_offset=stream_offset,
                    guid_index=guid_index,
                    property_index=property_index,
                    is_string=True,
                )
                hash_property_id = compute_crc(encoded)
            else:
                entry_record = NameIdRecord(
                    property_id_or_offset=int(prop.name),
                    guid_index=guid_index,
                    property_index=property_index,
                    is_string=False,
                )
                hash_property_id = int(prop.name)

            entry_stream.extend(entry_record.pack())

            hash_record = NameIdRecord(
                property_id_or_offset=hash_property_id,
                guid_index=guid_index,
                property_index=property_index,
                is_string=is_string,
            )
            bucket_index = (
                hash_record.property_id_or_offset
                ^ hash_record.packed_guid
            ) % self.bucket_count
            buckets[bucket_index].extend(hash_record.pack())

        if guid_stream:
            pc.set_binary(PR_NAMEID_STREAM_GUID, guid_stream)
        if entry_stream:
            pc.set_binary(PR_NAMEID_STREAM_ENTRY, entry_stream)
        if string_stream:
            pc.set_binary(PR_NAMEID_STREAM_STRING, string_stream)

        for bucket_index, bucket in enumerate(buckets):
            if bucket:
                pc.set_binary(PR_NAMEID_BUCKET_BASE + bucket_index, bucket)

        return pc

    def _register(
        self,
        guid: UUID | None,
        name: str | int,
    ) -> int:
        key = (guid, name)
        existing = self._lookup.get(key)
        if existing is not None:
            return existing

        property_index = len(self._properties)
        property_id = FIRST_NAMED_PROPERTY_ID + property_index
        if property_id > LAST_NAMED_PROPERTY_ID:
            raise OverflowError("PST named-property ID range exhausted")

        if isinstance(name, int) and guid is None:
            raise ValueError("numeric named properties require a GUID")

        self._properties.append(
            NamedProperty(
                property_id=property_id,
                guid=guid,
                name=name,
            )
        )
        self._lookup[key] = property_id
        return property_id

    def _build_guid_stream(self) -> tuple[bytes, dict[UUID, int]]:
        custom: list[UUID] = []
        indices: dict[UUID, int] = {}

        for prop in self._properties:
            guid = prop.guid
            if guid is None or guid in (PS_MAPI, PS_PUBLIC_STRINGS):
                continue
            if guid not in indices:
                indices[guid] = len(custom)
                custom.append(guid)

        return (
            b"".join(guid.bytes_le for guid in custom),
            indices,
        )


def parse_nameid_records(data: bytes) -> tuple[NameIdRecord, ...]:
    if len(data) % 8:
        raise ValueError("NAMEID stream length must be a multiple of 8")

    result = []
    for offset in range(0, len(data), 8):
        property_id_or_offset, packed_guid, property_index = struct.unpack_from(
            "<IHH",
            data,
            offset,
        )
        result.append(
            NameIdRecord(
                property_id_or_offset=property_id_or_offset,
                guid_index=packed_guid >> 1,
                property_index=property_index,
                is_string=bool(packed_guid & 1),
            )
        )
    return tuple(result)


def _guid_index(
    guid: UUID | None,
    custom_indices: dict[UUID, int],
    is_string: bool,
) -> int:
    if guid is None:
        if not is_string:
            raise ValueError("numeric named properties require a GUID")
        return 0
    if guid == PS_MAPI:
        return 1
    if guid == PS_PUBLIC_STRINGS:
        return 2
    return custom_indices[guid] + 3


def _coerce_guid(value: UUID | str | None) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    return UUID(str(value))
