"""Unicode PST writer boundary.

The actual MS-PST NDB/LTP implementation is intentionally not faked here.
This module defines the interface that the converter will target.
"""

from __future__ import annotations

from pathlib import Path

from open_ost2pst.model import Mailbox


class PstWriter:
    """Write the intermediate mailbox model as a Unicode PST."""

    def write(self, mailbox: Mailbox, destination: str | Path) -> None:
        raise NotImplementedError(
            "Unicode PST writing is not implemented yet. "
            "The next milestone is the NDB/LTP writer."
        )
