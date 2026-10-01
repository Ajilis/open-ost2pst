import struct

import pytest

from open_ost2pst.pst.image import NdbImageBuilder
from open_ost2pst.pst.ltp.bth import BthHeader, parse_leaf_records
from open_ost2pst.pst.ltp.heap import HeapClientSignature
from open_ost2pst.pst.ltp.pc import PropertyType
from open_ost2pst.pst.primitives import BLOCK_MAX_PAYLOAD
from open_ost2pst.pst.ltp.tc import (
    PID_LTP_ROW_ID,
    PID_LTP_ROW_VER,
    TC_TYPE,
    TableContext,
    parse_row_index_header,
    parse_tcinfo,
    read_heap_allocation,
)


def _column(columns, property_id):
    return next(column for column in columns if column.property_id == property_id)


def test_tc_starts_with_mandatory_row_columns() -> None:
    table = TableContext()

    assert table.column_count == 2
    image = table.build()

    (
        c_cols,
        rgib,
        hid_row_index,
        hnid_rows,
        hid_index,
        columns,
    ) = parse_tcinfo(image.heap, image.tcinfo_hid)

    assert c_cols == 2
    assert rgib == (8, 8, 8, 9)
    assert hnid_rows == 0
    assert hid_index == 0

    row_id = _column(columns, PID_LTP_ROW_ID)
    row_ver = _column(columns, PID_LTP_ROW_VER)

    assert row_id.ib_data == 0
    assert row_id.cb_data == 4
    assert row_id.bit_index == 0
    assert row_ver.ib_data == 4
    assert row_ver.cb_data == 4
    assert row_ver.bit_index == 1

    header = parse_row_index_header(image.heap, hid_row_index)
    assert header.cb_key == 4
    assert header.cb_ent == 4
    assert header.root_hid == 0


def test_tc_layout_groups_8_4_then_2_then_1_byte_cells() -> None:
    table = TableContext()
    table.add_column(0x3001, PropertyType.UNICODE)
    table.add_column(0x3008, PropertyType.SYSTIME)
    table.add_column(0x3400, PropertyType.INTEGER16)
    table.add_column(0x3602, PropertyType.INTEGER32)
    table.add_column(0x360A, PropertyType.BOOLEAN)

    image = table.build()
    layout = image.layout

    assert layout.tci_4b == 24
    assert layout.tci_2b == 26
    assert layout.tci_1b == 27
    assert layout.ceb_size == 1
    assert layout.tci_bm == 28

    row_id = _column(layout.descriptors, PID_LTP_ROW_ID)
    row_ver = _column(layout.descriptors, PID_LTP_ROW_VER)
    display = _column(layout.descriptors, 0x3001)
    systime = _column(layout.descriptors, 0x3008)
    short = _column(layout.descriptors, 0x3400)
    count = _column(layout.descriptors, 0x3602)
    boolean = _column(layout.descriptors, 0x360A)

    assert row_id.ib_data == 0
    assert row_ver.ib_data == 4
    assert display.cb_data == 4
    assert systime.cb_data == 8
    assert short.cb_data == 2
    assert count.cb_data == 4
    assert boolean.cb_data == 1

    assert max(display.ib_data, systime.ib_data, count.ib_data) < layout.tci_4b
    assert short.ib_data >= layout.tci_4b
    assert boolean.ib_data >= layout.tci_2b


def test_tc_column_descriptors_are_sorted_by_property_tag() -> None:
    table = TableContext()
    table.add_column(0x5000, PropertyType.INTEGER32)
    table.add_column(0x1000, PropertyType.UNICODE)
    table.add_column(0x3000, PropertyType.BOOLEAN)

    image = table.build()
    (_, _, _, _, _, columns) = parse_tcinfo(image.heap, image.tcinfo_hid)

    tags = [column.tag for column in columns]
    assert tags == sorted(tags)


