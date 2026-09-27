"""Allocation Map (AMap) pages and shared physical allocation.

Unicode PST AMaps track 64-byte allocation units. Each 496-byte bitmap maps a
253,952-byte span beginning at the AMap page itself. Bit order is MSB-first,
matching libpff and [MS-PST]: bit 0 is mask 0x80 of byte 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .pages import PAGE_DATA_SIZE, PageTrailer, PageType
from .primitives import (
    BLOCK_ALIGNMENT,
    BLOCK_MAX_SIZE,
    PAGE_SIZE,
    block_aligned_size,
)


AMAP_FIRST_OFFSET = 0x4400
AMAP_DATA_SIZE = PAGE_DATA_SIZE  # 496 bytes
AMAP_ALLOCATION_UNIT = BLOCK_ALIGNMENT  # 64 bytes
AMAP_BITS = AMAP_DATA_SIZE * 8
AMAP_SPAN = AMAP_BITS * AMAP_ALLOCATION_UNIT  # 0x3E000
AMAP_SELF_SLOTS = PAGE_SIZE // AMAP_ALLOCATION_UNIT  # 8


@dataclass(frozen=True, slots=True)
class AmapImage:
    """One fully serialized Unicode AMap page."""

    ib: int
    data: bytes

    def __post_init__(self) -> None:
        if self.ib < AMAP_FIRST_OFFSET:
            raise ValueError("AMap offset is before the first AMap")
        if (self.ib - AMAP_FIRST_OFFSET) % AMAP_SPAN:
            raise ValueError("AMap offset is not on an AMap interval")
        if len(self.data) != PAGE_SIZE:
            raise ValueError("AMap image must be exactly 512 bytes")


@dataclass(slots=True)
class AmapAllocator:
    """Shared allocator that keeps AMap bitmaps synchronized.

    The allocator grows the represented PST in complete AMap spans, as required
    by MS-PST. It can hand out both 64-byte-aligned block space and
    512-byte-aligned page space through lightweight adapters.
    """

    next_ib: int = AMAP_FIRST_OFFSET + PAGE_SIZE
    _bitmaps: dict[int, bytearray] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.next_ib, int) or self.next_ib < AMAP_FIRST_OFFSET:
            raise ValueError("next_ib must be at or after the first AMap")
        self.next_ib = _align_up(self.next_ib, AMAP_ALLOCATION_UNIT)

        last_required = self._amap_base_for(self.next_ib)
        amap_ib = AMAP_FIRST_OFFSET
        while amap_ib <= last_required:
            self._ensure_amap(amap_ib)
            amap_ib += AMAP_SPAN

        if self._is_inside_amap_page(self.next_ib):
            self.next_ib = self._amap_base_for(self.next_ib) + PAGE_SIZE

    @property
    def amap_offsets(self) -> tuple[int, ...]:
        return tuple(sorted(self._bitmaps))

    @property
    def last_amap_ib(self) -> int:
        return max(self._bitmaps)

    @property
    def file_eof(self) -> int:
        """Logical EOF after growth in whole AMap spans."""

        return self.last_amap_ib + AMAP_SPAN

    @property
    def free_bytes(self) -> int:
        """Total free space represented by all current AMaps."""

        free_bits = 0
        for bitmap in self._bitmaps.values():
            free_bits += sum(8 - byte.bit_count() for byte in bitmap)
        return free_bits * AMAP_ALLOCATION_UNIT

    @property
    def images(self) -> tuple[AmapImage, ...]:
        return tuple(
            AmapImage(ib=ib, data=pack_amap_page(bytes(self._bitmaps[ib]), ib))
            for ib in self.amap_offsets
        )

    @property
    def chunks(self) -> tuple[tuple[int, bytes], ...]:
        return tuple((image.ib, image.data) for image in self.images)

    def bitmap(self, amap_ib: int) -> bytes:
        try:
            return bytes(self._bitmaps[amap_ib])
        except KeyError as exc:
            raise KeyError(f"unknown AMap at {amap_ib:#x}") from exc

    def is_allocated(self, ib: int) -> bool:
        if ib < AMAP_FIRST_OFFSET or ib % AMAP_ALLOCATION_UNIT:
            raise ValueError("ib must be a 64-byte-aligned mapped offset")
        amap_ib = self._amap_base_for(ib)
        bitmap = self._bitmaps.get(amap_ib)
        if bitmap is None:
            return False
        slot = (ib - amap_ib) // AMAP_ALLOCATION_UNIT
        byte_index, bit_index = divmod(slot, 8)
        return bool(bitmap[byte_index] & (0x80 >> bit_index))

    def allocate(self, size: int, *, alignment: int = AMAP_ALLOCATION_UNIT) -> int:
        """Allocate one physical extent and update its AMap.

        Individual MS-PST allocations are at most 8192 bytes. The size passed
        here is the physical extent size, including any block padding/trailer.
        """

        if not isinstance(size, int) or not 0 < size <= BLOCK_MAX_SIZE:
            raise ValueError(f"size must be between 1 and {BLOCK_MAX_SIZE}")
        if size % AMAP_ALLOCATION_UNIT:
            raise ValueError("size must be a multiple of 64 bytes")
        if alignment not in (AMAP_ALLOCATION_UNIT, PAGE_SIZE):
            raise ValueError("alignment must be 64 or 512 bytes")

        candidate = _align_up(self.next_ib, alignment)

        while True:
            amap_ib = self._amap_base_for(candidate)
            self._ensure_amap_chain(amap_ib)

            data_start = amap_ib
            data_end = amap_ib + AMAP_SPAN

            if candidate < amap_ib + PAGE_SIZE:
                candidate = _align_up(amap_ib + PAGE_SIZE, alignment)

            if candidate + size <= data_end:
                break

            next_amap = amap_ib + AMAP_SPAN
            self._ensure_amap_chain(next_amap)
            candidate = _align_up(next_amap + PAGE_SIZE, alignment)

        self.mark_allocated(candidate, size)
        self.next_ib = candidate + size
        return candidate

    def allocate_page(self) -> int:
        return self.allocate(PAGE_SIZE, alignment=PAGE_SIZE)

    def allocate_block(self, payload_size: int) -> int:
        footprint = block_aligned_size(payload_size)
        return self.allocate(footprint, alignment=AMAP_ALLOCATION_UNIT)

    def mark_allocated(self, ib: int, size: int) -> None:
        """Mark an already-chosen physical extent allocated in its AMap."""

        if ib < AMAP_FIRST_OFFSET or ib % AMAP_ALLOCATION_UNIT:
            raise ValueError("ib must be a 64-byte-aligned mapped offset")
        if size <= 0 or size % AMAP_ALLOCATION_UNIT:
            raise ValueError("size must be a positive multiple of 64 bytes")

        remaining = size
        cursor = ib
        while remaining:
            amap_ib = self._amap_base_for(cursor)
            self._ensure_amap_chain(amap_ib)
            span_end = amap_ib + AMAP_SPAN
            chunk = min(remaining, span_end - cursor)
            if chunk <= 0:
                raise ValueError("allocation cannot overlap an AMap boundary")

            start_slot = (cursor - amap_ib) // AMAP_ALLOCATION_UNIT
            slot_count = chunk // AMAP_ALLOCATION_UNIT
            if start_slot + slot_count > AMAP_BITS:
                raise ValueError("allocation exceeds AMap coverage")

            self._set_slots(self._bitmaps[amap_ib], start_slot, slot_count)
            cursor += chunk
            remaining -= chunk

            if remaining:
                # The next AMap owns its first page. User allocations cannot
                # continue through that page, so crossing extents are invalid.
                raise ValueError("one allocation cannot cross an AMap boundary")

    def page_allocator(self) -> "AmapPageAllocator":
        return AmapPageAllocator(self)

    def block_allocator(self) -> "AmapBlockOffsetAllocator":
        return AmapBlockOffsetAllocator(self)

    def _ensure_amap_chain(self, target_ib: int) -> None:
        amap_ib = AMAP_FIRST_OFFSET
        while amap_ib <= target_ib:
            self._ensure_amap(amap_ib)
            amap_ib += AMAP_SPAN

    def _ensure_amap(self, amap_ib: int) -> None:
        if amap_ib in self._bitmaps:
            return
        if amap_ib < AMAP_FIRST_OFFSET or (amap_ib - AMAP_FIRST_OFFSET) % AMAP_SPAN:
            raise ValueError("invalid AMap offset")

        bitmap = bytearray(AMAP_DATA_SIZE)
        # The AMap maps itself; its 512-byte page consumes the first 8 slots.
        bitmap[0] = 0xFF
        self._bitmaps[amap_ib] = bitmap

    @staticmethod
    def _set_slots(bitmap: bytearray, start_slot: int, count: int) -> None:
        for slot in range(start_slot, start_slot + count):
            byte_index, bit_index = divmod(slot, 8)
            mask = 0x80 >> bit_index
            if bitmap[byte_index] & mask:
                raise ValueError(f"allocation overlaps occupied AMap slot {slot}")
            bitmap[byte_index] |= mask

    @staticmethod
    def _amap_base_for(ib: int) -> int:
        if ib < AMAP_FIRST_OFFSET:
            raise ValueError("offset is before first AMap")
        index = (ib - AMAP_FIRST_OFFSET) // AMAP_SPAN
        return AMAP_FIRST_OFFSET + index * AMAP_SPAN

    @staticmethod
    def _is_inside_amap_page(ib: int) -> bool:
        amap_ib = AmapAllocator._amap_base_for(ib)
        return amap_ib <= ib < amap_ib + PAGE_SIZE


@dataclass(frozen=True, slots=True)
class AmapPageAllocator:
    """Adapter accepted by the existing NBT/BBT page builders."""

    amap: AmapAllocator

    def allocate(self) -> int:
        return self.amap.allocate_page()


@dataclass(frozen=True, slots=True)
class AmapBlockOffsetAllocator:
    """Adapter accepted by DataBlockStore."""

    amap: AmapAllocator

    def allocate(self, payload_size: int) -> int:
        return self.amap.allocate_block(payload_size)


def pack_amap_page(bitmap: bytes, ib: int) -> bytes:
    """Serialize one Unicode AMap page including its PAGETRAILER."""

    if len(bitmap) != AMAP_DATA_SIZE:
        raise ValueError(f"AMap bitmap must be exactly {AMAP_DATA_SIZE} bytes")
    if ib < AMAP_FIRST_OFFSET or (ib - AMAP_FIRST_OFFSET) % AMAP_SPAN:
        raise ValueError("invalid AMap offset")
    if bitmap[0] != 0xFF:
        raise ValueError("AMap must mark its own 512-byte page allocated")

    trailer = PageTrailer.for_page(
        page_type=PageType.AMAP,
        ib=ib,
        bid=ib,
        page_data=bitmap,
    )
    result = bitmap + trailer.pack()
    assert len(result) == PAGE_SIZE
    return result


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)
