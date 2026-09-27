"""BTree-on-Heap (BTH) builder for the MS-PST LTP layer."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterable

from .heap import HID_NULL, MAX_HEAP_ALLOCATION, HeapNode


BTH_TYPE = 0xB5
VALID_KEY_SIZES = {2, 4, 8, 16}


@dataclass(frozen=True, slots=True)
class BthHeader:
    cb_key: int
    cb_ent: int
    index_levels: int
    root_hid: int

    def __post_init__(self) -> None:
        if self.cb_key not in VALID_KEY_SIZES:
            raise ValueError("BTH key size must be 2, 4, 8, or 16 bytes")
        if not 1 <= self.cb_ent <= 32:
            raise ValueError("BTH entry size must be between 1 and 32 bytes")
        if not 0 <= self.index_levels <= 0xFF:
            raise ValueError("BTH index level count must fit in one byte")
        if not 0 <= self.root_hid <= 0xFFFFFFFF:
            raise ValueError("BTH root HID must fit in 32 bits")

    def pack(self) -> bytes:
        return struct.pack(
            "<BBBBI",
            BTH_TYPE,
            self.cb_key,
            self.cb_ent,
            self.index_levels,
            self.root_hid,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "BthHeader":
        if len(data) != 8:
            raise ValueError("BTHHEADER must be exactly 8 bytes")
        b_type, cb_key, cb_ent, index_levels, root_hid = struct.unpack(
            "<BBBBI", data
        )
        if b_type != BTH_TYPE:
            raise ValueError("invalid BTHHEADER type")
        return cls(cb_key, cb_ent, index_levels, root_hid)


@dataclass(frozen=True, slots=True)
class BthBuildResult:
    header_hid: int
    root_hid: int
    index_levels: int
    record_count: int


def build_bth(
    heap: HeapNode,
    *,
    cb_key: int,
    cb_ent: int,
    records: Iterable[tuple[bytes, bytes]],
    set_user_root: bool = True,
) -> BthBuildResult:
    """Build a BTH inside heap and return its header/root HIDs."""

    if cb_key not in VALID_KEY_SIZES:
        raise ValueError("BTH key size must be 2, 4, 8, or 16 bytes")
    if not 1 <= cb_ent <= 32:
        raise ValueError("BTH entry size must be between 1 and 32 bytes")

    prepared = list(records)
    for key, data in prepared:
        if len(key) != cb_key:
            raise ValueError("BTH key has wrong width")
        if len(data) != cb_ent:
            raise ValueError("BTH data has wrong width")

    prepared.sort(key=lambda item: int.from_bytes(item[0], "little"))
    _reject_duplicate_keys(prepared)

    if not prepared:
        header = BthHeader(cb_key, cb_ent, 0, HID_NULL)
        header_hid = heap.allocate(header.pack())
        if set_user_root:
            heap.set_user_root(header_hid)
        return BthBuildResult(header_hid, HID_NULL, 0, 0)

    leaf_record_size = cb_key + cb_ent
    leaf_capacity = max(1, MAX_HEAP_ALLOCATION // leaf_record_size)

    level: list[tuple[bytes, int]] = []
    for start in range(0, len(prepared), leaf_capacity):
        group = prepared[start:start + leaf_capacity]
        allocation = b"".join(key + data for key, data in group)
        level.append((group[0][0], heap.allocate(allocation)))

    index_levels = 0
    index_record_size = cb_key + 4
    index_capacity = max(1, MAX_HEAP_ALLOCATION // index_record_size)

    while len(level) > 1:
        index_levels += 1
        next_level: list[tuple[bytes, int]] = []
        for start in range(0, len(level), index_capacity):
            group = level[start:start + index_capacity]
            allocation = b"".join(
                key + struct.pack("<I", hid)
                for key, hid in group
            )
            next_level.append((group[0][0], heap.allocate(allocation)))
        level = next_level

    root_hid = level[0][1]
    header = BthHeader(cb_key, cb_ent, index_levels, root_hid)
    header_hid = heap.allocate(header.pack())

    if set_user_root:
        heap.set_user_root(header_hid)

    return BthBuildResult(
        header_hid=header_hid,
        root_hid=root_hid,
        index_levels=index_levels,
        record_count=len(prepared),
    )


def parse_leaf_records(
    data: bytes,
    *,
    cb_key: int,
    cb_ent: int,
) -> tuple[tuple[bytes, bytes], ...]:
    record_size = cb_key + cb_ent
    if record_size <= 0 or len(data) % record_size:
        raise ValueError("invalid BTH leaf allocation size")
    return tuple(
        (
            data[offset:offset + cb_key],
            data[offset + cb_key:offset + record_size],
        )
        for offset in range(0, len(data), record_size)
    )


def parse_index_records(
    data: bytes,
    *,
    cb_key: int,
) -> tuple[tuple[bytes, int], ...]:
    record_size = cb_key + 4
    if len(data) % record_size:
        raise ValueError("invalid BTH index allocation size")
    return tuple(
        (
            data[offset:offset + cb_key],
            struct.unpack_from("<I", data, offset + cb_key)[0],
        )
        for offset in range(0, len(data), record_size)
    )


def _reject_duplicate_keys(records: list[tuple[bytes, bytes]]) -> None:
    previous: int | None = None
    for key, _data in records:
        value = int.from_bytes(key, "little")
        if previous is not None and value == previous:
            raise ValueError(f"duplicate BTH key: {value:#x}")
        previous = value
