"""Table Context (TC) writer for the MS-PST LTP layer."""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any

from .bth import BthBuildResult, BthHeader, build_bth
from .heap import HID_NULL, MAX_HEAP_ALLOCATION, HeapClientSignature, HeapImage, HeapNode
from .pc import PropertyType


PID_LTP_ROW_ID = 0x67F2
PID_LTP_ROW_VER = 0x67F3
TC_TYPE = 0x7C
TCINFO_FIXED_SIZE = 22
TCOLDESC_SIZE = 8


_VARIABLE_TYPES = {
    PropertyType.STRING8,
    PropertyType.UNICODE,
    PropertyType.GUID,
    PropertyType.BINARY,
}


@dataclass(slots=True)
class TableColumn:
    property_id: int
    property_type: PropertyType
    ib_data: int = 0
    cb_data: int = 0
    bit_index: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.property_id <= 0xFFFF:
            raise ValueError("property_id must fit in 16 bits")
        self.cb_data = _column_width(self.property_type)

    @property
    def tag(self) -> int:
        return (self.property_id << 16) | int(self.property_type)

    def pack(self) -> bytes:
        return struct.pack(
            "<HHHBB",
            int(self.property_type),
            self.property_id,
            self.ib_data,
            self.cb_data,
            self.bit_index,
        )


@dataclass(frozen=True, slots=True)
class TableLayout:
    tci_4b: int
    tci_2b: int
    tci_1b: int
    tci_bm: int
    ceb_size: int
    physical_columns: tuple[TableColumn, ...]
    descriptors: tuple[TableColumn, ...]

    @property
    def row_size(self) -> int:
        return self.tci_bm


@dataclass(frozen=True, slots=True)
class TableContextImage:
    heap: HeapImage
    row_index: BthBuildResult
    layout: TableLayout
    row_count: int
    row_matrix_hnid: int
    tcinfo_hid: int

    def single_block(self) -> bytes:
        return self.heap.single_block()


