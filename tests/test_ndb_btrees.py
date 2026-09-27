import math
import struct

import pytest

from open_ost2pst.pst.btree import (
    BBT_LEAF_ENTRY_SIZE,
    BT_ENTRY_SIZE,
    MAX_BLOCK_PAYLOAD,
    NBT_LEAF_ENTRY_SIZE,
    BbtEntry,
    BtEntry,
    NbtEntry,
    build_bbt,
    build_nbt,
)
from open_ost2pst.pst.crc import compute_crc
from open_ost2pst.pst.pages import (
    BT_ENTRY_AREA_SIZE,
    BT_PAGE_META_OFFSET,
    PAGE_DATA_SIZE,
    PageAllocator,
    PageTrailer,
    PageType,
    pack_btree_page,
)
from open_ost2pst.pst.primitives import BRef, PAGE_SIZE, PageBidAllocator, compute_sig


def _meta(page: bytes) -> tuple[int, int, int, int]:
    return tuple(page[BT_PAGE_META_OFFSET : BT_PAGE_META_OFFSET + 4])


def _trailer(page: bytes) -> tuple[int, int, int, int, int]:
    return struct.unpack("<BBHIQ", page[PAGE_DATA_SIZE:])


def test_page_allocator_aligns_to_512_bytes() -> None:
    allocator = PageAllocator(next_ib=0x4401)

    assert allocator.allocate() == 0x4600
    assert allocator.allocate() == 0x4800


def test_page_trailer_contains_type_signature_crc_and_bid() -> None:
    ib = 0x6000
    bid = 0x123
    body = bytes((index * 7) & 0xFF for index in range(PAGE_DATA_SIZE))

    trailer = PageTrailer.for_page(
        page_type=PageType.NBT,
        ib=ib,
        bid=bid,
        page_data=body,
    ).pack()

    ptype, repeat, signature, crc, stored_bid = struct.unpack("<BBHIQ", trailer)

    assert ptype == PageType.NBT
    assert repeat == PageType.NBT
    assert signature == compute_sig(ib, bid)
    assert crc == compute_crc(body)
    assert stored_bid == bid


def test_btree_page_layout_matches_unicode_btp_page() -> None:
    entry = BtEntry(btkey=0x1234, child=BRef(0x55, 0x8000)).pack()
    page = pack_btree_page(
        page_type=PageType.BBT,
        ib=0x6000,
        bid=0x22,
        entries=[entry],
        entry_size=BT_ENTRY_SIZE,
        level=1,
    )

    assert len(page) == PAGE_SIZE
    assert page[:BT_ENTRY_SIZE] == entry
    assert page[BT_ENTRY_SIZE:BT_ENTRY_AREA_SIZE] == bytes(
        BT_ENTRY_AREA_SIZE - BT_ENTRY_SIZE
    )
    assert _meta(page) == (
        1,
        BT_ENTRY_AREA_SIZE // BT_ENTRY_SIZE,
        BT_ENTRY_SIZE,
        1,
    )
    assert page[492:496] == b"\x00" * 4

    ptype, repeat, signature, crc, bid = _trailer(page)
    assert ptype == repeat == PageType.BBT
    assert signature == compute_sig(0x6000, 0x22)
    assert crc == compute_crc(page[:PAGE_DATA_SIZE])
    assert bid == 0x22


def test_nbt_and_bbt_leaf_entry_binary_sizes() -> None:
    nbt = NbtEntry(
        nid=0x122,
        data_bid=0x100,
        sub_bid=0x104,
        parent_nid=0x122,
    )
    bbt = BbtEntry(
        bid=0x100,
        ib=0x8000,
        cb=512,
        c_ref=2,
    )

    assert len(nbt.pack()) == NBT_LEAF_ENTRY_SIZE
    assert struct.unpack("<QQQII", nbt.pack()) == (
        0x122,
        0x100,
        0x104,
        0x122,
        0,
    )

    assert len(bbt.pack()) == BBT_LEAF_ENTRY_SIZE
    assert struct.unpack("<QQHHI", bbt.pack()) == (
        0x100,
        0x8000,
        512,
        2,
        0,
    )


def test_bbt_rejects_oversized_block_payload() -> None:
    with pytest.raises(ValueError):
        BbtEntry(bid=4, ib=0x8000, cb=MAX_BLOCK_PAYLOAD + 1)


def test_empty_nbt_still_has_valid_leaf_root_page() -> None:
    result = build_nbt(
        [],
        offset_allocator=PageAllocator(0x6000),
        bid_allocator=PageBidAllocator(1),
    )

    assert result.height == 0
    assert len(result.pages) == 1
    root = result.pages[0]
    assert root.bref == result.root
    assert root.page_type == PageType.NBT
    assert root.level == 0
    assert root.first_key is None
    assert _meta(root.data) == (
        0,
        BT_ENTRY_AREA_SIZE // NBT_LEAF_ENTRY_SIZE,
        NBT_LEAF_ENTRY_SIZE,
        0,
    )


