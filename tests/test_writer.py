import pytest

from open_ost2pst.model import Folder, Mailbox
from open_ost2pst.pst import PstWriter


def test_writer_is_explicitly_not_implemented(tmp_path) -> None:
    mailbox = Mailbox(Folder("root"))

    with pytest.raises(NotImplementedError):
        PstWriter().write(mailbox, tmp_path / "output.pst")
