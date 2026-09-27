import tempfile

import pytest

from open_ost2pst.pst.image import NdbImageBuilder
from open_ost2pst.pst.ltp.pc import PropertyContext
from open_ost2pst.pst.ltp.tc import TableContext
from open_ost2pst.pst.primitives import NidType, make_nid, nid_index


pypff = pytest.importorskip("pypff")

NID_MESSAGE_STORE = 0x21
NID_ROOT_FOLDER = 0x122

PR_DISPLAY_NAME = 0x3001
PR_CONTENT_COUNT = 0x3602
PR_CONTENT_UNREAD = 0x3603
PR_SUBFOLDERS = 0x360A
PR_STORE_SUPPORT_MASK = 0x340D


def _folder_pc(name: str, *, subfolders: bool) -> PropertyContext:
    pc = PropertyContext()
    pc.set_unicode(PR_DISPLAY_NAME, name)
    pc.set_integer32(PR_CONTENT_COUNT, 0)
    pc.set_integer32(PR_CONTENT_UNREAD, 0)
    pc.set_boolean(PR_SUBFOLDERS, subfolders)
    return pc


def _hierarchy_table() -> TableContext:
    table = TableContext()
    table.add_column(PR_DISPLAY_NAME, 0x001F)
    table.add_column(PR_CONTENT_COUNT, 0x0003)
    table.add_column(PR_CONTENT_UNREAD, 0x0003)
    table.add_column(PR_SUBFOLDERS, 0x000B)
    return table


def test_libpff_reads_hierarchy_table_context() -> None:
    child_nid = make_nid(NidType.NORMAL_FOLDER, 0x401)
    root_hierarchy_nid = make_nid(
        NidType.HIERARCHY_TABLE,
        nid_index(NID_ROOT_FOLDER),
    )
    child_hierarchy_nid = make_nid(
        NidType.HIERARCHY_TABLE,
        nid_index(child_nid),
    )

    store_pc = PropertyContext()
    store_pc.set_unicode(PR_DISPLAY_NAME, "Open OST2PST Store")
    store_pc.set_integer32(PR_STORE_SUPPORT_MASK, 0)

    root_hierarchy = _hierarchy_table()
    root_hierarchy.add_row(
        child_nid,
        {
            PR_DISPLAY_NAME: "Inbox",
            PR_CONTENT_COUNT: 0,
            PR_CONTENT_UNREAD: 0,
            PR_SUBFOLDERS: False,
        },
    )

    child_hierarchy = _hierarchy_table()

    builder = NdbImageBuilder()
    builder.add_property_context(NID_MESSAGE_STORE, store_pc)
    builder.add_property_context(
        NID_ROOT_FOLDER,
        _folder_pc("Top of Personal Folders", subfolders=True),
        parent_nid=NID_ROOT_FOLDER,
    )
    builder.add_property_context(
        child_nid,
        _folder_pc("Inbox", subfolders=False),
        parent_nid=NID_ROOT_FOLDER,
    )
    builder.add_table_context(root_hierarchy_nid, root_hierarchy)
    builder.add_table_context(child_hierarchy_nid, child_hierarchy)

    result = builder.build()

    with tempfile.NamedTemporaryFile(suffix=".pst") as handle:
        handle.write(result.data)
        handle.flush()

        store_file = pypff.file()
        store_file.open(handle.name)
        try:
            root = store_file.get_root_folder()
            assert root is not None
            assert root.get_identifier() == NID_ROOT_FOLDER
            assert root.get_name() == "Top of Personal Folders"
            assert root.get_number_of_sub_folders() == 1

            child = root.get_sub_folder(0)
            assert child is not None
            assert child.get_identifier() == child_nid
            assert child.get_name() == "Inbox"
            assert child.get_number_of_sub_folders() == 0
        finally:
            store_file.close()