class TableContext:
    """Build a small Table Context with an HN-resident Row Matrix.

    Large Row Matrices are intentionally rejected until subnode/XBLOCK data
    trees are available.
    """

    def __init__(self) -> None:
        self._columns: dict[int, TableColumn] = {}
        self._rows: list[tuple[int, dict[int, Any]]] = []
        self.add_column(PID_LTP_ROW_ID, PropertyType.INTEGER32)
        self.add_column(PID_LTP_ROW_VER, PropertyType.INTEGER32)

    @property
    def column_count(self) -> int:
        return len(self._columns)

    @property
    def row_count(self) -> int:
        return len(self._rows)

    @property
    def row_ids(self) -> tuple[int, ...]:
        return tuple(row_id for row_id, _ in self._rows)

    def add_column(
        self,
        property_id: int,
        property_type: int | PropertyType,
    ) -> TableColumn:
        try:
            ptype = PropertyType(int(property_type))
        except ValueError as exc:
            raise ValueError(f"unsupported TC property type: {property_type:#x}") from exc

        existing = self._columns.get(property_id)
        if existing is not None:
            if existing.property_type != ptype:
                raise ValueError(
                    f"column 0x{property_id:04x} already exists with another type"
                )
            return existing

        if len(self._columns) >= 255:
            raise ValueError("TC column count cannot exceed 255")

        column = TableColumn(property_id=property_id, property_type=ptype)
        self._columns[property_id] = column
        return column

    def add_row(
        self,
        row_id: int,
        values: dict[int, Any] | None = None,
        *,
        row_version: int = 1,
    ) -> None:
        if not isinstance(row_id, int) or not 0 <= row_id <= 0xFFFFFFFF:
            raise ValueError("row_id must fit in 32 bits")
        if row_id in self.row_ids:
            raise ValueError(f"duplicate TC row id: {row_id:#x}")
        if not 0 <= row_version <= 0xFFFFFFFF:
            raise ValueError("row_version must fit in 32 bits")

        supplied = dict(values or {})
        supplied.pop(PID_LTP_ROW_ID, None)
        supplied.pop(PID_LTP_ROW_VER, None)

        undeclared = set(supplied) - set(self._columns)
        if undeclared:
            first = min(undeclared)
            raise KeyError(f"row uses undeclared column 0x{first:04x}")

        supplied[PID_LTP_ROW_ID] = row_id
        supplied[PID_LTP_ROW_VER] = row_version
        self._rows.append((row_id, supplied))

    def build(self) -> TableContextImage:
        layout = self._layout()
        heap = HeapNode(HeapClientSignature.TABLE_CONTEXT)

        matrix = bytearray()
        row_index_records: list[tuple[bytes, bytes]] = []

        for row_index, (row_id, values) in enumerate(self._rows):
            row = bytearray(layout.row_size)
            ceb = bytearray(layout.ceb_size)

            for column in layout.physical_columns:
                if column.property_id not in values:
                    continue

                cell = self._encode_cell(heap, column, values[column.property_id])
                if len(cell) != column.cb_data:
                    raise AssertionError("encoded TC cell width mismatch")

                start = column.ib_data
                row[start:start + column.cb_data] = cell

                byte_index, bit_index = divmod(column.bit_index, 8)
                ceb[byte_index] |= 0x80 >> bit_index

            row[layout.tci_1b:layout.tci_bm] = ceb
            matrix.extend(row)
            row_index_records.append(
                (
                    struct.pack("<I", row_id),
                    struct.pack("<I", row_index),
                )
            )

        if matrix:
            if len(matrix) > MAX_HEAP_ALLOCATION:
                raise ValueError(
                    "TC Row Matrix exceeds one HN allocation; "
                    "subnode row storage is not implemented yet"
                )
            row_matrix_hnid = heap.allocate(matrix)
        else:
            row_matrix_hnid = HID_NULL

        row_index = build_bth(
            heap,
            cb_key=4,
            cb_ent=4,
            records=row_index_records,
            set_user_root=False,
        )

        tcinfo = bytearray()
        tcinfo.extend(
            struct.pack(
                "<BBHHHHIII",
                TC_TYPE,
                len(layout.descriptors),
                layout.tci_4b,
                layout.tci_2b,
                layout.tci_1b,
                layout.tci_bm,
                row_index.header_hid,
                row_matrix_hnid,
                0,
            )
        )
        for column in layout.descriptors:
            tcinfo.extend(column.pack())

        tcinfo_hid = heap.allocate(tcinfo)
        heap.set_user_root(tcinfo_hid)

        return TableContextImage(
            heap=heap.build(),
            row_index=row_index,
            layout=layout,
            row_count=len(self._rows),
            row_matrix_hnid=row_matrix_hnid,
            tcinfo_hid=tcinfo_hid,
        )

    def serialize(self) -> bytes:
        return self.build().single_block()

    def _layout(self) -> TableLayout:
        row_id = self._columns[PID_LTP_ROW_ID]
        row_ver = self._columns[PID_LTP_ROW_VER]

        other_columns = [
            column
            for property_id, column in self._columns.items()
            if property_id not in (PID_LTP_ROW_ID, PID_LTP_ROW_VER)
        ]

        # iBit order is logical and deterministic: mandatory RowId/RowVer first,
        # then remaining columns by property tag.
        logical = [row_id, row_ver] + sorted(other_columns, key=lambda c: c.tag)
        for bit_index, column in enumerate(logical):
            column.bit_index = bit_index

        # Physical row layout uses the required 8/4, 2, 1 byte groups.
        # RowId and RowVer are kept at offsets 0 and 4.
        group_8_4 = [
            column
            for column in other_columns
            if column.cb_data in (8, 4)
        ]
        group_2 = [column for column in other_columns if column.cb_data == 2]
        group_1 = [column for column in other_columns if column.cb_data == 1]

        physical = [row_id, row_ver]
        physical.extend(sorted(group_8_4, key=lambda c: c.tag))
        physical.extend(sorted(group_2, key=lambda c: c.tag))
        physical.extend(sorted(group_1, key=lambda c: c.tag))

        cursor = 0
        for column in physical:
            column.ib_data = cursor
            cursor += column.cb_data
            if cursor > 0xFFFF:
                raise ValueError("TC row layout exceeds 16-bit offsets")

        tci_4b = sum(c.cb_data for c in physical if c.cb_data in (8, 4))
        tci_2b = tci_4b + sum(c.cb_data for c in physical if c.cb_data == 2)
        tci_1b = tci_2b + sum(c.cb_data for c in physical if c.cb_data == 1)
        ceb_size = math.ceil(len(self._columns) / 8)
        tci_bm = tci_1b + ceb_size

        if tci_bm > 0xFFFF:
            raise ValueError("TC row size exceeds 16 bits")

        descriptors = tuple(sorted(self._columns.values(), key=lambda c: c.tag))
        return TableLayout(
            tci_4b=tci_4b,
            tci_2b=tci_2b,
            tci_1b=tci_1b,
            tci_bm=tci_bm,
            ceb_size=ceb_size,
            physical_columns=tuple(physical),
            descriptors=descriptors,
        )

    @staticmethod
    def _encode_cell(
        heap: HeapNode,
        column: TableColumn,
        value: Any,
    ) -> bytes:
        ptype = column.property_type

        if ptype == PropertyType.INTEGER16:
            return struct.pack("<H", int(value) & 0xFFFF)
        if ptype == PropertyType.INTEGER32:
            return struct.pack("<I", int(value) & 0xFFFFFFFF)
        if ptype == PropertyType.FLOAT32:
            return struct.pack("<f", float(value))
        if ptype == PropertyType.FLOAT64:
            return struct.pack("<d", float(value))
        if ptype == PropertyType.BOOLEAN:
            return struct.pack("<B", 1 if value else 0)
        if ptype == PropertyType.INTEGER64:
            return struct.pack("<Q", int(value) & 0xFFFFFFFFFFFFFFFF)
        if ptype == PropertyType.SYSTIME:
            numeric = int(value)
            if not 0 <= numeric <= 0xFFFFFFFFFFFFFFFF:
                raise ValueError("SYSTIME value must fit in 64 bits")
            return struct.pack("<Q", numeric)

        if ptype == PropertyType.UNICODE:
            data = str(value).encode("utf-16-le") + b"\x00\x00"
        elif ptype == PropertyType.STRING8:
            data = str(value).encode("cp1252") + b"\x00"
        elif ptype == PropertyType.BINARY:
            data = bytes(value)
            if not data:
                raise ValueError("empty TC binary values are not supported yet")
        elif ptype == PropertyType.GUID:
            data = bytes(value)
            if len(data) != 16:
                raise ValueError("TC GUID values must be exactly 16 bytes")
        else:
            raise ValueError(f"unsupported TC property type: {int(ptype):#x}")

        if len(data) > MAX_HEAP_ALLOCATION:
            raise ValueError(
                "TC cell value requires subnode storage; not implemented yet"
            )
        hid = heap.allocate(data)
        return struct.pack("<I", hid)


