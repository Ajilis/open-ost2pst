import struct

from open_ost2pst.pst.blocks import DataBlockStore
from open_ost2pst.pst.amap import AmapAllocator
from open_ost2pst.pst.primitives import BID_INTERNAL, BlockBidAllocator
from open_ost2pst.pst.subnodes import (
    SLBLOCK_TYPE,
    SubnodeEntry,
    pack_slblock,
    parse_slblock,
)


def test_slblock_binary_layout_and_sorting() -> None:
    payload = pack_slblock(
        [
            SubnodeEntry(nid=0x692, data_bid=0x20),
            SubnodeEntry(nid=0x405, data_bid=0x10),
        ]
    )

    btype, level, count, padding = struct.unpack_from("<BBHI", payload, 0)
    assert btype == SLBLOCK_TYPE
    assert level == 0
    assert count == 2
    assert padding == 0

    entries = parse_slblock(payload)
    assert [entry.nid for entry in entries] == [0x405, 0x692]
    assert [entry.data_bid for entry in entries] == [0x10, 0x20]


def test_internal_block_has_internal_bid_and_bbt_entry() -> None:
    store = DataBlockStore(
        offset_allocator=AmapAllocator().block_allocator(),
        bid_allocator=BlockBidAllocator(4),
    )

    block = store.add_internal(b"internal")

    assert block.internal is True
    assert block.bref.bid & BID_INTERNAL
    assert block.bbt_entry.bid == block.bref.bid
    assert block.bbt_entry.cb == len(b"internal")
