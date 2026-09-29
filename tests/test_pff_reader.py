from __future__ import annotations

from datetime import datetime

from open_ost2pst.binary_payload import TemporaryBinaryPayload
from open_ost2pst.reader import pff_reader


class FakeEntry:
    def __init__(self, *, string=None, integer=None):
        self.data_as_string = string
        self.data_as_integer = integer


class FakeRecordSet:
    def __init__(self, values=None):
        self.values = values or {}

    def get_entry_by_type(self, property_id):
        return self.values.get(property_id)


class FakeRecipients:
    def __init__(self, rows):
        self.rows = rows
        self.number_of_recipients = len(rows)

    def get_recipient(self, index):
        return self.rows[index]


class FakeAttachment:
    def __init__(self, filename, data, mime_type=None):
        self.long_filename = filename
        self._data = data
        self._offset = 0
        self.size = len(data)
        self._record_set = FakeRecordSet(
            {
                pff_reader.PR_ATTACH_MIME_TAG: FakeEntry(string=mime_type)
                if mime_type
                else None
            }
        )

    def get_record_set(self, index):
        assert index == 0
        return self._record_set

    def seek_offset(self, offset, whence=0):
        assert whence == 0
        self._offset = offset

    def read_buffer(self, size):
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class FakeMessage:
    def __init__(self, *, attachments=None, broken_attachment=False):
        self.subject = "Hello OST"
        self.sender_name = "Alice Example"
        self.plain_text_body = "Bonjour".encode("utf-8")
        self.html_body = "<p>Bonjour</p>".encode("utf-8")
        self.rtf_body = b"{\\rtf1 Bonjour}"
        self.delivery_time = datetime(2026, 9, 27, 10, 30)
        self.creation_time = datetime(2026, 9, 27, 10, 0)
        self.transport_headers = "From: Alice Example <alice@example.com>\r\n"
        self.recipients = FakeRecipients(
            [
                FakeRecordSet(
                    {
                        pff_reader.PR_DISPLAY_NAME: FakeEntry(string="Bob"),
                        pff_reader.PR_SMTP_ADDRESS: FakeEntry(
                            string="bob@example.com"
                        ),
                        pff_reader.PR_RECIPIENT_TYPE: FakeEntry(integer=1),
                    }
                ),
                FakeRecordSet(
                    {
                        pff_reader.PR_DISPLAY_NAME: FakeEntry(string="Carol"),
                        pff_reader.PR_EMAIL_ADDRESS: FakeEntry(
                            string="carol@example.com"
                        ),
                        pff_reader.PR_RECIPIENT_TYPE: FakeEntry(integer=2),
                    }
                ),
            ]
        )
        self._attachments = attachments or []
        self.number_of_attachments = len(self._attachments)
        self._broken_attachment = broken_attachment
        self._record_set = FakeRecordSet(
            {
                pff_reader.PR_SENDER_SMTP_ADDRESS: FakeEntry(
                    string="alice@example.com"
                ),
                pff_reader.PR_MESSAGE_FLAGS: FakeEntry(
                    integer=pff_reader.MESSAGE_FLAG_READ
                ),
            }
        )

    def get_record_set(self, index):
        assert index == 0
        return self._record_set

    def get_attachment(self, index):
        if self._broken_attachment:
            raise OSError("corrupt attachment")
        return self._attachments[index]


class FakeFolder:
    def __init__(self, name, *, messages=None, folders=None):
        self.name = name
        self._messages = messages or []
        self._folders = folders or []
        self.number_of_sub_messages = len(self._messages)
        self.number_of_sub_folders = len(self._folders)

    def get_sub_message(self, index):
        return self._messages[index]

    def get_sub_folder(self, index):
        return self._folders[index]


class FakeStore:
    def __init__(self, root):
        self.root = root
        self.opened = False
        self.closed = False

    def open(self, path):
        self.opened = True

    def get_root_folder(self):
        return self.root

    def close(self):
        self.closed = True


