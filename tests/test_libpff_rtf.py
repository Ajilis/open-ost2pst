import tempfile

import pytest

from open_ost2pst.pst.messaging import MessagingBuilder
from open_ost2pst.reader.pff_reader import load_mailbox


pypff = pytest.importorskip("pypff")


def _strip_pypff_rtf_terminator(value: bytes) -> bytes:
    if value.endswith(b"\x00"):
        return value[:-1]
    return value


def test_libpff_reads_large_rtf_body_exactly() -> None:
    rtf = (
        b"{\\rtf1\\ansi\\deff0 "
        + (b"Rich text body with formatting. " * 2000)
        + b"}"
    )

    builder = MessagingBuilder()
    inbox = builder.add_folder(builder.root, "Inbox")
    builder.add_message(
        inbox,
        subject="RTF fidelity",
        body="Plain text fallback",
        rtf_body=rtf,
    )

    result = builder.build()

    with tempfile.NamedTemporaryFile(suffix=".pst") as handle:
        handle.write(result.data)
        handle.flush()

        store = pypff.file()
        store.open(handle.name)
        try:
            root = store.get_root_folder()
            inbox_item = root.get_sub_folder(0)
            message = inbox_item.get_sub_message(0)

            returned = message.get_rtf_body()
            assert returned is not None
            assert _strip_pypff_rtf_terminator(bytes(returned)) == rtf
        finally:
            store.close()

        mailbox, report = load_mailbox(handle.name)
        assert report.messages_failed == 0
        assert mailbox.root.folders[0].messages[0].body_rtf == rtf
