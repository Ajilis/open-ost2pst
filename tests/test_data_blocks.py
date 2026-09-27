import struct

import pytest

from open_ost2pst.pst.btree import build_bbt
from open_ost2pst.pst.pages import PageAllocator
from open_ost2pst.pst.primitives import PageBidAllocator
from open_ost2pst.pst.blocks import (
    BlockOffsetAllocator,
    BlockTrailer,
    DataBlockStore,
    pack_data_block,
    parse_block_trailer,
)
from open_ost2pst.pst.crc import compute_crc
from open_ost2pst.pst.primitives import (
    BID_INTERNAL,
    BLOCK_MAX_PAYLOAD,
    BLOCK_MAX_SIZE,
    BLOCK_TRAILER_SIZE,
    BlockBidAllocator,
    block_aligned_size,
    compute_sig,
)


def test_ms_pst_236_byte_anatomy_example() -> None:
    payload = bytes(range(236))
    ib = 0x5000
    bid = 0x100

    block = pack_data_block(payload=payload, ib=ib, bid=bid)

    assert len(block) == 256
    assert block[:236] == payload
    assert block[236:240] == b"\x00" * 4

    cb, signature, crc, stored_bid = struct.unpack(
        "<HHIQ", block[-BLOCK_TRAILER_SIZE:]
    )
    assert cb == 236
    assert signature == compute_sig(ib, bid)
    assert crc == compute_crc(payload)
    assert stored_bid == bid


def test_crc_excludes_padding() -> None:
    payload = b"A" * 49
    block = pack_data_block(payload=payload, ib=0x6000, bid=4)
    trailer = parse_block_trailer(block)

    assert len(block) == 128
    assert trailer.cb == len(payload)
    assert trailer.crc == compute_crc(payload)
    assert trailer.crc != compute_crc(block[:-BLOCK_TRAILER_SIZE])


def test_block_trailer_round_trip_fields() -> None:
    payload = b"hello PST"
    trailer = BlockTrailer.for_block(
        payload=payload,
        ib=0x8000,
        bid=0x44,
    )

    packed = trailer.pack()

    assert len(packed) == BLOCK_TRAILER_SIZE
    assert struct.unpack("<HHIQ", packed) == (
        len(payload),
        compute_sig(0x8000, 0x44),
        compute_crc(payload),
        0x44,
    )


@pytest.mark.parametrize(
    ("payload_size", "expected_size"),
    [
        (0, 64),
        (1, 64),
        (48, 64),
        (49, 128),
        (236, 256),
        (BLOCK_MAX_PAYLOAD, BLOCK_MAX_SIZE),
    ],
)
def test_data_block_sizes_are_64_byte_multiples(
    payload_size: int,
    expected_size: int,
) -> None:
    payload = b"x" * payload_size
    block = pack_data_block(
        payload=payload,
        ib=0x10000,
        bid=4,
    )

    assert len(block) == expected_size
    assert len(block) == block_aligned_size(payload_size)
    assert len(block) % 64 == 0


def test_maximum_payload_fills_an_8192_byte_block() -> None:
    payload = b"x" * BLOCK_MAX_PAYLOAD
    block = pack_data_block(payload=payload, ib=0x12000, bid=8)
    trailer = parse_block_trailer(block)

    assert len(block) == BLOCK_MAX_SIZE == 8192
    assert trailer.cb == BLOCK_MAX_PAYLOAD
    assert block[:BLOCK_MAX_PAYLOAD] == payload
    assert block[BLOCK_MAX_PAYLOAD:] == trailer.pack()


def test_payload_over_8176_requires_large_data_tree() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        pack_data_block(
            payload=b"x" * (BLOCK_MAX_PAYLOAD + 1),
            ib=0x14000,
            bid=4,
        )


def test_external_data_block_rejects_internal_bid() -> None:
    with pytest.raises(ValueError, match="external BIDs"):
        pack_data_block(
            payload=b"data",
            ib=0x16000,
            bid=4 | BID_INTERNAL,
        )


def test_data_block_requires_64_byte_aligned_ib() -> None:
    with pytest.raises(ValueError, match="aligned"):
        pack_data_block(payload=b"data", ib=0x16001, bid=4)


def test_block_offset_allocator_aligns_start_and_advances_by_footprint() -> None:
    allocator = BlockOffsetAllocator(next_ib=0x5001)

    first = allocator.allocate(236)
    second = allocator.allocate(49)
    third = allocator.allocate(BLOCK_MAX_PAYLOAD)

    assert first == 0x5040
    assert second == 0x5140
    assert third == 0x51C0
    assert allocator.next_ib == 0x71C0


def test_data_block_store_generates_bbt_entries_automatically() -> None:
    store = DataBlockStore(
        offset_allocator=BlockOffsetAllocator(0x8000),
        bid_allocator=BlockBidAllocator(4),
    )

    first = store.add(b"alpha")
    second = store.add(b"beta" * 20, c_ref=3)

    assert first.bref.bid == 4
    assert second.bref.bid == 8
    assert first.bref.ib == 0x8000
    assert second.bref.ib == 0x8040

    assert first.bbt_entry.bid == first.bref.bid
    assert first.bbt_entry.ib == first.bref.ib
    assert first.bbt_entry.cb == 5
    assert first.bbt_entry.c_ref == 1

    assert second.bbt_entry.bid == second.bref.bid
    assert second.bbt_entry.ib == second.bref.ib
    assert second.bbt_entry.cb == 80
    assert second.bbt_entry.c_ref == 3

    assert store.bbt_entries == (first.bbt_entry, second.bbt_entry)
    assert store.blocks == (first, second)


def test_store_extend_preserves_order_and_unique_bids() -> None:
    store = DataBlockStore(
        offset_allocator=BlockOffsetAllocator(0xA000),
        bid_allocator=BlockBidAllocator(0x20),
    )

    blocks = store.extend([b"a", b"bb", b"ccc"])

    assert [block.bref.bid for block in blocks] == [0x20, 0x24, 0x28]
    assert [block.payload_size for block in blocks] == [1, 2, 3]
    assert [entry.bid for entry in store.bbt_entries] == [0x20, 0x24, 0x28]


def test_store_rejects_large_payload_until_xblock_support_exists() -> None:
    store = DataBlockStore(
        offset_allocator=BlockOffsetAllocator(0xC000),
        bid_allocator=BlockBidAllocator(4),
    )

    with pytest.raises(ValueError, match="XBLOCK/XXBLOCK"):
        store.add(b"x" * (BLOCK_MAX_PAYLOAD + 1))


def test_parse_block_trailer_rejects_non_aligned_input() -> None:
    with pytest.raises(ValueError, match="multiple of 64"):
        parse_block_trailer(b"x" * 65)


def test_store_bbt_entries_feed_existing_bbt_builder() -> None:
    store = DataBlockStore(
        offset_allocator=BlockOffsetAllocator(0x10000),
        bid_allocator=BlockBidAllocator(4),
    )
    store.extend([b"alpha", b"beta", b"gamma"])

    result = build_bbt(
        store.bbt_entries,
        offset_allocator=PageAllocator(0x20000),
        bid_allocator=PageBidAllocator(0x100),
    )

    assert result.height == 0
    assert len(result.pages) == 1
    assert [offset for offset, _data in store.chunks] == [
        block.bref.ib for block in store.blocks
    ]
    assert [entry.bid for entry in store.bbt_entries] == [4, 8, 12]
