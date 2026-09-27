"""PST Messaging layer built on top of NDB + LTP."""

from __future__ import annotations

from dataclasses import dataclass, field

from .image import NdbBuildResult, NdbImageBuilder
from .nameid import NameIdMap
from .ltp.pc import PropertyContext
from .ltp.tc import TableContext
from .primitives import NidType, make_nid, nid_index
from .rtf import compress_rtf


NID_MESSAGE_STORE = 0x0021
NID_ROOT_FOLDER = 0x0122
NID_IPM_SUBTREE = 0x8022
NID_SEARCH_ROOT = 0x8042
NID_DELETED_ITEMS = 0x8062
NID_SPAM_SEARCH_FOLDER = 0x2223
NID_ATTACHMENT_TABLE = 0x0671
NID_RECIPIENT_TABLE = 0x0692

PR_MESSAGE_CLASS = 0x001A
PR_SUBJECT = 0x0037
PR_CLIENT_SUBMIT_TIME = 0x0039
PR_SENDER_NAME = 0x0C1A
PR_RECIPIENT_TYPE = 0x0C15
PR_SENDER_EMAIL_ADDRESS = 0x0C1F
PR_DISPLAY_CC = 0x0E03
PR_DISPLAY_TO = 0x0E04
PR_MESSAGE_DELIVERY_TIME = 0x0E06
PR_MESSAGE_FLAGS = 0x0E07
PR_HAS_ATTACH = 0x0E1B
PR_ATTACH_SIZE = 0x0E20
PR_BODY = 0x1000
PR_RTF_COMPRESSED = 0x1009
PR_HTML = 0x1013

PR_DISPLAY_NAME = 0x3001
PR_ADDRTYPE = 0x3002
PR_EMAIL_ADDRESS = 0x3003
PR_CREATION_TIME = 0x3007
PR_STORE_SUPPORT_MASK = 0x340D
PR_CONTENT_COUNT = 0x3602
PR_CONTENT_UNREAD = 0x3603
PR_SUBFOLDERS = 0x360A
PR_ATTACH_DATA = 0x3701
PR_ATTACH_FILENAME = 0x3704
PR_ATTACH_METHOD = 0x3705
PR_ATTACH_LONG_FILENAME = 0x3707
PR_ATTACH_MIME_TAG = 0x370E
PR_SMTP_ADDRESS = 0x39FE

MSGFLAG_READ = 0x00000001
ATTACH_BY_VALUE = 1

RECIPIENT_TYPE_TO = 1
RECIPIENT_TYPE_CC = 2
RECIPIENT_TYPE_BCC = 3


@dataclass(slots=True)
class MessagingRecipient:
    name: str = ""
    email: str = ""
    recipient_type: int = RECIPIENT_TYPE_TO


@dataclass(slots=True)
class MessagingAttachment:
    filename: str
    data: bytes
    mime_type: str | None = None


@dataclass(slots=True)
class MessagingMessage:
    nid: int
    subject: str = ""
    body: str = ""
    sender_name: str = ""
    sender_email: str = ""
    display_to: str = ""
    display_cc: str = ""
    html_body: bytes | None = None
    rtf_body: bytes | None = None
    delivery_filetime: int | None = None
    client_submit_filetime: int | None = None
    creation_filetime: int | None = None
    is_read: bool = True
    recipients: list[MessagingRecipient] = field(default_factory=list)
    attachments: list[MessagingAttachment] = field(default_factory=list)


@dataclass(slots=True)
class MessagingFolder:
    nid: int
    name: str
    folders: list["MessagingFolder"] = field(default_factory=list)
    messages: list[MessagingMessage] = field(default_factory=list)

    @property
    def index(self) -> int:
        return nid_index(self.nid)


@dataclass(frozen=True, slots=True)
class MessagingBuildResult:
    pst: NdbBuildResult
    root_folder_nid: int
    folder_count: int
    message_count: int
    attachment_count: int
    ipm_subtree_nid: int

    @property
    def data(self) -> bytes:
        return self.pst.data


