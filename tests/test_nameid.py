import struct
from uuid import UUID

from open_ost2pst.pst.crc import compute_crc
from open_ost2pst.pst.ltp.tc import read_heap_allocation
from open_ost2pst.pst.primitives import NidType, nid_type
from open_ost2pst.pst.nameid import (
    DEFAULT_BUCKET_COUNT,
    FIRST_NAMED_PROPERTY_ID,
    NID_NAME_TO_ID_MAP,
    PR_NAMEID_BUCKET_BASE,
    PR_NAMEID_BUCKET_COUNT,
    PR_NAMEID_STREAM_ENTRY,
    PR_NAMEID_STREAM_GUID,
    PR_NAMEID_STREAM_STRING,
    PS_MAPI,
    NameIdMap,
    parse_nameid_records,
)


def _entry(image, property_id):
    return next(item for item in image.entries if item.property_id == property_id)


def _value(image, property_id):
    entry = _entry(image, property_id)
    if nid_type(entry.hnid) == NidType.LTP:
        return next(
            value.data
            for value in image.external_values
            if value.nid == entry.hnid
        )
    return read_heap_allocation(image.heap, entry.hnid)


def test_empty_nameid_map_has_required_bucket_count() -> None:
    mapping = NameIdMap()
    image = mapping.build_property_context().build()

    bucket = _entry(image, PR_NAMEID_BUCKET_COUNT)
    assert bucket.hnid == DEFAULT_BUCKET_COUNT
    assert mapping.property_count == 0
    assert NID_NAME_TO_ID_MAP == 0x61
    assert _value(image, PR_NAMEID_STREAM_GUID) == b""
    assert _value(image, PR_NAMEID_STREAM_ENTRY) == b""
    assert _value(image, PR_NAMEID_STREAM_STRING) == b""


def test_string_named_property_builds_string_entry_and_hash_bucket() -> None:
    mapping = NameIdMap()
    property_id = mapping.register_string("X-Test-Property")

    assert property_id == FIRST_NAMED_PROPERTY_ID
    image = mapping.build_property_context().build()

    entry_stream = _value(image, PR_NAMEID_STREAM_ENTRY)
    records = parse_nameid_records(entry_stream)
    assert len(records) == 1
    record = records[0]
    assert record.property_index == 0
    assert record.named_property_id == 0x8000
    assert record.guid_index == 0
    assert record.is_string is True
    assert record.property_id_or_offset == 0

    string_stream = _value(image, PR_NAMEID_STREAM_STRING)
    name_bytes = "X-Test-Property".encode("utf-16-le")
    assert struct.unpack_from("<I", string_stream, 0)[0] == len(name_bytes)
    assert string_stream[4:4 + len(name_bytes)] == name_bytes
    assert len(string_stream) % 4 == 0

    packed_guid = 1
    bucket_index = (compute_crc(name_bytes) ^ packed_guid) % DEFAULT_BUCKET_COUNT
    bucket_stream = _value(image, PR_NAMEID_BUCKET_BASE + bucket_index)
    bucket_record = parse_nameid_records(bucket_stream)[0]
    assert bucket_record.property_id_or_offset == compute_crc(name_bytes)
    assert bucket_record.is_string is True
    assert bucket_record.property_index == 0


def test_numeric_named_property_uses_well_known_guid() -> None:
    mapping = NameIdMap()
    property_id = mapping.register_numeric(0x8501, guid=PS_MAPI)
    assert property_id == 0x8000

    image = mapping.build_property_context().build()
    record = parse_nameid_records(_value(image, PR_NAMEID_STREAM_ENTRY))[0]

    assert record.property_id_or_offset == 0x8501
    assert record.guid_index == 1
    assert record.is_string is False


def test_custom_guid_stream_uses_guid_bytes_le() -> None:
    guid = UUID("00062008-0000-0000-c000-000000000046")
    mapping = NameIdMap()

    first = mapping.register_numeric(0x8501, guid=guid)
    second = mapping.register_string("CustomName", guid=guid)

    assert (first, second) == (0x8000, 0x8001)

    image = mapping.build_property_context().build()
    assert _value(image, PR_NAMEID_STREAM_GUID) == guid.bytes_le

    records = parse_nameid_records(_value(image, PR_NAMEID_STREAM_ENTRY))
    assert [record.guid_index for record in records] == [3, 3]


def test_duplicate_named_property_reuses_property_id() -> None:
    mapping = NameIdMap()
    first = mapping.register_string("Same")
    second = mapping.register_string("Same")

    assert first == second == 0x8000
    assert mapping.property_count == 1
