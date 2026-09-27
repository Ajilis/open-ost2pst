"""Shared LTP helpers for values stored outside the heap."""

from __future__ import annotations

from dataclasses import dataclass

from ..primitives import NidType, make_nid


@dataclass(frozen=True, slots=True)
class ExternalValue:
    """One HNID-backed value stored as a local LTP subnode."""

    nid: int
    data: bytes


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
