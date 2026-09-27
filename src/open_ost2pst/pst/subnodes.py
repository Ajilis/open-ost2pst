"""Subnode BTree (SLBLOCK) support for MS-PST NDB."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Mapping

from .primitives import BLOCK_MAX_PAYLOAD


SLBLOCK_TYPE = 0x02
SLBLOCK_LEVEL_LEAF = 0x00
SLBLOCK_HEADER_SIZE = 8
SLENTRY_SIZE = 24
SLBLOCK_MAX_ENTRIES = (BLOCK_MAX_PAYLOAD - SLBLOCK_HEADER_SIZE) // SLENTRY_SIZE


@dataclass(frozen=True, slots=True)
class SubnodeEntry:
    nid: int
    data_bid: int
    sub_bid: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.nid <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("subnode NID must fit in 64 bits")
        if not 0 <= self.data_bid <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("subnode data BID must fit in 64 bits")
        if not 0 <= self.sub_bid <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("subnode sub BID must fit in 64 bits")

    def pack(self) -> bytes:
        return struct.pack("<QQQ", self.nid, self.data_bid, self.sub_bid)


def pack_slblock(entries: list[SubnodeEntry] | tuple[SubnodeEntry, ...]) -> bytes:
    """Serialize one subnode leaf block (SLBLOCK).

    This milestone supports a single leaf block. Larger subnode sets will need
    SIBLOCK intermediate nodes.
    """

    ordered = sorted(entries, key=lambda entry: entry.nid)
    if len(ordered) > SLBLOCK_MAX_ENTRIES:
        raise ValueError(
            "subnode set exceeds one SLBLOCK; SIBLOCK support is required"
        )

    previous: int | None = None
    for entry in ordered:
        if previous is not None and entry.nid == previous:
            raise ValueError(f"duplicate subnode NID: {entry.nid:#x}")
        previous = entry.nid

    payload = bytearray(
        struct.pack(
            "<BBHI",
            SLBLOCK_TYPE,
            SLBLOCK_LEVEL_LEAF,
            len(ordered),
            0,
        )
    )
    for entry in ordered:
        payload.extend(entry.pack())

    if len(payload) > BLOCK_MAX_PAYLOAD:
        raise AssertionError("SLBLOCK payload exceeds NDB block limit")
    return bytes(payload)


def parse_slblock(payload: bytes) -> tuple[SubnodeEntry, ...]:
    if len(payload) < SLBLOCK_HEADER_SIZE:
        raise ValueError("SLBLOCK payload is truncated")

    btype, level, count, _padding = struct.unpack_from("<BBHI", payload, 0)
    if btype != SLBLOCK_TYPE or level != SLBLOCK_LEVEL_LEAF:
        raise ValueError("payload is not a leaf SLBLOCK")

    expected = SLBLOCK_HEADER_SIZE + count * SLENTRY_SIZE
    if len(payload) != expected:
        raise ValueError("SLBLOCK payload size does not match entry count")

    entries = []
    offset = SLBLOCK_HEADER_SIZE
    for _ in range(count):
        nid, data_bid, sub_bid = struct.unpack_from("<QQQ", payload, offset)
        entries.append(SubnodeEntry(nid, data_bid, sub_bid))
        offset += SLENTRY_SIZE
    return tuple(entries)
