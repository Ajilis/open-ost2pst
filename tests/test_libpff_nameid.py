import tempfile

import pytest

from open_ost2pst.pst.ltp.pc import PropertyType
from open_ost2pst.pst.messaging import MessagingBuilder
from tests._libpff_helpers import get_child_by_name, get_ipm_subtree


pypff = pytest.importorskip("pypff")


def _entry_by_type(record_set, entry_type):
    if hasattr(record_set, "get_entry_by_type"):
        return record_set.get_entry_by_type(entry_type)

    for index in range(record_set.get_number_of_entries()):
        entry = record_set.get_entry(index)
        if entry.get_entry_type() == entry_type:
            return entry
    return None


def test_libpff_parses_real_named_property_map() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(
        inbox,
        subject="Named property",
        body="Name-to-ID test",
    )

    property_id = builder.set_named_property(
        message,
        "X-OpenOst2Pst-Test",
        "named-value",
        property_type=PropertyType.UNICODE,
    )
    assert property_id == 0x8001

    result = builder.build()

    with tempfile.NamedTemporaryFile(suffix=".pst") as handle:
        handle.write(result.data)
        handle.flush()

        store = pypff.file()
        store.open(handle.name)
        try:
            name_map = store.get_name_to_id_map()
            assert name_map is not None

            ipm = get_ipm_subtree(store)
            inbox_item = get_child_by_name(ipm, "Inbox")
            item = inbox_item.get_sub_message(0)

            record_set = item.get_record_set(0)
            entry = _entry_by_type(record_set, property_id)
            assert entry is not None
            assert entry.get_data_as_string() == "named-value"
        finally:
            store.close()