class MessagingBuilder:
    """Build a browsable PST hierarchy with folders and IPM.Note messages."""

    def __init__(
        self,
        *,
        store_name: str = "Open OST2PST Store",
        root_name: str = "Top of Personal Folders",
    ) -> None:
        self.store_name = store_name
        self.nameid = NameIdMap()

        # Keep the public root API pointed at the user-visible IPM subtree.
        # The physical NID_ROOT_FOLDER is emitted separately during build().
        self.root = MessagingFolder(NID_IPM_SUBTREE, root_name)
        self.deleted_items = MessagingFolder(
            NID_DELETED_ITEMS,
            "Deleted Items",
        )
        self.root.folders.append(self.deleted_items)

        # 0x401, 0x402 and 0x403 are reserved for the mandatory IPM,
        # Search Root and Deleted Items folders.
        self._next_folder_index = 0x404
        self._next_message_index = 0x10000

    def add_folder(
        self,
        parent: MessagingFolder,
        name: str,
    ) -> MessagingFolder:
        nid = make_nid(NidType.NORMAL_FOLDER, self._next_folder_index)
        self._next_folder_index += 1
        folder = MessagingFolder(nid=nid, name=name)
        parent.folders.append(folder)
        return folder

    def register_named_string(
        self,
        name: str,
        *,
        guid=None,
    ) -> int:
        return self.nameid.register_string(name, guid=guid)

    def register_named_numeric(
        self,
        lid: int,
        *,
        guid,
    ) -> int:
        return self.nameid.register_numeric(lid, guid=guid)

    def add_message(
        self,
        folder: MessagingFolder,
        *,
        subject: str = "",
        body: str = "",
        sender_name: str = "",
        sender_email: str = "",
        display_to: str = "",
        display_cc: str = "",
        html_body: bytes | None = None,
        rtf_body: bytes | None = None,
        delivery_filetime: int | None = None,
        client_submit_filetime: int | None = None,
        creation_filetime: int | None = None,
        is_read: bool = True,
    ) -> MessagingMessage:
        nid = make_nid(NidType.NORMAL_MESSAGE, self._next_message_index)
        self._next_message_index += 1

        message = MessagingMessage(
            nid=nid,
            subject=subject,
            body=body,
            sender_name=sender_name,
            sender_email=sender_email,
            display_to=display_to,
            display_cc=display_cc,
            html_body=html_body,
            rtf_body=rtf_body,
            delivery_filetime=delivery_filetime,
            client_submit_filetime=client_submit_filetime,
            creation_filetime=creation_filetime,
            is_read=is_read,
        )
        folder.messages.append(message)
        return message

    def add_recipient(
        self,
        message: MessagingMessage,
        *,
        name: str = "",
        email: str = "",
        recipient_type: int = RECIPIENT_TYPE_TO,
    ) -> MessagingRecipient:
        if recipient_type not in (
            RECIPIENT_TYPE_TO,
            RECIPIENT_TYPE_CC,
            RECIPIENT_TYPE_BCC,
        ):
            raise ValueError("recipient_type must be To, Cc, or Bcc")

        recipient = MessagingRecipient(
            name=name,
            email=email,
            recipient_type=recipient_type,
        )
        message.recipients.append(recipient)
        return recipient

    def add_attachment(
        self,
        message: MessagingMessage,
        *,
        filename: str,
        data: bytes | bytearray | memoryview,
        mime_type: str | None = None,
    ) -> MessagingAttachment:
        attachment = MessagingAttachment(
            filename=filename,
            data=bytes(data),
            mime_type=mime_type,
        )
        message.attachments.append(attachment)
        return attachment

    def build(self) -> MessagingBuildResult:
        ndb = NdbImageBuilder()

        store_pc = PropertyContext()
        store_pc.set_unicode(PR_DISPLAY_NAME, self.store_name)
        store_pc.set_integer32(PR_STORE_SUPPORT_MASK, 0)
        ndb.add_property_context(NID_MESSAGE_STORE, store_pc)

        # Every PST has exactly one Name-to-ID map. An empty map is still a
        # valid PC with PidTagNameidBucketCount=251.
        ndb.add_property_context(
            0x0061,
            self.nameid.build_property_context(),
        )

        self._emit_minimum_root(ndb)

        folder_count, message_count, attachment_count = self._emit_folder(
            ndb,
            self.root,
            parent_nid=NID_ROOT_FOLDER,
        )

        # Search Root is a mandatory normal folder under the physical root.
        search_root = MessagingFolder(NID_SEARCH_ROOT, "Search Root")
        search_folders, search_messages, search_attachments = self._emit_folder(
            ndb,
            search_root,
            parent_nid=NID_ROOT_FOLDER,
        )

        # The mandatory spam search folder is a search-folder PC referenced
        # by the physical root hierarchy. No additional table nodes are
        # required by the minimum-node set.
        spam_pc = PropertyContext()
        spam_pc.set_unicode(PR_DISPLAY_NAME, "SPAM Search Folder 2")
        spam_pc.set_integer32(PR_CONTENT_COUNT, 0)
        spam_pc.set_integer32(PR_CONTENT_UNREAD, 0)
        spam_pc.set_boolean(PR_SUBFOLDERS, False)
        ndb.add_property_context(
            NID_SPAM_SEARCH_FOLDER,
            spam_pc,
            parent_nid=NID_ROOT_FOLDER,
        )

        return MessagingBuildResult(
            pst=ndb.build(),
            root_folder_nid=NID_ROOT_FOLDER,
            folder_count=folder_count + search_folders + 2,
            message_count=message_count + search_messages,
            attachment_count=attachment_count + search_attachments,
            ipm_subtree_nid=self.root.nid,
        )

    def _emit_minimum_root(self, ndb: NdbImageBuilder) -> None:
        physical_root = MessagingFolder(
            NID_ROOT_FOLDER,
            "",
            folders=[
                self.root,
                MessagingFolder(NID_SEARCH_ROOT, "Search Root"),
                MessagingFolder(
                    NID_SPAM_SEARCH_FOLDER,
                    "SPAM Search Folder 2",
                ),
            ],
        )

        root_pc = PropertyContext()
        root_pc.set_unicode(PR_DISPLAY_NAME, "")
        root_pc.set_integer32(PR_CONTENT_COUNT, 0)
        root_pc.set_integer32(PR_CONTENT_UNREAD, 0)
        root_pc.set_boolean(PR_SUBFOLDERS, True)
        ndb.add_property_context(
            NID_ROOT_FOLDER,
            root_pc,
            parent_nid=NID_ROOT_FOLDER,
        )

        ndb.add_table_context(
            make_nid(
                NidType.HIERARCHY_TABLE,
                nid_index(NID_ROOT_FOLDER),
            ),
            _build_hierarchy_table(physical_root),
        )
        ndb.add_table_context(
            make_nid(
                NidType.CONTENTS_TABLE,
                nid_index(NID_ROOT_FOLDER),
            ),
            TableContext(),
        )
        ndb.add_table_context(
            make_nid(
                NidType.ASSOC_CONTENTS_TABLE,
                nid_index(NID_ROOT_FOLDER),
            ),
            TableContext(),
        )

    def _emit_folder(
        self,
        ndb: NdbImageBuilder,
        folder: MessagingFolder,
        *,
        parent_nid: int,
    ) -> tuple[int, int, int]:
        folder_pc = PropertyContext()
        folder_pc.set_unicode(PR_DISPLAY_NAME, folder.name)
        folder_pc.set_integer32(PR_CONTENT_COUNT, len(folder.messages))
        folder_pc.set_integer32(PR_CONTENT_UNREAD, _unread_count(folder))
        folder_pc.set_boolean(PR_SUBFOLDERS, bool(folder.folders))
        ndb.add_property_context(
            folder.nid,
            folder_pc,
            parent_nid=parent_nid,
        )

        ndb.add_table_context(
            make_nid(NidType.HIERARCHY_TABLE, folder.index),
            _build_hierarchy_table(folder),
        )
        ndb.add_table_context(
            make_nid(NidType.CONTENTS_TABLE, folder.index),
            _build_contents_table(folder),
        )
        ndb.add_table_context(
            make_nid(NidType.ASSOC_CONTENTS_TABLE, folder.index),
            TableContext(),
        )

        attachment_count = 0
        for message in folder.messages:
            attachment_count += len(message.attachments)
            self._emit_message(ndb, message, parent_nid=folder.nid)

        folder_count = 1
        message_count = len(folder.messages)
        for child in folder.folders:
            child_folders, child_messages, child_attachments = self._emit_folder(
                ndb,
                child,
                parent_nid=folder.nid,
            )
            folder_count += child_folders
            message_count += child_messages
            attachment_count += child_attachments

        return folder_count, message_count, attachment_count

    def _emit_message(
        self,
        ndb: NdbImageBuilder,
        message: MessagingMessage,
        *,
        parent_nid: int,
    ) -> None:
        stored_message = ndb.store_property_context_node(
            _build_message_pc(message)
        )
        subnodes: dict[int, object] = dict(stored_message.subnodes)

        if message.recipients:
            subnodes[NID_RECIPIENT_TABLE] = ndb.store_table_context_node(
                _build_recipient_table(message)
            )

        if message.attachments:
            attachment_table = TableContext()
            attachment_table.add_column(PR_DISPLAY_NAME, 0x001F)
            attachment_table.add_column(PR_ATTACH_SIZE, 0x0003)
            attachment_table.add_column(PR_ATTACH_METHOD, 0x0003)

            for index, attachment in enumerate(message.attachments):
                local_nid = make_nid(NidType.ATTACHMENT, 0x20 + index)
                subnodes[local_nid] = ndb.store_property_context_node(
                    _build_attachment_pc(attachment)
                )
                attachment_table.add_row(
                    local_nid,
                    {
                        PR_DISPLAY_NAME: attachment.filename,
                        PR_ATTACH_SIZE: len(attachment.data),
                        PR_ATTACH_METHOD: ATTACH_BY_VALUE,
                    },
                )

            subnodes[NID_ATTACHMENT_TABLE] = ndb.store_table_context_node(
                attachment_table
            )

        sub_bid = ndb.add_subnode_tree(subnodes) if subnodes else 0
        ndb.add_node(
            message.nid,
            stored_message.data_bid,
            sub_bid=sub_bid,
            parent_nid=parent_nid,
        )