def test_nbt_builder_sorts_entries_and_splits_leaf_pages() -> None:
    entries = [
        NbtEntry(nid=nid, data_bid=0x1000 + nid * 4)
        for nid in range(31, 0, -1)
    ]

    result = build_nbt(
        entries,
        offset_allocator=PageAllocator(0x6000),
        bid_allocator=PageBidAllocator(0x20),
    )

    leaves = [page for page in result.pages if page.level == 0]
    root = result.page_at(result.root.ib)

    assert len(leaves) == 3
    assert result.height == 1
    assert root.level == 1
    assert _meta(root.data) == (
        3,
        BT_ENTRY_AREA_SIZE // BT_ENTRY_SIZE,
        BT_ENTRY_SIZE,
        1,
    )

    first_leaf_keys = [struct.unpack_from("<Q", page.data, 0)[0] for page in leaves]
    assert first_leaf_keys == [1, 16, 31]

    root_keys = [
        struct.unpack_from("<Q", root.data, index * BT_ENTRY_SIZE)[0]
        for index in range(3)
    ]
    assert root_keys == first_leaf_keys


def test_nbt_builder_creates_multiple_intermediate_levels() -> None:
    leaf_capacity = BT_ENTRY_AREA_SIZE // NBT_LEAF_ENTRY_SIZE
    intermediate_capacity = BT_ENTRY_AREA_SIZE // BT_ENTRY_SIZE
    entry_count = leaf_capacity * intermediate_capacity + 1

    entries = [
        NbtEntry(nid=index + 1, data_bid=0x1000 + index * 4)
        for index in range(entry_count)
    ]

    result = build_nbt(
        entries,
        offset_allocator=PageAllocator(0x8000),
        bid_allocator=PageBidAllocator(0x40),
    )

    leaf_count = math.ceil(entry_count / leaf_capacity)
    level_one_count = math.ceil(leaf_count / intermediate_capacity)

    assert leaf_count == 21
    assert level_one_count == 2
    assert result.height == 2
    assert len([page for page in result.pages if page.level == 0]) == leaf_count
    assert len([page for page in result.pages if page.level == 1]) == level_one_count
    assert len([page for page in result.pages if page.level == 2]) == 1

    root = result.page_at(result.root.ib)
    assert _meta(root.data)[0] == 2


def test_bbt_builder_splits_at_20_unicode_entries_per_leaf() -> None:
    capacity = BT_ENTRY_AREA_SIZE // BBT_LEAF_ENTRY_SIZE
    assert capacity == 20

    entries = [
        BbtEntry(
            bid=(index + 1) * 4,
            ib=0x10000 + index * 64,
            cb=32,
        )
        for index in range(41)
    ]

    result = build_bbt(
        list(reversed(entries)),
        offset_allocator=PageAllocator(0xA000),
        bid_allocator=PageBidAllocator(0x100),
    )

    leaves = [page for page in result.pages if page.level == 0]
    root = result.page_at(result.root.ib)

    assert len(leaves) == 3
    assert result.height == 1
    assert root.page_type == PageType.BBT
    assert _meta(root.data)[0] == 3

    leaf_keys = [struct.unpack_from("<Q", page.data, 0)[0] for page in leaves]
    assert leaf_keys == [4, 84, 164]


def test_btree_builder_rejects_duplicate_keys() -> None:
    entries = [
        NbtEntry(nid=0x122, data_bid=4),
        NbtEntry(nid=0x122, data_bid=8),
    ]

    with pytest.raises(ValueError, match="duplicate BTree key"):
        build_nbt(
            entries,
            offset_allocator=PageAllocator(0x6000),
            bid_allocator=PageBidAllocator(1),
        )


def test_every_btree_page_is_aligned_and_has_valid_crc() -> None:
    entries = [
        BbtEntry(bid=(index + 1) * 4, ib=0x20000 + index * 64, cb=64)
        for index in range(50)
    ]
    result = build_bbt(
        entries,
        offset_allocator=PageAllocator(0xC001),
        bid_allocator=PageBidAllocator(0x200),
    )

    seen_offsets = set()
    for page in result.pages:
        assert len(page.data) == PAGE_SIZE
        assert page.bref.ib % PAGE_SIZE == 0
        assert page.bref.ib not in seen_offsets
        seen_offsets.add(page.bref.ib)

        ptype, repeat, signature, crc, bid = _trailer(page.data)
        assert ptype == repeat == PageType.BBT
        assert bid == page.bref.bid
        assert signature == compute_sig(page.bref.ib, page.bref.bid)
        assert crc == compute_crc(page.data[:PAGE_DATA_SIZE])
