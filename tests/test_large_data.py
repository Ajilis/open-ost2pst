import struct

from open_ost2pst.binary_payload import TemporaryBinaryPayload
from open_ost2pst.pst.amap import AmapAllocator
from open_ost2pst.pst.blocks import DataBlockStore
from open_ost2pst.pst.large_data import (
    XBLOCK_LEVEL,
    XBLOCK_MAX_ENTRIES,
    XXBLOCK_LEVEL,
    pack_xblock,
    parse_xblock,
    store_block_sequence,
    store_data_stream,
)
from open_ost2pst.pst.primitives import (
    BID_INTERNAL,
    BLOCK_MAX_PAYLOAD,
    BlockBidAllocator,
)


def _store() -> DataBlockStore:
    return DataBlockStore(
        offset_allocator=AmapAllocator().block_allocator(),
        bid_allocator=BlockBidAllocator(4),
    )


def test_xblock_binary_layout() -> None:
    bids = [4, 8, 12]
    payload = pack_xblock(
        bids,
        total_size=12345,
        level=XBLOCK_LEVEL,
    )

    assert struct.unpack_from("<BBHI", payload, 0) == (
        0x01,
        XBLOCK_LEVEL,
        3,
        12345,
    )
    assert struct.unpack_from("<3Q", payload, 8) == tuple(bids)
    assert parse_xblock(payload) == (
        XBLOCK_LEVEL,
        12345,
        tuple(bids),
    )


def test_large_stream_uses_xblock() -> None:
    store = _store()
    payload = b"A" * (BLOCK_MAX_PAYLOAD * 2 + 123)

    tree = store_data_stream(store, payload)

    assert tree.logical_size == len(payload)
    assert len(tree.data_blocks) == 3
    assert len(tree.index_blocks) == 1
    assert tree.root_bid & BID_INTERNAL

    level, total, bids = parse_xblock(
        tree.index_blocks[0].data[: tree.index_blocks[0].payload_size]
    )
    assert level == XBLOCK_LEVEL
    assert total == len(payload)
    assert bids == tuple(block.bref.bid for block in tree.data_blocks)


def test_more_than_1021_data_blocks_uses_xxblock() -> None:
    store = _store()
    payloads = [bytes([index & 0xFF]) for index in range(XBLOCK_MAX_ENTRIES + 1)]

    tree = store_block_sequence(store, payloads)

    assert len(tree.data_blocks) == XBLOCK_MAX_ENTRIES + 1
    assert len(tree.index_blocks) == 3
    assert tree.uses_xxblock is True

    first_level, first_total, first_bids = parse_xblock(
        tree.index_blocks[0].data[: tree.index_blocks[0].payload_size]
    )
    second_level, second_total, second_bids = parse_xblock(
        tree.index_blocks[1].data[: tree.index_blocks[1].payload_size]
    )
    root_level, root_total, root_bids = parse_xblock(
        tree.index_blocks[2].data[: tree.index_blocks[2].payload_size]
    )

    assert first_level == second_level == XBLOCK_LEVEL
    assert len(first_bids) == XBLOCK_MAX_ENTRIES
    assert len(second_bids) == 1
    assert first_total == XBLOCK_MAX_ENTRIES
    assert second_total == 1

    assert root_level == XXBLOCK_LEVEL
    assert root_total == XBLOCK_MAX_ENTRIES + 1
    assert root_bids == (
        tree.index_blocks[0].bref.bid,
        tree.index_blocks[1].bref.bid,
    )


def test_temporary_payload_streams_into_xblock() -> None:
    store = _store()
    raw = b"S" * (BLOCK_MAX_PAYLOAD * 3 + 17)
    payload = TemporaryBinaryPayload.from_chunks(
        [
            raw[:5000],
            raw[5000:15000],
            raw[15000:],
        ],
        max_bytes=len(raw),
    )

    try:
        tree = store_data_stream(store, payload)
    finally:
        payload.close()

    assert tree.logical_size == len(raw)
    assert len(tree.data_blocks) == 4
    assert tree.uses_xblock is True

    reconstructed = b"".join(
        block.data[: block.payload_size]
        for block in tree.data_blocks
    )
    assert reconstructed == raw