class FakePypff:
    def __init__(self, store):
        self.store = store

    def file(self):
        return self.store


def _install_fake_pypff(monkeypatch, root):
    store = FakeStore(root)
    monkeypatch.setattr(
        pff_reader,
        "_load_pypff",
        lambda: FakePypff(store),
    )
    return store


def test_load_mailbox_extracts_messages_recipients_and_attachments(
    monkeypatch, tmp_path
):
    attachment = FakeAttachment(
        "invoice.pdf",
        b"PDF-DATA",
        mime_type="application/pdf",
    )
    message = FakeMessage(attachments=[attachment])
    root = FakeFolder(
        "Root",
        folders=[FakeFolder("Inbox", messages=[message])],
    )
    store = _install_fake_pypff(monkeypatch, root)

    source = tmp_path / "mailbox.ost"
    source.write_bytes(b"fake")

    mailbox, report = pff_reader.load_mailbox(source)

    assert store.opened is True
    assert store.closed is True

    assert mailbox.folder_count == 2
    assert mailbox.message_count == 1
    assert mailbox.attachment_count == 1

    extracted = mailbox.root.folders[0].messages[0]
    assert extracted.subject == "Hello OST"
    assert extracted.sender_name == "Alice Example"
    assert extracted.sender_email == "alice@example.com"
    assert extracted.body_text == "Bonjour"
    assert extracted.body_html == "<p>Bonjour</p>"
    assert extracted.body_rtf == b"{\\rtf1 Bonjour}"
    assert extracted.is_read is True

    assert [(r.name, r.email, r.recipient_type) for r in extracted.recipients] == [
        ("Bob", "bob@example.com", "to"),
        ("Carol", "carol@example.com", "cc"),
    ]

    assert extracted.attachments[0].filename == "invoice.pdf"
    assert extracted.attachments[0].mime_type == "application/pdf"
    assert extracted.attachments[0].data == b"PDF-DATA"

    assert report.folders_seen == 2
    assert report.folders_loaded == 2
    assert report.messages_seen == 1
    assert report.messages_loaded == 1
    assert report.messages_failed == 0
    assert report.attachments_seen == 1
    assert report.attachments_loaded == 1
    assert report.attachments_failed == 0
    assert report.warnings == []


def test_load_mailbox_skips_corrupt_attachment(monkeypatch, tmp_path):
    message = FakeMessage(
        attachments=[FakeAttachment("broken.bin", b"broken")],
        broken_attachment=True,
    )
    root = FakeFolder("Root", messages=[message])
    _install_fake_pypff(monkeypatch, root)

    source = tmp_path / "damaged.ost"
    source.write_bytes(b"fake")

    mailbox, report = pff_reader.load_mailbox(source)

    assert mailbox.message_count == 1
    assert mailbox.attachment_count == 0
    assert report.messages_loaded == 1
    assert report.attachments_seen == 1
    assert report.attachments_loaded == 0
    assert report.attachments_failed == 1
    assert len(report.warnings) == 1
    assert "corrupt attachment" in report.warnings[0]


def test_decode_body_falls_back_to_windows_1252():
    assert pff_reader._decode_body(b"caf\xe9") == "café"


def test_normalize_rtf_body_removes_pypff_terminal_null() -> None:
    assert pff_reader._normalize_rtf_body(
        b"{\\rtf1\\ansi test}\x00"
    ) == b"{\\rtf1\\ansi test}"
    assert pff_reader._normalize_rtf_body(
        b"{\\rtf1\\ansi test}"
    ) == b"{\\rtf1\\ansi test}"
    assert pff_reader._normalize_rtf_body(None) is None


