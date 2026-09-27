import struct

import pytest

from open_ost2pst.pst.amap import (
    AMAP_ALLOCATION_UNIT,
    AMAP_DATA_SIZE,
    AMAP_FIRST_OFFSET,
    AMAP_SPAN,
    AmapAllocator,
    pack_amap_page,
)
from open_ost2pst.pst.blocks import DataBlockStore
from open_ost2pst.pst.btree import BbtEntry, NbtEntry, build_bbt, build_nbt
from open_ost2pst.pst.crc import compute_crc
from open_ost2pst.pst.pages import PAGE_DATA_SIZE, PageType
from open_ost2pst.pst.primitives import (
    BlockBidAllocator,
    PAGE_SIZE,
    PageBidAllocator,
)


def _trailer(page: bytes) -> tuple[int, int, int, int, int]:
    return struct.unpack("<BBHIQ", page[PAGE_DATA_SIZE:])


def test_initial_amap_maps_itself() -> None:
    allocator = AmapAllocator()
    bitmap = allocator.bitmap(AMAP_FIRST_OFFSET)

    assert len(bitmap) == AMAP_DATA_SIZE
    assert bitmap[0] == 0xFF
    assert bitmap[1:] == bytes(AMAP_DATA_SIZE - 1)

    assert allocator.last_amap_ib == AMAP_FIRST_OFFSET
    assert allocator.file_eof == AMAP_FIRST_OFFSET + AMAP_SPAN
    assert allocator.free_bytes == (AMAP_DATA_SIZE * 8 - 8) * 64


def test_first_user_allocation_uses_msb_of_second_byte() -> None:
    allocator = AmapAllocator()

    first = allocator.allocate(64)
    second = allocator.allocate(64)

    assert first == 0x4600
    assert second == 0x4640

    bitmap = allocator.bitmap(AMAP_FIRST_OFFSET)
    assert bitmap[0] == 0xFF
    assert bitmap[1] == 0xC0

    assert allocator.is_allocated(0x4600) is True
    assert allocator.is_allocated(0x4640) is True
    assert allocator.is_allocated(0x4680) is False


def test_page_allocation_is_512_byte_aligned_and_marks_eight_slots() -> None:
    allocator = AmapAllocator()

    assert allocator.allocate(64) == 0x4600
    page_ib = allocator.allocate_page()

    assert page_ib == 0x4800
    assert page_ib % PAGE_SIZE == 0

    bitmap = allocator.bitmap(AMAP_FIRST_OFFSET)
    # slots 16..23 correspond exactly to bitmap byte 2.
    assert bitmap[2] == 0xFF

    for offset in range(page_ib, page_ib + PAGE_SIZE, 64):
        assert allocator.is_allocated(offset)


def test_amap_page_trailer_uses_ib_as_bid_and_zero_signature() -> None:
    allocator = AmapAllocator()
    page = allocator.images[0].data

    ptype, repeat, signature, crc, bid = _trailer(page)

    assert len(page) == PAGE_SIZE
    assert ptype == repeat == PageType.AMAP
    assert signature == 0
    assert crc == compute_crc(page[:PAGE_DATA_SIZE])
    assert bid == AMAP_FIRST_OFFSET


def test_pack_amap_requires_self_allocation_bits() -> None:
    with pytest.raises(ValueError, match="mark its own"):
        pack_amap_page(bytes(AMAP_DATA_SIZE), AMAP_FIRST_OFFSET)


def test_allocator_moves_to_next_amap_when_extent_would_cross_boundary() -> None:
    near_end = AMAP_FIRST_OFFSET + AMAP_SPAN - AMAP_ALLOCATION_UNIT
    allocator = AmapAllocator(next_ib=near_end)

    ib = allocator.allocate(128)

    second_amap = AMAP_FIRST_OFFSET + AMAP_SPAN
    assert ib == second_amap + PAGE_SIZE
    assert allocator.amap_offsets == (AMAP_FIRST_OFFSET, second_amap)
    assert allocator.last_amap_ib == second_amap
    assert allocator.file_eof == second_amap + AMAP_SPAN

    second_bitmap = allocator.bitmap(second_amap)
    assert second_bitmap[0] == 0xFF
    assert second_bitmap[1] == 0xC0


def test_amap_free_bytes_tracks_allocations() -> None:
    allocator = AmapAllocator()
    initial = allocator.free_bytes

    allocator.allocate(64)
    allocator.allocate_page()

    assert allocator.free_bytes == initial - 64 - PAGE_SIZE


def test_overlapping_manual_allocation_is_rejected() -> None:
    allocator = AmapAllocator()
    ib = allocator.allocate(64)

    with pytest.raises(ValueError, match="overlaps"):
        allocator.mark_allocated(ib, 64)


def test_one_allocation_cannot_cross_amap_boundary() -> None:
    allocator = AmapAllocator()

    with pytest.raises(ValueError, match="cannot cross"):
        allocator.mark_allocated(
            AMAP_FIRST_OFFSET + AMAP_SPAN - 64,
            128,
        )


def test_block_adapter_integrates_with_data_block_store() -> None:
    amap = AmapAllocator()
    store = DataBlockStore(
        offset_allocator=amap.block_allocator(),
        bid_allocator=BlockBidAllocator(4),
    )

    first = store.add(b"alpha")
    second = store.add(b"x" * 80)

    assert first.bref.ib == 0x4600
    assert second.bref.ib == 0x4640

    assert amap.is_allocated(first.bref.ib)
    assert amap.is_allocated(second.bref.ib)
    # second block has a 128-byte physical footprint.
    assert amap.is_allocated(second.bref.ib + 64)


def test_page_adapter_integrates_with_nbt_and_bbt_builders() -> None:
    amap = AmapAllocator()
    page_bids = PageBidAllocator(0x100)

    nbt = build_nbt(
        [NbtEntry(nid=0x122, data_bid=4, parent_nid=0x122)],
        offset_allocator=amap.page_allocator(),
        bid_allocator=page_bids,
    )
    bbt = build_bbt(
        [BbtEntry(bid=4, ib=0x8000, cb=32)],
        offset_allocator=amap.page_allocator(),
        bid_allocator=page_bids,
    )

    assert nbt.root.ib == 0x4600
    assert bbt.root.ib == 0x4800
    assert amap.is_allocated(0x4600)
    assert amap.is_allocated(0x47C0)
    assert amap.is_allocated(0x4800)
    assert amap.is_allocated(0x49C0)


def test_shared_amap_allocator_tracks_blocks_and_btree_pages_together() -> None:
    amap = AmapAllocator()
    blocks = DataBlockStore(
        offset_allocator=amap.block_allocator(),
        bid_allocator=BlockBidAllocator(4),
    )
    blocks.extend([b"one", b"two" * 30, b"three"])

    bbt = build_bbt(
        blocks.bbt_entries,
        offset_allocator=amap.page_allocator(),
        bid_allocator=PageBidAllocator(0x200),
    )

    for block in blocks.blocks:
        assert amap.is_allocated(block.bref.ib)

    assert amap.is_allocated(bbt.root.ib)
    assert len(amap.images) == 1
    assert amap.chunks[0][0] == AMAP_FIRST_OFFSET


def test_allocator_rejects_non_granular_sizes() -> None:
    allocator = AmapAllocator()

    with pytest.raises(ValueError, match="multiple of 64"):
        allocator.allocate(65)
