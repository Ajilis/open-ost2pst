import math
import struct

import pytest

from open_ost2pst.pst.image import NdbImageBuilder
from open_ost2pst.pst.ltp.bth import BthHeader
from open_ost2pst.pst.ltp.heap import (
    HID_NULL,
    hid_block_index,
    hid_index,
    parse_page_map,
)
from open_ost2pst.pst.ltp.pc import (
    PropertyContext,
    PropertyType,
)


def _entry_by_id(image, property_id):
    return next(entry for entry in image.entries if entry.property_id == property_id)


def _resolve_hid(image, hid):
    block_index = hid_block_index(hid)
    allocation_index = hid_index(hid)
    block = image.heap.blocks[block_index].data
    c_alloc, _c_free, offsets = parse_page_map(block)
    assert 1 <= allocation_index <= c_alloc
    start = offsets[allocation_index - 1]
    end = offsets[allocation_index]
    return block[start:end]


def test_pc_fixed_values_are_stored_inline() -> None:
    pc = PropertyContext()
    pc.set_integer16(0x1001, -7)
    pc.set_integer32(0x1002, -1)
    pc.set_boolean(0x1003, True)
    pc.set_float32(0x1004, 1.5)

    image = pc.build()

    assert image.heap.client_signature == 0xBC
    assert image.bth.record_count == 4
    assert image.bth.index_levels == 0
    assert image.heap.user_root == image.bth.header_hid

    assert _entry_by_id(image, 0x1001).property_type == PropertyType.INTEGER16
    assert _entry_by_id(image, 0x1001).hnid == 0x0000FFF9
    assert _entry_by_id(image, 0x1002).hnid == 0xFFFFFFFF
    assert _entry_by_id(image, 0x1003).hnid == 1

    float_bits = struct.unpack("<I", struct.pack("<f", 1.5))[0]
    assert _entry_by_id(image, 0x1004).hnid == float_bits


def test_pc_variable_values_are_hid_backed() -> None:
    pc = PropertyContext()
    pc.set_unicode(0x3001, "Open OST2PST Store")
    pc.set_binary(0x0FF9, b"record-key")
    pc.set_integer64(0x1005, -123456789)
    pc.set_float64(0x1006, math.pi)
    pc.set_filetime(0x3007, 132537600000000000)
    pc.set_guid(0x1008, bytes(range(16)))

    image = pc.build()

    display = _entry_by_id(image, 0x3001)
    record_key = _entry_by_id(image, 0x0FF9)
    integer64 = _entry_by_id(image, 0x1005)
    float64 = _entry_by_id(image, 0x1006)
    systime = _entry_by_id(image, 0x3007)
    guid = _entry_by_id(image, 0x1008)

    assert display.property_type == PropertyType.UNICODE
    assert _resolve_hid(image, display.hnid) == (
        "Open OST2PST Store".encode("utf-16-le") + b"\x00\x00"
    )
    assert _resolve_hid(image, record_key.hnid) == b"record-key"
    assert struct.unpack("<q", _resolve_hid(image, integer64.hnid))[0] == -123456789
    assert struct.unpack("<d", _resolve_hid(image, float64.hnid))[0] == pytest.approx(math.pi)
    assert struct.unpack("<Q", _resolve_hid(image, systime.hnid))[0] == 132537600000000000
    assert _resolve_hid(image, guid.hnid) == bytes(range(16))


def test_pc_unicode_is_null_terminated_utf16le() -> None:
    pc = PropertyContext()
    pc.set_unicode(0x3001, "é")

    image = pc.build()
    entry = image.entries[0]

    assert _resolve_hid(image, entry.hnid) == b"\xe9\x00\x00\x00"


def test_pc_string8_is_null_terminated() -> None:
    pc = PropertyContext()
    pc.set_string8(0x3001, "café")

    image = pc.build()
    entry = image.entries[0]

    assert entry.property_type == PropertyType.STRING8
    assert _resolve_hid(image, entry.hnid) == b"caf\xe9\x00"


def test_pc_entries_are_sorted_by_property_id_in_bth() -> None:
    pc = PropertyContext()
    pc.set_integer32(0x4000, 4)
    pc.set_integer32(0x1000, 1)
    pc.set_integer32(0x3000, 3)
    pc.set_integer32(0x2000, 2)

    image = pc.build()

    assert [entry.property_id for entry in image.entries] == [
        0x1000,
        0x2000,
        0x3000,
        0x4000,
    ]

    header_data = _resolve_hid(image, image.bth.header_hid)
    header = BthHeader.unpack(header_data)
    assert header.cb_key == 2
    assert header.cb_ent == 6
    assert header.index_levels == 0
    assert header.root_hid == image.bth.root_hid

    leaf = _resolve_hid(image, image.bth.root_hid)
    keys = [
        struct.unpack_from("<H", leaf, offset)[0]
        for offset in range(0, len(leaf), 8)
    ]
    assert keys == [0x1000, 0x2000, 0x3000, 0x4000]


def test_pc_property_replacement_and_delete() -> None:
    pc = PropertyContext()
    pc.set_integer32(0x1000, 1)
    pc.set_integer32(0x1000, 2)

    assert pc.property_count == 1
    assert pc.property_ids == (0x1000,)
    assert _entry_by_id(pc.build(), 0x1000).hnid == 2

    pc.delete(0x1000)
    assert pc.property_count == 0
    assert pc.property_ids == ()


def test_empty_pc_has_bth_header_with_null_root() -> None:
    pc = PropertyContext()
    image = pc.build()

    assert image.bth.record_count == 0
    assert image.bth.root_hid == HID_NULL
    assert image.heap.user_root == image.bth.header_hid

    header = BthHeader.unpack(_resolve_hid(image, image.bth.header_hid))
    assert header.root_hid == HID_NULL


def test_pc_rejects_variable_value_larger_than_one_hn_allocation() -> None:
    pc = PropertyContext()
    pc.set_binary(0x3701, b"x" * 3581)

    with pytest.raises(ValueError, match="subnode storage"):
        pc.build()


def test_pc_rejects_empty_binary_until_zero_length_hnid_is_supported() -> None:
    pc = PropertyContext()

    with pytest.raises(ValueError, match="empty PT_BINARY"):
        pc.set_binary(0x3701, b"")


def test_pc_can_be_embedded_as_message_store_ndb_node() -> None:
    pc = PropertyContext()
    pc.set_unicode(0x3001, "Open OST2PST Store")
    pc.set_integer32(0x340D, 0)

    builder = NdbImageBuilder()
    node = builder.add_property_context(0x21, pc)
    result = builder.build()

    assert node.nid == 0x21
    assert node.data_bid == result.blocks[0].bref.bid
    assert result.blocks[0].data[2] == 0xEC
    assert result.blocks[0].data[3] == 0xBC


def test_pc_multi_block_embedding_waits_for_xblock_support() -> None:
    pc = PropertyContext()
    # Many small binary values create enough heap allocations/BTH nodes
    # to force the PC over one HN block.
    for index in range(800):
        pc.set_binary(0x8000 + index, b"x" * 8)

    builder = NdbImageBuilder()

    with pytest.raises(ValueError, match="XBLOCK/XXBLOCK"):
        builder.add_property_context(0x21, pc)
