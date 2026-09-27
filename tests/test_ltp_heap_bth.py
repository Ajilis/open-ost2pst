import struct

import pytest

from open_ost2pst.pst.ltp.bth import (
    BTH_TYPE,
    BthHeader,
    build_bth,
    parse_index_records,
    parse_leaf_records,
)
from open_ost2pst.pst.ltp.heap import (
    HID_NULL,
    HN_BITMAP_HEADER_SIZE,
    HN_HEADER_SIZE,
    HN_PAGE_HEADER_SIZE,
    HN_SIGNATURE,
    MAX_HEAP_ALLOCATION,
    HeapClientSignature,
    HeapId,
    HeapNode,
    HeapOverflowError,
    hid_block_index,
    hid_index,
    make_hid,
    parse_page_map,
)


def test_hid_layout_round_trip() -> None:
    hid = make_hid(3, 2)

    assert hid == 0x00020060
    assert hid_index(hid) == 3
    assert hid_block_index(hid) == 2
    assert HeapId.from_value(hid).value == hid


@pytest.mark.parametrize("value", [1, 0x1F, 0x00010001])
def test_hid_rejects_nonzero_type_bits(value: int) -> None:
    with pytest.raises(ValueError, match="type bits"):
        HeapId.from_value(value)


def test_single_block_hn_header_and_page_map() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)
    hid = heap.allocate(b"abc")
    heap.set_user_root(hid)

    block = heap.serialize()

    ib_hnpm, signature, client_sig, root_hid = struct.unpack_from(
        "<HBBI", block, 0
    )
    assert ib_hnpm == 16
    assert signature == HN_SIGNATURE
    assert client_sig == HeapClientSignature.PROPERTY_CONTEXT
    assert root_hid == 0x20

    c_alloc, c_free, offsets = parse_page_map(block)
    assert c_alloc == 1
    assert c_free == 0
    assert offsets == (HN_HEADER_SIZE, HN_HEADER_SIZE + 3)

    # HNPAGEMAP is word-aligned even though the allocation ended at offset 15.
    assert ib_hnpm % 2 == 0
    assert block[HN_HEADER_SIZE:HN_HEADER_SIZE + 3] == b"abc"
    assert block[15] == 0


def test_empty_hn_has_valid_page_map() -> None:
    heap = HeapNode(HeapClientSignature.BTH)
    block = heap.serialize()

    ib_hnpm = struct.unpack_from("<H", block, 0)[0]
    assert ib_hnpm == HN_HEADER_SIZE

    c_alloc, c_free, offsets = parse_page_map(block)
    assert c_alloc == 0
    assert c_free == 0
    assert offsets == (HN_HEADER_SIZE,)


def test_heap_allocation_maximum_is_3580_bytes() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)

    hid = heap.allocate(b"x" * MAX_HEAP_ALLOCATION)
    assert hid == 0x20
    assert heap.get_allocation(hid) == b"x" * MAX_HEAP_ALLOCATION

    with pytest.raises(HeapOverflowError, match="3580"):
        heap.allocate(b"x" * (MAX_HEAP_ALLOCATION + 1))


def test_heap_spills_to_next_block_and_hid_encodes_block_index() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)

    first = heap.allocate(b"a" * 3580)
    second = heap.allocate(b"b" * 3580)
    third = heap.allocate(b"c" * 3580)

    assert hid_block_index(first) == 0
    assert hid_block_index(second) == 0
    assert hid_block_index(third) == 1
    assert hid_index(third) == 1
    assert heap.block_count == 2

    image = heap.build()
    assert len(image.blocks) == 2

    c_alloc0, _, offsets0 = parse_page_map(image.blocks[0].data)
    c_alloc1, _, offsets1 = parse_page_map(image.blocks[1].data)
    assert c_alloc0 == 2
    assert c_alloc1 == 1
    assert offsets0[0] == HN_HEADER_SIZE
    assert offsets1[0] == HN_PAGE_HEADER_SIZE


def test_block_8_uses_hn_bitmap_header_and_block_16_does_not() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)

    # Two 3580-byte allocations fit per ordinary HN block. 34 allocations
    # force 17 blocks, enough to inspect blocks 8 and 16.
    for _ in range(34):
        heap.allocate(b"x" * 3580)

    image = heap.build()
    assert len(image.blocks) == 17

    _, _, offsets8 = parse_page_map(image.blocks[8].data)
    _, _, offsets16 = parse_page_map(image.blocks[16].data)

    assert offsets8[0] == HN_BITMAP_HEADER_SIZE
    assert offsets16[0] == HN_PAGE_HEADER_SIZE
    assert len(image.blocks[8].data) <= 8176
    assert len(image.blocks[16].data) <= 8176


def test_fill_level_map_tracks_first_blocks() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)
    heap.allocate(b"a" * 3580)
    heap.allocate(b"b" * 3580)
    heap.allocate(b"c" * 3580)

    image = heap.build()
    block0 = image.blocks[0].data

    # First block is fairly full, second has substantial free space.
    first_level = block0[8] & 0x0F
    second_level = (block0[8] >> 4) & 0x0F

    assert first_level > second_level
    assert first_level != 0


def test_bth_header_round_trip() -> None:
    header = BthHeader(
        cb_key=2,
        cb_ent=6,
        index_levels=1,
        root_hid=0x40,
    )

    packed = header.pack()

    assert packed == struct.pack("<BBBBI", BTH_TYPE, 2, 6, 1, 0x40)
    assert BthHeader.unpack(packed) == header