def _build_hierarchy_table(folder: MessagingFolder) -> TableContext:
    table = TableContext()
    table.add_column(PR_DISPLAY_NAME, 0x001F)
    table.add_column(PR_CONTENT_COUNT, 0x0003)
    table.add_column(PR_CONTENT_UNREAD, 0x0003)
    table.add_column(PR_SUBFOLDERS, 0x000B)

    for child in folder.folders:
        table.add_row(
            child.nid,
            {
                PR_DISPLAY_NAME: child.name,
                PR_CONTENT_COUNT: len(child.messages),
                PR_CONTENT_UNREAD: _unread_count(child),
                PR_SUBFOLDERS: bool(child.folders),
            },
        )
    return table


def _build_contents_table(folder: MessagingFolder) -> TableContext:
    table = TableContext()
    table.add_column(PR_MESSAGE_FLAGS, 0x0003)

    if any(message.delivery_filetime is not None for message in folder.messages):
        table.add_column(PR_MESSAGE_DELIVERY_TIME, 0x0040)

    for message in folder.messages:
        values: dict[int, int] = {
            PR_MESSAGE_FLAGS: MSGFLAG_READ if message.is_read else 0,
        }
        if message.delivery_filetime is not None:
            values[PR_MESSAGE_DELIVERY_TIME] = message.delivery_filetime
        table.add_row(message.nid, values)
    return table


