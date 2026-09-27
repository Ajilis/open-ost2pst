"""Property Context (PC) writer for the MS-PST LTP layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import Iterable

from .bth import BthBuildResult, build_bth, parse_leaf_records
from .heap import (
    HID_NULL,
    MAX_HEAP_ALLOCATION,
    HeapClientSignature,
    HeapImage,
    HeapNode,
)


class PropertyType(IntEnum):
    INTEGER16 = 0x0002
    INTEGER32 = 0x0003
    FLOAT32 = 0x0004
    FLOAT64 = 0x0005
    BOOLEAN = 0x000B
    INTEGER64 = 0x0014
    STRING8 = 0x001E
    UNICODE = 0x001F
    SYSTIME = 0x0040
    GUID = 0x0048
    BINARY = 0x0102


_FIXED_INLINE_TYPES = {
    PropertyType.INTEGER16,
    PropertyType.INTEGER32,
    PropertyType.FLOAT32,
    PropertyType.BOOLEAN,
}


@dataclass(frozen=True, slots=True)
class PropertyContextEntry:
    property_id: int
    property_type: PropertyType
    hnid: int

    def __post_init__(self) -> None:
        if not 0 <= self.property_id <= 0xFFFF:
            raise ValueError("property_id must fit in 16 bits")
        if not 0 <= self.hnid <= 0xFFFFFFFF:
            raise ValueError("HNID must fit in 32 bits")

    @property
    def key(self) -> bytes:
        return struct.pack("<H", self.property_id)

    @property
    def data(self) -> bytes:
        return struct.pack("<HI", int(self.property_type), self.hnid)


@dataclass(frozen=True, slots=True)
class PropertyContextImage:
    heap: HeapImage
    bth: BthBuildResult
    entries: tuple[PropertyContextEntry, ...]

    def single_block(self) -> bytes:
        return self.heap.single_block()


@dataclass(frozen=True, slots=True)
class _PropertyValue:
    property_type: PropertyType
    data: bytes
    inline: bool


class PropertyContext:
    """Build a Property Context backed by an HN and a 2+6 byte BTH."""

    def __init__(self) -> None:
        self._properties: dict[int, _PropertyValue] = {}

    @property
    def property_count(self) -> int:
        return len(self._properties)

    @property
    def property_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._properties))

    def delete(self, property_id: int) -> None:
        self._validate_property_id(property_id)
        self._properties.pop(property_id, None)

    def set_integer16(self, property_id: int, value: int) -> None:
        self._set_fixed(
            property_id,
            PropertyType.INTEGER16,
            struct.pack("<h", value),
        )

    def set_integer32(self, property_id: int, value: int) -> None:
        self._set_fixed(
            property_id,
            PropertyType.INTEGER32,
            struct.pack("<i", value),
        )

    def set_boolean(self, property_id: int, value: bool) -> None:
        self._set_fixed(
            property_id,
            PropertyType.BOOLEAN,
            struct.pack("<H", 1 if value else 0),
        )

    def set_float32(self, property_id: int, value: float) -> None:
        self._set_fixed(
            property_id,
            PropertyType.FLOAT32,
            struct.pack("<f", value),
        )

    def set_integer64(self, property_id: int, value: int) -> None:
        self._set_variable(
            property_id,
            PropertyType.INTEGER64,
            struct.pack("<q", value),
        )

    def set_float64(self, property_id: int, value: float) -> None:
        self._set_variable(
            property_id,
            PropertyType.FLOAT64,
            struct.pack("<d", value),
        )

    def set_filetime(self, property_id: int, value: int) -> None:
        if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("FILETIME must fit in 64 bits")
        self._set_variable(
            property_id,
            PropertyType.SYSTIME,
            struct.pack("<Q", value),
        )

    def set_unicode(self, property_id: int, value: str) -> None:
        encoded = value.encode("utf-16-le") + b"\x00\x00"
        self._set_variable(property_id, PropertyType.UNICODE, encoded)

    def set_string8(
        self,
        property_id: int,
        value: str,
        *,
        encoding: str = "cp1252",
    ) -> None:
        encoded = value.encode(encoding) + b"\x00"
        self._set_variable(property_id, PropertyType.STRING8, encoded)

    def set_binary(
        self,
        property_id: int,
        value: bytes | bytearray | memoryview,
    ) -> None:
        raw = bytes(value)
        if not raw:
            raise ValueError(
                "empty PT_BINARY is not emitted until zero-length HNID "
                "semantics are implemented"
            )
        self._set_variable(property_id, PropertyType.BINARY, raw)

    def set_guid(
        self,
        property_id: int,
        value: bytes | bytearray | memoryview,
    ) -> None:
        raw = bytes(value)
        if len(raw) != 16:
            raise ValueError("GUID property data must be exactly 16 bytes")
        self._set_variable(property_id, PropertyType.GUID, raw)

    def build(self) -> PropertyContextImage:
        heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)
        records: list[tuple[bytes, bytes]] = []
        entries: list[PropertyContextEntry] = []

        for property_id in sorted(self._properties):
            prop = self._properties[property_id]
            if prop.inline:
                hnid = int.from_bytes(prop.data.ljust(4, b"\x00"), "little")
            else:
                if len(prop.data) > MAX_HEAP_ALLOCATION:
                    raise ValueError(
                        f"property 0x{property_id:04x} exceeds one HN "
                        "allocation; subnode storage is not implemented yet"
                    )
                hnid = heap.allocate(prop.data)

            entry = PropertyContextEntry(
                property_id=property_id,
                property_type=prop.property_type,
                hnid=hnid,
            )
            entries.append(entry)
            records.append((entry.key, entry.data))

        bth = build_bth(
            heap,
            cb_key=2,
            cb_ent=6,
            records=records,
        )

        return PropertyContextImage(
            heap=heap.build(),
            bth=bth,
            entries=tuple(entries),
        )

    def serialize(self) -> bytes:
        return self.build().single_block()

    def _set_fixed(
        self,
        property_id: int,
        property_type: PropertyType,
        data: bytes,
    ) -> None:
        self._validate_property_id(property_id)
        if property_type not in _FIXED_INLINE_TYPES:
            raise ValueError("property type is not a fixed inline PC type")
        if not 1 <= len(data) <= 4:
            raise ValueError("fixed PC values must be 1 to 4 bytes")
        self._properties[property_id] = _PropertyValue(
            property_type=property_type,
            data=data,
            inline=True,
        )

    def _set_variable(
        self,
        property_id: int,
        property_type: PropertyType,
        data: bytes,
    ) -> None:
        self._validate_property_id(property_id)
        if not data:
            raise ValueError("variable PC values must be non-empty")
        self._properties[property_id] = _PropertyValue(
            property_type=property_type,
            data=data,
            inline=False,
        )

    @staticmethod
    def _validate_property_id(property_id: int) -> None:
        if not isinstance(property_id, int) or not 0 <= property_id <= 0xFFFF:
            raise ValueError("property_id must fit in 16 bits")


def parse_property_context_entries(
    heap: HeapNode,
    bth: BthBuildResult,
) -> tuple[PropertyContextEntry, ...]:
    """Parse PC leaf records from a single-level BTH for diagnostics/tests."""

    if bth.index_levels != 0 or bth.root_hid == HID_NULL:
        raise ValueError("diagnostic parser currently expects one BTH leaf")

    records = parse_leaf_records(
        heap.get_allocation(bth.root_hid),
        cb_key=2,
        cb_ent=6,
    )

    entries = []
    for key, data in records:
        property_id = struct.unpack("<H", key)[0]
        property_type, hnid = struct.unpack("<HI", data)
        entries.append(
            PropertyContextEntry(
                property_id=property_id,
                property_type=PropertyType(property_type),
                hnid=hnid,
            )
        )
    return tuple(entries)
