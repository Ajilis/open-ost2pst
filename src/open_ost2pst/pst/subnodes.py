"""Subnode BTree (SLBLOCK/SIBLOCK) support for MS-PST NDB."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterable

from .primitives import BID_INTERNAL, BLOCK_MAX_PAYLOAD


SUBNODE_BLOCK_TYPE = 0x02
SLBLOCK_TYPE = SUBNODE_BLOCK_TYPE
SIBLOCK_TYPE = SUBNODE_BLOCK_TYPE
SLBLOCK_LEVEL_LEAF = 0x00
SIBLOCK_LEVEL_INTERMEDIATE = 0x01
SUBNODE_BLOCK_HEADER_SIZE = 8

SLENTRY_SIZE = 24
SIENTRY_SIZE = 16

SLBLOCK_MAX_ENTRIES = (
    BLOCK_MAX_PAYLOAD - SUBNODE_BLOCK_HEADER_SIZE
) // SLENTRY_SIZE
SIBLOCK_MAX_ENTRIES = (
    BLOCK_MAX_PAYLOAD - SUBNODE_BLOCK_HEADER_SIZE
) // SIENTRY_SIZE
SUBNODE_TREE_MAX_ENTRIES = SLBLOCK_MAX_ENTRIES * SIBLOCK_MAX_ENTRIES


@dataclass(frozen=True, slots=True)
class SubnodeEntry:
    """Unicode SLENTRY."""

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


@dataclass(frozen=True, slots=True)
class SubnodeIntermediateEntry:
    """Unicode SIENTRY."""

    nid: int
    bid: int

    def __post_init__(self) -> None:
        if not 0 <= self.nid <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("SIENTRY NID must fit in 64 bits")
        if not 0 <= self.bid <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("SIENTRY BID must fit in 64 bits")
        if not (self.bid & BID_INTERNAL):
            raise ValueError("SIENTRY BID must reference an internal SLBLOCK")

    def pack(self) -> bytes:
        return struct.pack("<QQ", self.nid, self.bid)


def pack_slblock(
    entries: Iterable[SubnodeEntry],
) -> bytes:
    """Serialize one Unicode subnode leaf block."""

    ordered = tuple(sorted(entries, key=lambda entry: entry.nid))
    _validate_nonempty_unique_nids(ordered)

    if len(ordered) > SLBLOCK_MAX_ENTRIES:
        raise ValueError(
            f"SLBLOCK exceeds {SLBLOCK_MAX_ENTRIES} entries; "
            "use a SIBLOCK root"
        )

    payload = bytearray(
        struct.pack(
            "<BBHI",
            SUBNODE_BLOCK_TYPE,
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


def pack_siblock(
    entries: Iterable[SubnodeIntermediateEntry],
) -> bytes:
    """Serialize one Unicode subnode intermediate block.

    Each SIENTRY key is the first NID stored in the corresponding child
    SLBLOCK.
    """

    ordered = tuple(sorted(entries, key=lambda entry: entry.nid))
    _validate_nonempty_unique_nids(ordered)

    if len(ordered) > SIBLOCK_MAX_ENTRIES:
        raise ValueError(
            f"SIBLOCK exceeds {SIBLOCK_MAX_ENTRIES} entries"
        )

    payload = bytearray(
        struct.pack(
            "<BBHI",
            SUBNODE_BLOCK_TYPE,
            SIBLOCK_LEVEL_INTERMEDIATE,
            len(ordered),
            0,
        )
    )
    for entry in ordered:
        payload.extend(entry.pack())

    if len(payload) > BLOCK_MAX_PAYLOAD:
        raise AssertionError("SIBLOCK payload exceeds NDB block limit")
    return bytes(payload)


def parse_slblock(payload: bytes) -> tuple[SubnodeEntry, ...]:
    btype, level, count = _parse_header(payload)
    if btype != SUBNODE_BLOCK_TYPE or level != SLBLOCK_LEVEL_LEAF:
        raise ValueError("payload is not a leaf SLBLOCK")
    if count == 0 or count > SLBLOCK_MAX_ENTRIES:
        raise ValueError("invalid SLBLOCK entry count")

    expected = SUBNODE_BLOCK_HEADER_SIZE + count * SLENTRY_SIZE
    if len(payload) != expected:
        raise ValueError("SLBLOCK payload size does not match entry count")

    entries: list[SubnodeEntry] = []
    offset = SUBNODE_BLOCK_HEADER_SIZE
    for _ in range(count):
        nid, data_bid, sub_bid = struct.unpack_from("<QQQ", payload, offset)
        entries.append(SubnodeEntry(nid, data_bid, sub_bid))
        offset += SLENTRY_SIZE

    _validate_sorted_unique(entries)
    return tuple(entries)


def parse_siblock(
    payload: bytes,
) -> tuple[SubnodeIntermediateEntry, ...]:
    btype, level, count = _parse_header(payload)
    if (
        btype != SUBNODE_BLOCK_TYPE
        or level != SIBLOCK_LEVEL_INTERMEDIATE
    ):
        raise ValueError("payload is not a SIBLOCK")
    if count == 0 or count > SIBLOCK_MAX_ENTRIES:
        raise ValueError("invalid SIBLOCK entry count")

    expected = SUBNODE_BLOCK_HEADER_SIZE + count * SIENTRY_SIZE
    if len(payload) != expected:
        raise ValueError("SIBLOCK payload size does not match entry count")

    entries: list[SubnodeIntermediateEntry] = []
    offset = SUBNODE_BLOCK_HEADER_SIZE
    for _ in range(count):
        nid, bid = struct.unpack_from("<QQ", payload, offset)
        entries.append(SubnodeIntermediateEntry(nid, bid))
        offset += SIENTRY_SIZE

    _validate_sorted_unique(entries)
    return tuple(entries)


def split_slblock_entries(
    entries: Iterable[SubnodeEntry],
) -> tuple[tuple[SubnodeEntry, ...], ...]:
    """Sort entries and split them into SLBLOCK-sized groups."""

    ordered = tuple(sorted(entries, key=lambda entry: entry.nid))
    _validate_nonempty_unique_nids(ordered)

    if len(ordered) > SUBNODE_TREE_MAX_ENTRIES:
        raise ValueError(
            "subnode tree exceeds one SIBLOCK level: "
            f"{len(ordered)} > {SUBNODE_TREE_MAX_ENTRIES}"
        )

    return tuple(
        ordered[start : start + SLBLOCK_MAX_ENTRIES]
        for start in range(0, len(ordered), SLBLOCK_MAX_ENTRIES)
    )


def _parse_header(payload: bytes) -> tuple[int, int, int]:
    if len(payload) < SUBNODE_BLOCK_HEADER_SIZE:
        raise ValueError("subnode block payload is truncated")

    btype, level, count, padding = struct.unpack_from("<BBHI", payload, 0)
    if padding != 0:
        raise ValueError("subnode block padding must be zero")
    return btype, level, count


def _validate_nonempty_unique_nids(entries: tuple[object, ...]) -> None:
    if not entries:
        raise ValueError("subnode block must contain at least one entry")
    _validate_sorted_unique(entries)


def _validate_sorted_unique(entries: Iterable[object]) -> None:
    previous: int | None = None
    for entry in entries:
        nid = int(getattr(entry, "nid"))
        if previous is not None and nid <= previous:
            if nid == previous:
                raise ValueError(f"duplicate subnode NID: {nid:#x}")
            raise ValueError("subnode NIDs must be strictly increasing")
        previous = nid
