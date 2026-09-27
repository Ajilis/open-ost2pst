import struct

import pytest

from open_ost2pst.pst.amap import AmapAllocator
from open_ost2pst.pst.blocks import DataBlockStore
from open_ost2pst.pst.image import NdbImageBuilder
from open_ost2pst.pst.primitives import BID_INTERNAL, BlockBidAllocator
from open_ost2pst.pst.subnodes import (
    SIBLOCK_LEVEL_INTERMEDIATE,
    SIBLOCK_MAX_ENTRIES,
    SLBLOCK_LEVEL_LEAF,
    SLBLOCK_MAX_ENTRIES,
    SUBNODE_BLOCK_TYPE,
    SUBNODE_TREE_MAX_ENTRIES,
    SubnodeEntry,
    SubnodeIntermediateEntry,
    pack_siblock,
    pack_slblock,
    parse_siblock,
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
    assert btype == SUBNODE_BLOCK_TYPE
    assert level == SLBLOCK_LEVEL_LEAF
    assert count == 2
    assert padding == 0

    entries = parse_slblock(payload)
    assert [entry.nid for entry in entries] == [0x405, 0x692]
    assert [entry.data_bid for entry in entries] == [0x10, 0x20]


def test_siblock_binary_layout_and_sorting() -> None:
    payload = pack_siblock(
        [
            SubnodeIntermediateEntry(nid=0x900, bid=0x0E),
            SubnodeIntermediateEntry(nid=0x100, bid=0x0A),
        ]
    )

    btype, level, count, padding = struct.unpack_from("<BBHI", payload, 0)
    assert btype == SUBNODE_BLOCK_TYPE
    assert level == SIBLOCK_LEVEL_INTERMEDIATE
    assert count == 2
    assert padding == 0

    entries = parse_siblock(payload)
    assert [entry.nid for entry in entries] == [0x100, 0x900]
    assert [entry.bid for entry in entries] == [0x0A, 0x0E]


def test_unicode_subnode_capacities_match_block_payload() -> None:
    assert SLBLOCK_MAX_ENTRIES == 340
    assert SIBLOCK_MAX_ENTRIES == 510
    assert SUBNODE_TREE_MAX_ENTRIES == 173_400


def test_sientry_requires_internal_child_bid() -> None:
    with pytest.raises(ValueError, match="internal SLBLOCK"):
        SubnodeIntermediateEntry(nid=1, bid=4)


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


def test_subnode_tree_over_leaf_capacity_builds_siblock_root() -> None:
    builder = NdbImageBuilder()
    subnodes = {}

    for nid in range(1, SLBLOCK_MAX_ENTRIES + 3):
        subnodes[nid] = builder.add_block(bytes([nid & 0xFF])).bref.bid

    root_bid = builder.add_subnode_tree(subnodes)

    blocks = {block.bref.bid: block for block in builder.blocks}
    root = blocks[root_bid]
    assert root.internal is True

    root_payload = root.data[: root.payload_size]
    root_entries = parse_siblock(root_payload)

    assert len(root_entries) == 2
    assert [entry.nid for entry in root_entries] == [1, 341]

    first_leaf = blocks[root_entries[0].bid]
    second_leaf = blocks[root_entries[1].bid]

    first_entries = parse_slblock(
        first_leaf.data[: first_leaf.payload_size]
    )
    second_entries = parse_slblock(
        second_leaf.data[: second_leaf.payload_size]
    )

    assert len(first_entries) == 340
    assert len(second_entries) == 2
    assert first_entries[0].nid == 1
    assert first_entries[-1].nid == 340
    assert second_entries[0].nid == 341
    assert second_entries[-1].nid == 342


def test_subnode_tree_at_leaf_capacity_stays_single_slblock() -> None:
    builder = NdbImageBuilder()
    subnodes = {}

    for nid in range(1, SLBLOCK_MAX_ENTRIES + 1):
        subnodes[nid] = builder.add_block(b"x").bref.bid

    root_bid = builder.add_subnode_tree(subnodes)
    root = next(block for block in builder.blocks if block.bref.bid == root_bid)

    entries = parse_slblock(root.data[: root.payload_size])
    assert len(entries) == SLBLOCK_MAX_ENTRIES


def test_subnode_tree_rejects_more_than_one_siblock_level() -> None:
    entries = (
        SubnodeEntry(nid=index + 1, data_bid=4)
        for index in range(SUBNODE_TREE_MAX_ENTRIES + 1)
    )

    from open_ost2pst.pst.subnodes import split_slblock_entries

    with pytest.raises(ValueError, match="exceeds one SIBLOCK level"):
        split_slblock_entries(entries)