def _build_recipient_table(message: MessagingMessage) -> TableContext:
    table = TableContext()
    table.add_column(PR_RECIPIENT_TYPE, 0x0003)
    table.add_column(PR_DISPLAY_NAME, 0x001F)
    table.add_column(PR_ADDRTYPE, 0x001F)
    table.add_column(PR_EMAIL_ADDRESS, 0x001F)
    table.add_column(PR_SMTP_ADDRESS, 0x001F)

    for row_id, recipient in enumerate(message.recipients, start=1):
        table.add_row(
            row_id,
            {
                PR_RECIPIENT_TYPE: recipient.recipient_type,
                PR_DISPLAY_NAME: recipient.name,
                PR_ADDRTYPE: "SMTP",
                PR_EMAIL_ADDRESS: recipient.email,
                PR_SMTP_ADDRESS: recipient.email,
            },
        )
    return table


def _build_message_pc(message: MessagingMessage) -> PropertyContext:
    pc = PropertyContext()
    pc.set_unicode(PR_MESSAGE_CLASS, "IPM.Note")
    pc.set_unicode(PR_SUBJECT, message.subject)
    pc.set_unicode(PR_BODY, message.body)
    pc.set_integer32(
        PR_MESSAGE_FLAGS,
        MSGFLAG_READ if message.is_read else 0,
    )
    pc.set_boolean(PR_HAS_ATTACH, bool(message.attachments))

    if message.sender_name:
        pc.set_unicode(PR_SENDER_NAME, message.sender_name)
    if message.sender_email:
        pc.set_unicode(PR_SENDER_EMAIL_ADDRESS, message.sender_email)
    if message.display_to:
        pc.set_unicode(PR_DISPLAY_TO, message.display_to)
    if message.display_cc:
        pc.set_unicode(PR_DISPLAY_CC, message.display_cc)
    if message.html_body:
        pc.set_binary(PR_HTML, message.html_body)
    if message.rtf_body is not None:
        pc.set_binary(
            PR_RTF_COMPRESSED,
            compress_rtf(message.rtf_body),
        )
    if message.delivery_filetime is not None:
        pc.set_filetime(PR_MESSAGE_DELIVERY_TIME, message.delivery_filetime)
    if message.client_submit_filetime is not None:
        pc.set_filetime(PR_CLIENT_SUBMIT_TIME, message.client_submit_filetime)
    if message.creation_filetime is not None:
        pc.set_filetime(PR_CREATION_TIME, message.creation_filetime)

    return pc


def _build_attachment_pc(attachment: MessagingAttachment) -> PropertyContext:
    pc = PropertyContext()
    pc.set_integer32(PR_ATTACH_METHOD, ATTACH_BY_VALUE)
    pc.set_binary(PR_ATTACH_DATA, attachment.data)
    pc.set_unicode(PR_ATTACH_LONG_FILENAME, attachment.filename)
    pc.set_unicode(PR_ATTACH_FILENAME, attachment.filename)
    pc.set_unicode(PR_DISPLAY_NAME, attachment.filename)
    pc.set_integer32(PR_ATTACH_SIZE, len(attachment.data))
    if attachment.mime_type:
        pc.set_unicode(PR_ATTACH_MIME_TAG, attachment.mime_type)
    return pc


def _unread_count(folder: MessagingFolder) -> int:
    return sum(1 for message in folder.messages if not message.is_read)