def test_tc_row_matrix_contains_inline_hid_values_and_ceb() -> None:
    table = TableContext()
    table.add_column(0x3001, PropertyType.UNICODE)
    table.add_column(0x3602, PropertyType.INTEGER32)
    table.add_column(0x360A, PropertyType.BOOLEAN)

    table.add_row(
        0x8022,
        {
            0x3001: "Inbox",
            0x3602: 5,
            # 0x360A deliberately absent to exercise sparse CEB.
        },
        row_version=7,
    )

    image = table.build()
    matrix = read_heap_allocation(image.heap, image.row_matrix_hnid)
    assert len(matrix) == image.layout.row_size

    row_id_col = _column(image.layout.descriptors, PID_LTP_ROW_ID)
    row_ver_col = _column(image.layout.descriptors, PID_LTP_ROW_VER)
    name_col = _column(image.layout.descriptors, 0x3001)
    count_col = _column(image.layout.descriptors, 0x3602)
    subfolders_col = _column(image.layout.descriptors, 0x360A)

    assert struct.unpack_from("<I", matrix, row_id_col.ib_data)[0] == 0x8022
    assert struct.unpack_from("<I", matrix, row_ver_col.ib_data)[0] == 7
    assert struct.unpack_from("<I", matrix, count_col.ib_data)[0] == 5
    assert matrix[subfolders_col.ib_data] == 0

    name_hid = struct.unpack_from("<I", matrix, name_col.ib_data)[0]
    assert read_heap_allocation(image.heap, name_hid) == (
        "Inbox".encode("utf-16-le") + b"\x00\x00"
    )

    ceb = matrix[image.layout.tci_1b:image.layout.tci_bm]
    assert len(ceb) == 1

    for column in (row_id_col, row_ver_col, name_col, count_col):
        assert ceb[column.bit_index // 8] & (0x80 >> (column.bit_index % 8))

    assert not (
        ceb[subfolders_col.bit_index // 8]
        & (0x80 >> (subfolders_col.bit_index % 8))
    )


def test_tc_row_index_maps_row_ids_to_unsorted_matrix_positions() -> None:
    table = TableContext()
    table.add_column(0x3602, PropertyType.INTEGER32)

    table.add_row(0x9002, {0x3602: 1})
    table.add_row(0x1002, {0x3602: 2})
    table.add_row(0x5002, {0x3602: 3})

    image = table.build()

    header = BthHeader.unpack(
        read_heap_allocation(image.heap, image.row_index.header_hid)
    )
    assert header.cb_key == 4
    assert header.cb_ent == 4
    assert header.index_levels == 0

    records = parse_leaf_records(
        read_heap_allocation(image.heap, header.root_hid),
        cb_key=4,
        cb_ent=4,
    )

    assert [
        (
            int.from_bytes(key, "little"),
            int.from_bytes(data, "little"),
        )
        for key, data in records
    ] == [
        (0x1002, 1),
        (0x5002, 2),
        (0x9002, 0),
    ]


def test_tcinfo_binary_header_and_descriptor_widths() -> None:
    table = TableContext()
    table.add_column(0x3001, PropertyType.UNICODE)
    image = table.build()

    raw = read_heap_allocation(image.heap, image.tcinfo_hid)

    assert raw[0] == TC_TYPE
    assert raw[1] == 3
    assert len(raw) == 22 + 3 * 8

    (
        b_type,
        c_cols,
        tci_4b,
        tci_2b,
        tci_1b,
        tci_bm,
        hid_row_index,
        hnid_rows,
        hid_index,
    ) = struct.unpack_from("<BBHHHHIII", raw, 0)

    assert b_type == TC_TYPE
    assert c_cols == 3
    assert (tci_4b, tci_2b, tci_1b, tci_bm) == (
        image.layout.tci_4b,
        image.layout.tci_2b,
        image.layout.tci_1b,
        image.layout.tci_bm,
    )
    assert hid_row_index == image.row_index.header_hid
    assert hnid_rows == 0
    assert hid_index == 0


def test_tc_rejects_duplicate_row_ids() -> None:
    table = TableContext()
    table.add_row(1)

    with pytest.raises(ValueError, match="duplicate TC row id"):
        table.add_row(1)


def test_tc_rejects_undeclared_row_column() -> None:
    table = TableContext()

    with pytest.raises(KeyError, match="undeclared column"):
        table.add_row(1, {0x3001: "missing"})


def test_tc_row_matrix_over_one_hn_allocation_uses_subnode() -> None:
    from open_ost2pst.pst.primitives import NidType, nid_type

    table = TableContext()
    table.add_column(0x3001, PropertyType.UNICODE)

    for index in range(300):
        table.add_row(index + 1, {0x3001: "x"})

    image = table.build()

    assert nid_type(image.row_matrix_hnid) == NidType.LTP
    assert any(
        value.nid == image.row_matrix_hnid
        for value in image.external_values
    )


def test_tc_can_be_embedded_as_ndb_node() -> None:
    table = TableContext()
    table.add_column(0x3001, PropertyType.UNICODE)
    table.add_row(0x8022, {0x3001: "Inbox"})

    builder = NdbImageBuilder()
    node = builder.add_table_context(0x12D, table)
    result = builder.build()

    assert node.nid == 0x12D
    assert node.data_bid == result.blocks[0].bref.bid
    assert result.blocks[0].data[2] == 0xEC
    assert result.blocks[0].data[3] == HeapClientSignature.TABLE_CONTEXT


def test_external_tc_row_matrix_declares_row_aligned_block_payload() -> None:
    table = TableContext()
    table.add_column(0x0017, PropertyType.INTEGER32)
    table.add_column(0x0036, PropertyType.INTEGER32)
    table.add_column(0x0E07, PropertyType.INTEGER32)

    for index in range(390):
        table.add_row(
            0x200000 + index,
            {
                0x0017: 1,
                0x0036: 0,
                0x0E07: 1,
            },
        )

    image = table.build()
    matrix_value = next(
        value
        for value in image.external_values
        if value.nid == image.row_matrix_hnid
    )

    expected_payload = (
        BLOCK_MAX_PAYLOAD // image.layout.row_size
    ) * image.layout.row_size
    assert matrix_value.block_payload_size == expected_payload
    assert matrix_value.block_payload_size % image.layout.row_size == 0
    assert matrix_value.pad_nonfinal_to_max is True