class LegacyFakeEntry:
    def __init__(
        self,
        entry_type,
        value_type,
        *,
        string=None,
        integer=None,
        floating=None,
        boolean=None,
        dt=None,
        data=None,
    ):
        self._entry_type = entry_type
        self._value_type = value_type
        self._string = string
        self._integer = integer
        self._floating = floating
        self._boolean = boolean
        self._datetime = dt
        self._data = data

    def get_entry_type(self):
        return self._entry_type

    def get_value_type(self):
        return self._value_type

    def get_data_as_string(self):
        return self._string

    def get_data_as_integer(self):
        return self._integer

    def get_data_as_floating_point(self):
        return self._floating

    def get_data_as_boolean(self):
        return self._boolean

    def get_data_as_datetime(self):
        return self._datetime

    def get_data(self):
        return self._data


class LegacyFakeRecordSet:
    def __init__(self, entries):
        self._entries = list(entries)

    def get_number_of_entries(self):
        return len(self._entries)

    def get_entry(self, index):
        return self._entries[index]


class LegacyFakeItem:
    def __init__(self, entries):
        self._record_set = LegacyFakeRecordSet(entries)

    def get_record_set(self, index):
        assert index == 0
        return self._record_set


def test_legacy_pypff_record_getters_support_standard_properties() -> None:
    item = LegacyFakeItem(
        [
            LegacyFakeEntry(
                pff_reader.PR_MESSAGE_CLASS,
                pff_reader.PT_UNICODE,
                string="IPM.Note.Custom",
            ),
            LegacyFakeEntry(
                pff_reader.PR_IMPORTANCE,
                pff_reader.PT_INTEGER32,
                integer=2,
            ),
            LegacyFakeEntry(
                pff_reader.PR_CONVERSATION_INDEX,
                pff_reader.PT_BINARY,
                data=b"conversation-index",
            ),
        ]
    )

    assert (
        pff_reader._property_string(
            item,
            pff_reader.PR_MESSAGE_CLASS,
        )
        == "IPM.Note.Custom"
    )
    assert (
        pff_reader._property_integer(
            item,
            pff_reader.PR_IMPORTANCE,
        )
        == 2
    )
    assert (
        pff_reader._property_binary(
            item,
            pff_reader.PR_CONVERSATION_INDEX,
        )
        == b"conversation-index"
    )


def test_legacy_pypff_record_getters_support_named_properties() -> None:
    property_id = 0x8001
    definitions = {
        property_id: pff_reader._NameIdDefinition(
            guid=None,
            name="X-Legacy",
        )
    }
    item = LegacyFakeItem(
        [
            LegacyFakeEntry(
                property_id,
                pff_reader.PT_UNICODE,
                string="legacy-value",
            )
        ]
    )
    report = pff_reader.ExtractionReport(path="legacy.pst")

    values = pff_reader._extract_named_properties(
        item,
        definitions,
        report,
    )

    assert len(values) == 1
    assert values[0].name == "X-Legacy"
    assert values[0].property_type == pff_reader.PT_UNICODE
    assert values[0].value == "legacy-value"
    assert report.warnings == []


def test_large_attachment_uses_temporary_payload_and_cleanup(
    monkeypatch,
    tmp_path,
) -> None:
    data = b"x" * (pff_reader.ATTACHMENT_STREAM_THRESHOLD + 123)
    attachment = FakeAttachment(
        "large.bin",
        data,
        mime_type="application/octet-stream",
    )
    message = FakeMessage(attachments=[attachment])
    root = FakeFolder(
        "Root",
        folders=[FakeFolder("Inbox", messages=[message])],
    )
    _install_fake_pypff(monkeypatch, root)

    source = tmp_path / "large.ost"
    source.write_bytes(b"fake")

    mailbox, report = pff_reader.load_mailbox(source)
    payload = mailbox.root.folders[0].messages[0].attachments[0].data

    assert isinstance(payload, TemporaryBinaryPayload)
    payload_path = payload.path
    assert payload_path.parent == source.parent
    assert payload_path.exists()
    assert len(payload) == len(data)
    assert payload == data
    assert report.attachments_streamed == 1
    assert report.attachment_temp_bytes == len(data)
    assert payload.closed is False

    mailbox.cleanup()
    assert payload.closed is True
    assert payload_path.exists() is False