def parse_tcinfo(
    heap: HeapNode,
    tcinfo_hid: int,
) -> tuple[
    int,
    tuple[int, int, int, int],
    int,
    int,
    int,
    tuple[TableColumn, ...],
]:
    """Diagnostic parser for an in-memory TC builder."""

    data = heap.get_allocation(tcinfo_hid)
    if len(data) < TCINFO_FIXED_SIZE:
        raise ValueError("TCINFO allocation is truncated")

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
    ) = struct.unpack_from("<BBHHHHIII", data, 0)

    if b_type != TC_TYPE:
        raise ValueError("invalid TCINFO bType")

    expected = TCINFO_FIXED_SIZE + c_cols * TCOLDESC_SIZE
    if len(data) != expected:
        raise ValueError("TCINFO column descriptor length mismatch")

    columns = []
    offset = TCINFO_FIXED_SIZE
    for _ in range(c_cols):
        ptype, property_id, ib_data, cb_data, bit_index = struct.unpack_from(
            "<HHHBB", data, offset
        )
        column = TableColumn(
            property_id=property_id,
            property_type=PropertyType(ptype),
        )
        column.ib_data = ib_data
        column.cb_data = cb_data
        column.bit_index = bit_index
        columns.append(column)
        offset += TCOLDESC_SIZE

    return (
        c_cols,
        (tci_4b, tci_2b, tci_1b, tci_bm),
        hid_row_index,
        hnid_rows,
        hid_index,
        tuple(columns),
    )


def parse_row_index_header(heap: HeapNode, hid_row_index: int) -> BthHeader:
    return BthHeader.unpack(heap.get_allocation(hid_row_index))


def _column_width(property_type: PropertyType) -> int:
    if property_type == PropertyType.BOOLEAN:
        return 1
    if property_type == PropertyType.INTEGER16:
        return 2
    if property_type in (
        PropertyType.INTEGER32,
        PropertyType.FLOAT32,
        PropertyType.STRING8,
        PropertyType.UNICODE,
        PropertyType.GUID,
        PropertyType.BINARY,
    ):
        return 4
    if property_type in (
        PropertyType.FLOAT64,
        PropertyType.INTEGER64,
        PropertyType.SYSTIME,
    ):
        return 8
    raise ValueError(f"unsupported TC property type: {int(property_type):#x}")
