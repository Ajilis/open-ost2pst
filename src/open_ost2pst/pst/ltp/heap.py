"""Heap-on-Node (HN) primitives for the MS-PST LTP layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct

from ..primitives import BLOCK_MAX_PAYLOAD


HID_NULL = 0
HN_SIGNATURE = 0xEC
HN_HEADER_SIZE = 12
HN_PAGE_HEADER_SIZE = 2
HN_BITMAP_HEADER_SIZE = 66
MAX_HEAP_ALLOCATION = 3580
MAX_HID_INDEX = 0x7FF
MAX_HID_BLOCK_INDEX = 0xFFFF


class HeapClientSignature(IntEnum):
    RESERVED_1 = 0x6C
    TABLE_CONTEXT = 0x7C
    RESERVED_2 = 0x8C
    RESERVED_3 = 0x9C
    RESERVED_4 = 0xA5
    RESERVED_5 = 0xAC
    BTH = 0xB5
    PROPERTY_CONTEXT = 0xBC
    RESERVED_6 = 0xCC


@dataclass(frozen=True, slots=True)
class HeapId:
    """A 4-byte Heap ID (HID)."""

    index: int
    block_index: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.index <= MAX_HID_INDEX:
            raise ValueError("HID index must be between 1 and 2047")
        if not 0 <= self.block_index <= MAX_HID_BLOCK_INDEX:
            raise ValueError("HID block index must fit in 16 bits")

    @property
    def value(self) -> int:
        return (self.block_index << 16) | (self.index << 5)

    def pack(self) -> bytes:
        return struct.pack("<I", self.value)

    @classmethod
    def from_value(cls, value: int) -> "HeapId":
        if value == HID_NULL:
            raise ValueError("HID 0 is the null HID")
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("HID must fit in 32 bits")
        if value & 0x1F:
            raise ValueError("HID type bits must be zero")
        return cls(
            index=(value >> 5) & MAX_HID_INDEX,
            block_index=(value >> 16) & MAX_HID_BLOCK_INDEX,
        )


def make_hid(index: int, block_index: int = 0) -> int:
    return HeapId(index=index, block_index=block_index).value


def hid_index(hid: int) -> int:
    return HeapId.from_value(hid).index


def hid_block_index(hid: int) -> int:
    return HeapId.from_value(hid).block_index


@dataclass(frozen=True, slots=True)
class HeapBlockImage:
    block_index: int
    data: bytes
    allocation_hids: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.data) > BLOCK_MAX_PAYLOAD:
            raise ValueError("HN block exceeds one NDB block payload")


@dataclass(frozen=True, slots=True)
class HeapImage:
    blocks: tuple[HeapBlockImage, ...]
    user_root: int
    client_signature: HeapClientSignature

    def single_block(self) -> bytes:
        if len(self.blocks) != 1:
            raise ValueError("HN spans multiple blocks")
        return self.blocks[0].data


class HeapOverflowError(ValueError):
    """Raised when an HN allocation cannot fit into one heap block."""


class HeapNode:
    """Mutable Heap-on-Node builder."""

    def __init__(self, client_signature: int | HeapClientSignature):
        try:
            self.client_signature = HeapClientSignature(int(client_signature))
        except ValueError as exc:
            raise ValueError("unsupported HN client signature") from exc

        self.user_root = HID_NULL
        self._blocks: list[list[bytes]] = [[]]

    @property
    def block_count(self) -> int:
        return len(self._blocks)

    @property
    def allocation_count(self) -> int:
        return sum(len(block) for block in self._blocks)

    def allocate(self, data: bytes | bytearray | memoryview) -> int:
        raw = bytes(data)
        if not raw:
            raise ValueError("HN allocations must be non-empty")
        if len(raw) > MAX_HEAP_ALLOCATION:
            raise HeapOverflowError(
                f"HN allocation exceeds {MAX_HEAP_ALLOCATION} bytes"
            )

        block_index = len(self._blocks) - 1
        allocations = self._blocks[block_index]

        if not _fits(block_index, allocations, raw):
            if block_index >= MAX_HID_BLOCK_INDEX:
                raise HeapOverflowError("HN exceeds HID block-index space")
            self._blocks.append([])
            block_index += 1
            allocations = self._blocks[block_index]

        if len(allocations) >= MAX_HID_INDEX:
            raise HeapOverflowError("HN block exceeds HID allocation-index space")

        if not _fits(block_index, allocations, raw):
            raise HeapOverflowError("allocation does not fit in an empty HN block")

        allocations.append(raw)
        return make_hid(len(allocations), block_index)

    def get_allocation(self, hid: int) -> bytes:
        parsed = HeapId.from_value(hid)
        try:
            block = self._blocks[parsed.block_index]
            return block[parsed.index - 1]
        except IndexError as exc:
            raise KeyError(f"unknown HID {hid:#x}") from exc

    def set_user_root(self, hid: int) -> None:
        if hid != HID_NULL:
            self.get_allocation(hid)
        self.user_root = hid

    def build(self) -> HeapImage:
        block_sizes = [
            _serialized_size(index, allocations)
            for index, allocations in enumerate(self._blocks)
        ]
        fill_levels = [_fill_level(BLOCK_MAX_PAYLOAD - size) for size in block_sizes]

        images: list[HeapBlockImage] = []
        for block_index, allocations in enumerate(self._blocks):
            data = _serialize_block(
                block_index=block_index,
                allocations=allocations,
                client_signature=self.client_signature,
                user_root=self.user_root,
                fill_levels=fill_levels,
            )
            images.append(
                HeapBlockImage(
                    block_index=block_index,
                    data=data,
                    allocation_hids=tuple(
                        make_hid(index + 1, block_index)
                        for index in range(len(allocations))
                    ),
                )
            )

        return HeapImage(
            blocks=tuple(images),
            user_root=self.user_root,
            client_signature=self.client_signature,
        )

    def serialize(self) -> bytes:
        return self.build().single_block()

    def serialize_blocks(self) -> tuple[bytes, ...]:
        return tuple(block.data for block in self.build().blocks)


def parse_page_map(block: bytes) -> tuple[int, int, tuple[int, ...]]:
    """Return cAlloc, cFree, and rgibAlloc for one serialized HN block."""

    if len(block) < HN_PAGE_HEADER_SIZE:
        raise ValueError("HN block is too small")

    ib_hnpm = struct.unpack_from("<H", block, 0)[0]
    if ib_hnpm + 6 > len(block):
        raise ValueError("invalid HNPAGEMAP offset")

    c_alloc, c_free = struct.unpack_from("<HH", block, ib_hnpm)
    count = c_alloc + 1
    end = ib_hnpm + 4 + count * 2
    if end > len(block):
        raise ValueError("truncated HNPAGEMAP")
    offsets = struct.unpack_from(f"<{count}H", block, ib_hnpm + 4)
    return c_alloc, c_free, tuple(offsets)


def _header_size(block_index: int) -> int:
    if block_index == 0:
        return HN_HEADER_SIZE
    if block_index >= 8 and (block_index - 8) % 128 == 0:
        return HN_BITMAP_HEADER_SIZE
    return HN_PAGE_HEADER_SIZE


def _fits(block_index: int, allocations: list[bytes], new_item: bytes) -> bool:
    return _serialized_size(block_index, [*allocations, new_item]) <= BLOCK_MAX_PAYLOAD


def _serialized_size(block_index: int, allocations: list[bytes]) -> int:
    header_size = _header_size(block_index)
    allocation_end = header_size + sum(len(item) for item in allocations)
    page_map_offset = (allocation_end + 1) & ~1
    page_map_size = 4 + 2 * (len(allocations) + 1)
    return page_map_offset + page_map_size


def _serialize_block(
    *,
    block_index: int,
    allocations: list[bytes],
    client_signature: HeapClientSignature,
    user_root: int,
    fill_levels: list[int],
) -> bytes:
    header_size = _header_size(block_index)
    allocation_offsets = [header_size]

    body = bytearray(header_size)
    for item in allocations:
        body.extend(item)
        allocation_offsets.append(len(body))

    if len(body) & 1:
        body.append(0)

    ib_hnpm = len(body)
    body.extend(struct.pack("<HH", len(allocations), 0))
    for offset in allocation_offsets:
        body.extend(struct.pack("<H", offset))

    if len(body) > BLOCK_MAX_PAYLOAD:
        raise HeapOverflowError("serialized HN block exceeds NDB payload limit")

    if block_index == 0:
        fill = _pack_fill_levels(fill_levels[:8], 8)
        struct.pack_into(
            "<HBBI4s",
            body,
            0,
            ib_hnpm,
            HN_SIGNATURE,
            int(client_signature),
            user_root,
            fill,
        )
    elif block_index >= 8 and (block_index - 8) % 128 == 0:
        fill = _pack_fill_levels(fill_levels[block_index:block_index + 128], 128)
        struct.pack_into("<H64s", body, 0, ib_hnpm, fill)
    else:
        struct.pack_into("<H", body, 0, ib_hnpm)

    return bytes(body)


def _pack_fill_levels(values: list[int], count: int) -> bytes:
    padded = list(values[:count]) + [0] * max(0, count - len(values))
    out = bytearray((count + 1) // 2)
    for index, value in enumerate(padded):
        if not 0 <= value <= 0x0F:
            raise ValueError("fill level must fit in four bits")
        byte_index = index // 2
        if index % 2 == 0:
            out[byte_index] |= value
        else:
            out[byte_index] |= value << 4
    return bytes(out)


def _fill_level(free_bytes: int) -> int:
    if free_bytes >= 3584:
        return 0x0
    if free_bytes >= 2560:
        return 0x1
    if free_bytes >= 2048:
        return 0x2
    if free_bytes >= 1792:
        return 0x3
    if free_bytes >= 1536:
        return 0x4
    if free_bytes >= 1280:
        return 0x5
    if free_bytes >= 1024:
        return 0x6
    if free_bytes >= 768:
        return 0x7
    if free_bytes >= 512:
        return 0x8
    if free_bytes >= 256:
        return 0x9
    if free_bytes >= 128:
        return 0xA
    if free_bytes >= 64:
        return 0xB
    if free_bytes >= 32:
        return 0xC
    if free_bytes >= 16:
        return 0xD
    if free_bytes >= 8:
        return 0xE
    return 0xF
