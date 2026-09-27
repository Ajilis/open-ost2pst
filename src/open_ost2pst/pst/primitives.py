"""Low-level primitives for Unicode (64-bit) MS-PST files."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct


UINT32_MAX = 0xFFFFFFFF
UINT64_MAX = 0xFFFFFFFFFFFFFFFF
NID_INDEX_MAX = 0x07FFFFFF

BID_RESERVED = 0x01
BID_INTERNAL = 0x02

PAGE_SIZE = 512
PAGE_TRAILER_SIZE = 16
BLOCK_TRAILER_SIZE = 16
BLOCK_ALIGNMENT = 64


class NidType(IntEnum):
    HID = 0x00
    INTERNAL = 0x01
    NORMAL_FOLDER = 0x02
    SEARCH_FOLDER = 0x03
    NORMAL_MESSAGE = 0x04
    ATTACHMENT = 0x05
    SEARCH_UPDATE_QUEUE = 0x06
    SEARCH_CRITERIA_OBJECT = 0x07
    ASSOC_MESSAGE = 0x08
    CONTENTS_TABLE_INDEX = 0x0A
    RECEIVE_FOLDER_TABLE = 0x0B
    OUTGOING_QUEUE_TABLE = 0x0C
    HIERARCHY_TABLE = 0x0D
    CONTENTS_TABLE = 0x0E
    ASSOC_CONTENTS_TABLE = 0x0F
    SEARCH_CONTENTS_TABLE = 0x10
    ATTACHMENT_TABLE = 0x11
    RECIPIENT_TABLE = 0x12
    SEARCH_TABLE_INDEX = 0x13
    LTP = 0x1F


def make_nid(nid_type: int | NidType, nid_index: int) -> int:
    """Pack a 5-bit NID type and 27-bit index into a 32-bit NID."""

    type_value = int(nid_type)
    if not 0 <= type_value <= 0x1F:
        raise ValueError("nid_type must fit in 5 bits")
    if not 0 <= nid_index <= NID_INDEX_MAX:
        raise ValueError("nid_index must fit in 27 bits")
    return (nid_index << 5) | type_value


def nid_type(nid: int) -> int:
    _validate_uint32(nid, "nid")
    return nid & 0x1F


def nid_index(nid: int) -> int:
    _validate_uint32(nid, "nid")
    return (nid >> 5) & NID_INDEX_MAX


def make_block_bid(bid_index: int, *, internal: bool = False) -> int:
    """Pack a 62-bit block BID index with the MS-PST low-bit flags."""

    if not 0 <= bid_index <= (UINT64_MAX >> 2):
        raise ValueError("bid_index must fit in 62 bits")
    return (bid_index << 2) | (BID_INTERNAL if internal else 0)


def bid_index(bid: int) -> int:
    _validate_uint64(bid, "bid")
    return bid >> 2


def is_internal_bid(bid: int) -> bool:
    _validate_uint64(bid, "bid")
    return bool(bid & BID_INTERNAL)


def canonical_bid(bid: int) -> int:
    """Clear the reserved bit before a BBT lookup, as required by MS-PST."""

    _validate_uint64(bid, "bid")
    return bid & ~BID_RESERVED


def compute_sig(ib: int, bid: int) -> int:
    """Return the 16-bit page/block signature from MS-PST section 5.5."""

    _validate_uint64(ib, "ib")
    _validate_uint64(bid, "bid")
    value = (ib ^ bid) & UINT32_MAX
    return ((value >> 16) ^ value) & 0xFFFF


def block_aligned_size(payload_size: int) -> int:
    """On-disk block footprint including trailer, rounded to 64 bytes."""

    if payload_size < 0:
        raise ValueError("payload_size must be non-negative")
    total = payload_size + BLOCK_TRAILER_SIZE
    return (total + BLOCK_ALIGNMENT - 1) & ~(BLOCK_ALIGNMENT - 1)


@dataclass(frozen=True, slots=True)
class BRef:
    """Unicode BREF: a BID plus its absolute file offset (IB)."""

    bid: int
    ib: int

    def __post_init__(self) -> None:
        _validate_uint64(self.bid, "bid")
        _validate_uint64(self.ib, "ib")

    def pack(self) -> bytes:
        return struct.pack("<QQ", self.bid, self.ib)

    @classmethod
    def unpack(cls, data: bytes) -> "BRef":
        if len(data) != 16:
            raise ValueError("Unicode BREF must be exactly 16 bytes")
        bid, ib = struct.unpack("<QQ", data)
        return cls(bid=bid, ib=ib)


@dataclass(slots=True)
class BlockBidAllocator:
    """Allocate raw block BID values; the base counter advances by four."""

    next_bid: int = 4

    def __post_init__(self) -> None:
        _validate_uint64(self.next_bid, "next_bid")
        if self.next_bid & 0x03:
            raise ValueError("next_bid must have its two low bits clear")

    def allocate(self, *, internal: bool = False) -> int:
        if self.next_bid > UINT64_MAX - 4:
            raise OverflowError("block BID space exhausted")
        bid = self.next_bid | (BID_INTERNAL if internal else 0)
        self.next_bid += 4
        return bid


@dataclass(slots=True)
class PageBidAllocator:
    """Allocate page BIDs, which use all bits and advance by one."""

    next_bid: int = 1

    def __post_init__(self) -> None:
        _validate_uint64(self.next_bid, "next_bid")

    def allocate(self) -> int:
        if self.next_bid == UINT64_MAX:
            raise OverflowError("page BID space exhausted")
        bid = self.next_bid
        self.next_bid += 1
        return bid


def _validate_uint32(value: int, name: str) -> None:
    if not isinstance(value, int) or not 0 <= value <= UINT32_MAX:
        raise ValueError(f"{name} must be an unsigned 32-bit integer")


def _validate_uint64(value: int, name: str) -> None:
    if not isinstance(value, int) or not 0 <= value <= UINT64_MAX:
        raise ValueError(f"{name} must be an unsigned 64-bit integer")
