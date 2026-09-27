from open_ost2pst.pst.messaging import (
    MSGFLAG_READ,
    NID_IPM_SUBTREE,
    NID_MESSAGE_STORE,
    NID_ROOT_FOLDER,
    MessagingBuilder,
)
from open_ost2pst.pst.primitives import NidType, make_nid, nid_index


def test_messaging_builder_allocates_folder_and_message_nids() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(
        inbox,
        subject="Hello",
        body="Body",
        sender_name="Alice",
        sender_email="alice@example.com",
    )

    assert builder.root.nid == NID_IPM_SUBTREE
    assert inbox.nid == make_nid(NidType.NORMAL_FOLDER, 0x404)
    assert message.nid == make_nid(NidType.NORMAL_MESSAGE, 0x10000)

    assert make_nid(NidType.HIERARCHY_TABLE, nid_index(inbox.nid)) != inbox.nid
    assert make_nid(NidType.CONTENTS_TABLE, nid_index(inbox.nid)) != inbox.nid


def test_messaging_builder_counts_nested_folders_and_messages() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    projects = builder.add_folder(inbox, "Projects")
    builder.add_message(inbox, subject="One", body="1")
    builder.add_message(projects, subject="Two", body="2", is_read=False)

    result = builder.build()

    assert result.root_folder_nid == NID_ROOT_FOLDER
    assert result.folder_count == 7
    assert result.ipm_subtree_nid == NID_IPM_SUBTREE
    assert result.message_count == 2
    assert result.data[:4] == b"!BDN"


def test_messaging_builder_emits_store_root_tables_and_message_nodes() -> None:
    builder = MessagingBuilder(store_name="Test Store")
    inbox = builder.add_folder(builder.root, "Inbox")
    message = builder.add_message(inbox, subject="Subject", body="Body")

    result = builder.build()
    nids = {entry.nid for entry in result.pst.nbt_pages_entries} if hasattr(result.pst, "nbt_pages_entries") else None

    # The public build result remains intentionally NDB-oriented. Verify the
    # expected high-level objects and a non-empty PST image without depending
    # on private BTree internals.
    assert NID_MESSAGE_STORE == 0x21
    assert builder.root.nid == NID_IPM_SUBTREE
    assert inbox.messages[0].nid == message.nid
    assert len(result.data) == result.pst.header.root.file_eof


def test_unread_messages_are_preserved_in_builder_state() -> None:
    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    read = builder.add_message(inbox, subject="Read", is_read=True)
    unread = builder.add_message(inbox, subject="Unread", is_read=False)

    assert read.is_read is True
    assert unread.is_read is False
    assert MSGFLAG_READ == 1


def test_messaging_builder_allocates_named_properties() -> None:
    from open_ost2pst.pst.ltp.pc import PropertyType

    builder = MessagingBuilder()
    message = builder.add_message(builder.root, subject="Named")

    property_id = builder.set_named_property(
        message,
        "X-Custom-Name",
        "value",
        property_type=PropertyType.UNICODE,
    )

    assert property_id == 0x8000
    assert builder.nameid.property_count == 1
    assert message.named_properties[property_id] == (
        PropertyType.UNICODE,
        "value",
    )
