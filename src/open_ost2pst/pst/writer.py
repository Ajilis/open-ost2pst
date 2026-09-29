"""Unicode PST writer backed by the NDB/LTP/Messaging stack."""

from __future__ import annotations

from pathlib import Path

from open_ost2pst.model import Mailbox

from .bridge import WriteReport, mailbox_to_messaging


class PstWriter:
    """Write the intermediate mailbox model as a Unicode PST."""

    def __init__(self, *, store_name: str = "Open OST2PST Store") -> None:
        self.store_name = store_name

    def write(
        self,
        mailbox: Mailbox,
        destination: str | Path,
    ) -> WriteReport:
        target = Path(destination)

        builder, report = mailbox_to_messaging(
            mailbox,
            store_name=self.store_name,
        )
        builder.write(target)
        return report
