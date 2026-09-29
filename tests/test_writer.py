from open_ost2pst.model import Folder, Mailbox, Message
from open_ost2pst.pst import PstWriter


def test_writer_creates_unicode_pst_image(tmp_path) -> None:
    mailbox = Mailbox(
        Folder(
            "root",
            messages=[
                Message(
                    subject="Hello",
                    body_text="Body",
                )
            ],
        )
    )
    destination = tmp_path / "output.pst"

    report = PstWriter().write(mailbox, destination)

    assert destination.is_file()
    assert destination.read_bytes()[:4] == b"!BDN"
    assert not list(tmp_path.glob(".output.pst.*.partial"))
    assert report.folders_written == 1
    assert report.messages_written == 1
