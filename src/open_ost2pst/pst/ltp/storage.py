"""Shared LTP helpers for values stored outside the heap."""

from __future__ import annotations

from dataclasses import dataclass

from open_ost2pst.binary_payload import BinaryData

from ..primitives import NidType, make_nid


@dataclass(frozen=True, slots=True)
class ExternalValue:
    """One HNID-backed value stored as a local LTP subnode.

    block_payload_size and pad_nonfinal_to_max are used by Table Context
    Row Matrices. MS-PST requires rows to remain wholly inside one data
    block, and every non-final Row Matrix block to occupy a full 8192-byte
    physical block.
    """

    nid: int
    data: BinaryData
    block_payload_size: int | None = None
    pad_nonfinal_to_max: bool = False


class LtpNidAllocator:
    """Allocate local NIDs with NID_TYPE_LTP for one owning node."""

    def __init__(self, start_index: int = 1) -> None:
        if start_index < 1:
            raise ValueError("LTP NID index must start at 1 or greater")
        self._next_index = start_index

    def allocate(self) -> int:
        nid = make_nid(NidType.LTP, self._next_index)
        self._next_index += 1
        return nid
