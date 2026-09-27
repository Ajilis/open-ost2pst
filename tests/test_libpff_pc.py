import tempfile

import pytest

from open_ost2pst.pst.image import NdbImageBuilder
from open_ost2pst.pst.ltp.pc import PropertyContext


pypff = pytest.importorskip("pypff")

PR_DISPLAY_NAME = 0x3001
PR_STORE_SUPPORT_MASK = 0x340D


def _entry_by_type(record_set, entry_type):
    if hasattr(record_set, "get_entry_by_type"):
        return record_set.get_entry_by_type(entry_type)

    for index in range(record_set.get_number_of_entries()):
        entry = record_set.get_entry(index)
        if entry.get_entry_type() == entry_type:
            return entry
    return None


def test_libpff_reads_message_store_property_context() -> None:
    pc = PropertyContext()
    pc.set_unicode(PR_DISPLAY_NAME, "Open OST2PST Store")
    pc.set_integer32(PR_STORE_SUPPORT_MASK, 0)

    builder = NdbImageBuilder()
    builder.add_property_context(0x21, pc)
    result = builder.build()

    with tempfile.NamedTemporaryFile(suffix=".pst") as handle:
        handle.write(result.data)
        handle.flush()

        store_file = pypff.file()
        store_file.open(handle.name)
        try:
            store = store_file.get_message_store()
            assert store is not None
            assert store.get_identifier() == 0x21
            assert store.get_number_of_record_sets() >= 1

            record_set = store.get_record_set(0)
            display = _entry_by_type(record_set, PR_DISPLAY_NAME)
            support = _entry_by_type(record_set, PR_STORE_SUPPORT_MASK)

            assert display is not None
            assert display.get_value_type() == 0x001F
            assert display.get_data_as_string() == "Open OST2PST Store"

            assert support is not None
            assert support.get_value_type() == 0x0003
            assert support.get_data_as_integer() == 0
        finally:
            store_file.close()
