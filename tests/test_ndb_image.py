import struct

from open_ost2pst.pst.amap import AMAP_FIRST_OFFSET
from open_ost2pst.pst.crc import compute_crc
from open_ost2pst.pst.image import NdbImageBuilder, build_minimal_ndb
from open_ost2pst.pst.ndb import (
    HEADER_FULL_CRC_LENGTH,
    HEADER_FULL_CRC_OFFSET,
    HEADER_PARTIAL_CRC_LENGTH,
    HEADER_PARTIAL_CRC_OFFSET,
    OFFSET_BID_NEXT_B,
    OFFSET_BID_NEXT_P,
    OFFSET_ROOT,
    ROOT_SIZE,
    Root,
    VALID_AMAP,
)
from open_ost2pst.pst.pages import PAGE_DATA_SIZE, PageType
from open_ost2pst.pst.primitives import PAGE_SIZE


def test_minimal_ndb_assembles_header_amap_block_nbt_and_bbt() -> None:
    result = build_minimal_ndb()
    image = result.data

    assert image[:4] == b"!BDN"
    assert len(image) == result.header.root.file_eof
    assert len(image) == result.amap.file_eof

    root = Root.unpack(image[OFFSET_ROOT : OFFSET_ROOT + ROOT_SIZE])
    assert root.amap_last == AMAP_FIRST_OFFSET
    assert root.amap_valid == VALID_AMAP
    assert root.nbt_root == result.nbt.root
    assert root.bbt_root == result.bbt.root
    assert root.file_eof == len(image)

    assert len(result.blocks) == 1
    block = result.blocks[0]
    assert image[block.bref.ib : block.bref.ib + len(block.data)] == block.data

    nbt_root = result.nbt.page_at(root.nbt_root.ib)
    bbt_root = result.bbt.page_at(root.bbt_root.ib)
    assert image[root.nbt_root.ib : root.nbt_root.ib + PAGE_SIZE] == nbt_root.data
    assert image[root.bbt_root.ib : root.bbt_root.ib + PAGE_SIZE] == bbt_root.data

    assert image[AMAP_FIRST_OFFSET : AMAP_FIRST_OFFSET + PAGE_SIZE] == (
        result.amap.images[0].data
    )


def test_built_header_counters_point_after_allocated_ids() -> None:
    result = build_minimal_ndb()
    image = result.data

    stored_next_p = struct.unpack_from("<Q", image, OFFSET_BID_NEXT_P)[0]
    stored_next_b = struct.unpack_from("<Q", image, OFFSET_BID_NEXT_B)[0]

    assert stored_next_p == 3
    assert stored_next_b == 8
    assert stored_next_p == result.header.bid_next_p
    assert stored_next_b == result.header.bid_next_b


def test_built_header_crcs_are_valid_after_root_is_finalized() -> None:
    image = build_minimal_ndb().data

    partial = struct.unpack_from("<I", image, HEADER_PARTIAL_CRC_OFFSET)[0]
    full = struct.unpack_from("<I", image, HEADER_FULL_CRC_OFFSET)[0]

    assert partial == compute_crc(image[8 : 8 + HEADER_PARTIAL_CRC_LENGTH])
    assert full == compute_crc(image[8 : 8 + HEADER_FULL_CRC_LENGTH])


def test_btree_root_page_trailers_reference_header_brefs() -> None:
    result = build_minimal_ndb()

    for tree, expected_type in (
        (result.nbt, PageType.NBT),
        (result.bbt, PageType.BBT),
    ):
        page = tree.page_at(tree.root.ib)
        ptype, repeat, _sig, crc, bid = struct.unpack(
            "<BBHIQ", page.data[PAGE_DATA_SIZE:]
        )
        assert ptype == repeat == expected_type
        assert bid == tree.root.bid
        assert crc == compute_crc(page.data[:PAGE_DATA_SIZE])


def test_amap_marks_all_generated_blocks_and_pages_allocated() -> None:
    result = build_minimal_ndb()

    for block in result.blocks:
        for ib in range(block.bref.ib, block.bref.ib + len(block.data), 64):
            assert result.amap.is_allocated(ib)

    for page in (*result.nbt.pages, *result.bbt.pages):
        for ib in range(page.bref.ib, page.bref.ib + PAGE_SIZE, 64):
            assert result.amap.is_allocated(ib)


def test_builder_supports_multiple_nodes_and_bbt_records() -> None:
    builder = NdbImageBuilder()
    first = builder.add_block(b"one")
    second = builder.add_block(b"two" * 30)
    builder.add_node(0x21, first.bref.bid)
    builder.add_node(0x122, second.bref.bid, parent_nid=0x122)

    result = builder.build()

    assert len(result.blocks) == 2
    assert len(builder.nodes) == 2
    assert result.nbt.root.ib != result.bbt.root.ib
    assert [entry.bid for entry in builder.bbt_entries] == [4, 8]
