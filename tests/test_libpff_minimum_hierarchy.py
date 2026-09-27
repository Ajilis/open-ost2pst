import tempfile

import pytest

from open_ost2pst.pst.messaging import (
    NID_DELETED_ITEMS,
    NID_IPM_SUBTREE,
    NID_SEARCH_ROOT,
    NID_SPAM_SEARCH_FOLDER,
    MessagingBuilder,
)
from tests._libpff_helpers import get_child_by_name, get_physical_root


pypff = pytest.importorskip("pypff")


def test_libpff_reads_minimum_folder_hierarchy() -> None:
    builder = MessagingBuilder(root_name="Top of Personal Folders")
    result = builder.build()

    with tempfile.NamedTemporaryFile(suffix=".pst") as handle:
        handle.write(result.data)
        handle.flush()

        store = pypff.file()
        store.open(handle.name)
        try:
            root = get_physical_root(store)
            assert root.get_number_of_sub_folders() == 3

            ipm = get_child_by_name(root, "Top of Personal Folders")
            search = get_child_by_name(root, "Search Root")
            spam = get_child_by_name(root, "SPAM Search Folder 2")

            assert ipm.get_identifier() == NID_IPM_SUBTREE
            assert search.get_identifier() == NID_SEARCH_ROOT
            assert spam.get_identifier() == NID_SPAM_SEARCH_FOLDER

            deleted = get_child_by_name(ipm, "Deleted Items")
            assert deleted.get_identifier() == NID_DELETED_ITEMS
        finally:
            store.close()
