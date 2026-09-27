"""512-byte page structures for the Unicode MS-PST NDB layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct

from .crc import compute_crc
from .primitives import BRef, PAGE_SIZE, PAGE_TRAILER_SIZE, PageBidAllocator, compute_sig


PAGE_DATA_SIZE = PAGE_SIZE - PAGE_TRAILER_SIZE
BT_ENTRY_AREA_SIZE = 488
BT_PAGE_META_OFFSET = 488
BT_PAGE_PADDING_OFFSET = 492


class PageType(IntEnum):
    BBT = 0x80
    NBT = 0x81
    FMAP = 0x82
    PMAP = 0x83
    AMAP = 0x84
    FPMAP = 0x85
    DLIST = 0x86


_SIGNATURE_PAGE_TYPES = {PageType.BBT, PageType.NBT, PageType.DLIST}


@dataclass(frozen=True, slots=True)
class PageTrailer:
    """Unicode PAGETRAILER (16 bytes)."""

    page_type: PageType
    signature: int
    crc: int
    bid: int

    def pack(self) -> bytes:
        if not 0 <= self.signature <= 0xFFFF:
            raise ValueError("signature must fit in 16 bits")
        if not 0 <= self.crc <= 0xFFFFFFFF:
            raise ValueError("crc must fit in 32 bits")
        if not 0 <= self.bid <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("bid must fit in 64 bits")
        return struct.pack(
            "<BBHIQ",
            int(self.page_type),
            int(self.page_type),
            self.signature,
            self.crc,
            self.bid,
        )

    @classmethod
    def for_page(
        cls,
        *,
        page_type: PageType,
        ib: int,
        bid: int,
        page_data: bytes,
    ) -> "PageTrailer":
        if len(page_data) != PAGE_DATA_SIZE:
            raise ValueError(f"page_data must be exactly {PAGE_DATA_SIZE} bytes")
        signature = compute_sig(ib, bid) if page_type in _SIGNATURE_PAGE_TYPES else 0
        return cls(
            page_type=page_type,
            signature=signature,
            crc=compute_crc(page_data),
            bid=bid,
        )


@dataclass(frozen=True, slots=True)
class PageImage:
    """A fully serialized 512-byte NDB page plus placement metadata."""

    bref: BRef
    page_type: PageType
    level: int
    first_key: int | None
    data: bytes

    def __post_init__(self) -> None:
        if len(self.data) != PAGE_SIZE:
            raise ValueError("page image must be exactly 512 bytes")


@dataclass(slots=True)
class PageAllocator:
    """Allocate 512-byte-aligned absolute page offsets."""

    next_ib: int

    def __post_init__(self) -> None:
        if not isinstance(self.next_ib, int) or self.next_ib < 0:
            raise ValueError("next_ib must be a non-negative integer")
        self.next_ib = _align_up(self.next_ib, PAGE_SIZE)

    def allocate(self) -> int:
        ib = self.next_ib
        self.next_ib += PAGE_SIZE
        return ib


def pack_btree_page(
    *,
    page_type: PageType,
    ib: int,
    bid: int,
    entries: list[bytes] | tuple[bytes, ...],
    entry_size: int,
    level: int,
) -> bytes:
    """Serialize one Unicode BTPAGE including its PAGETRAILER."""

    if page_type not in (PageType.BBT, PageType.NBT):
        raise ValueError("BTPAGE page_type must be BBT or NBT")
    if not 1 <= entry_size <= BT_ENTRY_AREA_SIZE:
        raise ValueError("entry_size is outside the BTPAGE entry area")
    if not 0 <= level <= 0xFF:
        raise ValueError("level must fit in one byte")

    max_entries = BT_ENTRY_AREA_SIZE // entry_size
    if len(entries) > max_entries:
        raise ValueError("too many entries for one BTPAGE")

    body = bytearray(PAGE_DATA_SIZE)
    for index, entry in enumerate(entries):
        if len(entry) != entry_size:
            raise ValueError("all BTPAGE entries must match entry_size")
        start = index * entry_size
        body[start : start + entry_size] = entry

    body[BT_PAGE_META_OFFSET] = len(entries)
    body[BT_PAGE_META_OFFSET + 1] = max_entries
    body[BT_PAGE_META_OFFSET + 2] = entry_size
    body[BT_PAGE_META_OFFSET + 3] = level
    struct.pack_into("<I", body, BT_PAGE_PADDING_OFFSET, 0)

    trailer = PageTrailer.for_page(
        page_type=page_type,
        ib=ib,
        bid=bid,
        page_data=bytes(body),
    )
    page = bytes(body) + trailer.pack()
    assert len(page) == PAGE_SIZE
    return page


def make_btree_page(
    *,
    page_type: PageType,
    entries: list[bytes] | tuple[bytes, ...],
    entry_size: int,
    level: int,
    first_key: int | None,
    offset_allocator: PageAllocator,
    bid_allocator: PageBidAllocator,
) -> PageImage:
    """Allocate and serialize one BBT/NBT page."""

    ib = offset_allocator.allocate()
    bid = bid_allocator.allocate()
    data = pack_btree_page(
        page_type=page_type,
        ib=ib,
        bid=bid,
        entries=entries,
        entry_size=entry_size,
        level=level,
    )
    return PageImage(
        bref=BRef(bid=bid, ib=ib),
        page_type=page_type,
        level=level,
        first_key=first_key,
        data=data,
    )


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)