@pytest.mark.parametrize("cb_key", [1, 3, 5, 32])
def test_bth_rejects_invalid_key_width(cb_key: int) -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)

    with pytest.raises(ValueError, match="key size"):
        build_bth(heap, cb_key=cb_key, cb_ent=6, records=[])


def test_empty_bth_has_null_root_and_header_as_user_root() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)

    result = build_bth(heap, cb_key=2, cb_ent=6, records=[])

    assert result.root_hid == HID_NULL
    assert result.index_levels == 0
    assert result.header_hid == 0x20
    assert heap.user_root == result.header_hid

    header = BthHeader.unpack(heap.get_allocation(result.header_hid))
    assert header.root_hid == HID_NULL


def test_bth_leaf_records_sort_by_little_endian_numeric_key() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)
    records = [
        (b"\x00\x01", b"A" * 6),  # numeric key 256
        (b"\xff\x00", b"B" * 6),  # numeric key 255
        (b"\x01\x00", b"C" * 6),  # numeric key 1
    ]

    result = build_bth(
        heap,
        cb_key=2,
        cb_ent=6,
        records=records,
    )

    header = BthHeader.unpack(heap.get_allocation(result.header_hid))
    assert header.index_levels == 0
    assert header.root_hid == result.root_hid

    parsed = parse_leaf_records(
        heap.get_allocation(result.root_hid),
        cb_key=2,
        cb_ent=6,
    )
    assert [int.from_bytes(key, "little") for key, _ in parsed] == [1, 255, 256]


def test_bth_builds_intermediate_index_when_leaf_capacity_is_exceeded() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)
    records = [
        (
            index.to_bytes(2, "little"),
            (index * 3).to_bytes(6, "little"),
        )
        for index in range(448)
    ]

    result = build_bth(
        heap,
        cb_key=2,
        cb_ent=6,
        records=reversed(records),
    )

    assert result.record_count == 448
    assert result.index_levels == 1

    header = BthHeader.unpack(heap.get_allocation(result.header_hid))
    assert header.index_levels == 1
    assert header.root_hid == result.root_hid

    index_records = parse_index_records(
        heap.get_allocation(result.root_hid),
        cb_key=2,
    )
    assert len(index_records) == 2
    assert [int.from_bytes(key, "little") for key, _ in index_records] == [0, 447]

    first_leaf = parse_leaf_records(
        heap.get_allocation(index_records[0][1]),
        cb_key=2,
        cb_ent=6,
    )
    second_leaf = parse_leaf_records(
        heap.get_allocation(index_records[1][1]),
        cb_key=2,
        cb_ent=6,
    )
    assert len(first_leaf) == 447
    assert len(second_leaf) == 1


def test_bth_rejects_duplicate_keys() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)

    with pytest.raises(ValueError, match="duplicate BTH key"):
        build_bth(
            heap,
            cb_key=2,
            cb_ent=1,
            records=[
                (b"\x01\x00", b"a"),
                (b"\x01\x00", b"b"),
            ],
        )


def test_bth_validates_key_and_entry_widths() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)

    with pytest.raises(ValueError, match="wrong width"):
        build_bth(
            heap,
            cb_key=2,
            cb_ent=6,
            records=[(b"\x01", b"x" * 6)],
        )

    with pytest.raises(ValueError, match="wrong width"):
        build_bth(
            heap,
            cb_key=2,
            cb_ent=6,
            records=[(b"\x01\x00", b"x" * 5)],
        )


def test_bth_can_span_multiple_hn_blocks() -> None:
    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)
    records = [
        (
            index.to_bytes(2, "little"),
            (index * 7).to_bytes(6, "little"),
        )
        for index in range(1500)
    ]

    result = build_bth(
        heap,
        cb_key=2,
        cb_ent=6,
        records=records,
    )

    assert result.index_levels == 1
    assert heap.block_count >= 2
    assert hid_block_index(result.header_hid) >= 1

    header = BthHeader.unpack(heap.get_allocation(result.header_hid))
    assert header.root_hid == result.root_hid
    assert heap.get_allocation(result.root_hid)


def test_single_block_heap_can_be_embedded_in_ndb_builder() -> None:
    from open_ost2pst.pst.image import NdbImageBuilder

    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)
    build_bth(
        heap,
        cb_key=2,
        cb_ent=6,
        records=[(b"\x01\x00", b"x" * 6)],
    )

    builder = NdbImageBuilder()
    node = builder.add_heap_node(0x21, heap)
    result = builder.build()

    assert node.data_bid == result.blocks[0].bref.bid
    assert result.blocks[0].data.startswith(
        struct.pack("<HBB", struct.unpack_from("<H", result.blocks[0].data, 0)[0], HN_SIGNATURE, HeapClientSignature.PROPERTY_CONTEXT)
    )


def test_multi_block_heap_requires_ndb_data_tree_support() -> None:
    from open_ost2pst.pst.image import NdbImageBuilder

    heap = HeapNode(HeapClientSignature.PROPERTY_CONTEXT)
    for _ in range(3):
        heap.allocate(b"x" * 3580)

    builder = NdbImageBuilder()
    with pytest.raises(ValueError, match="XBLOCK/XXBLOCK"):
        builder.add_heap_node(0x21, heap)
