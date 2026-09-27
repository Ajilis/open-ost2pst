"""Unicode PST NDB header structures.

This module only serializes the fixed header/root structures. BBT/NBT page
construction is intentionally kept separate and is the next milestone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import struct

from .crc import compute_crc
from .primitives import BRef, NidType, UINT64_MAX


HEADER_SIZE = 564
ROOT_SIZE = 72

MAGIC = b"!BDN"
MAGIC_CLIENT = 0x4D53
UNICODE_VERSION = 23
CLIENT_VERSION = 19

CRYPT_NONE = 0x00
SENTINEL = 0x80

HEADER_PARTIAL_CRC_OFFSET = 4
HEADER_PARTIAL_CRC_START = 8
HEADER_PARTIAL_CRC_LENGTH = 471

HEADER_FULL_CRC_OFFSET = 524
HEADER_FULL_CRC_START = 8
HEADER_FULL_CRC_LENGTH = 516

OFFSET_BID_NEXT_P = 32
OFFSET_UNIQUE = 40
OFFSET_RGNID = 44
OFFSET_ROOT = 180
OFFSET_RGB_FM = 256
OFFSET_RGB_FP = 384
OFFSET_SENTINEL = 512
OFFSET_CRYPT_METHOD = 513
OFFSET_BID_NEXT_B = 516

VALID_AMAP = 0x02
INVALID_AMAP = 0x00


def initial_rgnid() -> tuple[int, ...]:
    """Return the 32 initial NID-index counters prescribed by MS-PST."""

    values = [0x400] * 32
    values[int(NidType.NORMAL_FOLDER)] = 0x400
    values[int(NidType.SEARCH_FOLDER)] = 0x4000
    values[int(NidType.NORMAL_MESSAGE)] = 0x10000
    values[int(NidType.ASSOC_MESSAGE)] = 0x8000
    return tuple(values)


@dataclass(frozen=True, slots=True)
class Root:
    """The 72-byte Unicode ROOT structure."""

    file_eof: int
    amap_last: int
    amap_free: int = 0
    pmap_free: int = 0
    nbt_root: BRef = BRef(0, 0)
    bbt_root: BRef = BRef(0, 0)
    amap_valid: int = INVALID_AMAP

    def __post_init__(self) -> None:
        for name in ("file_eof", "amap_last", "amap_free", "pmap_free"):
            value = getattr(self, name)
            if not isinstance(value, int) or not 0 <= value <= UINT64_MAX:
                raise ValueError(f"{name} must be an unsigned 64-bit integer")
        if self.amap_valid not in (INVALID_AMAP, 0x01, VALID_AMAP):
            raise ValueError("amap_valid must be a defined MS-PST AMap state")

    def pack(self) -> bytes:
        data = struct.pack(
            "<IQQQQQQQQBBH",
            0,
            self.file_eof,
            self.amap_last,
            self.amap_free,
            self.pmap_free,
            self.nbt_root.bid,
            self.nbt_root.ib,
            self.bbt_root.bid,
            self.bbt_root.ib,
            self.amap_valid,
            0,
            0,
        )
        assert len(data) == ROOT_SIZE
        return data

    @classmethod
    def unpack(cls, data: bytes) -> "Root":
        if len(data) != ROOT_SIZE:
            raise ValueError("Unicode ROOT must be exactly 72 bytes")
        (
            _reserved,
            file_eof,
            amap_last,
            amap_free,
            pmap_free,
            nbt_bid,
            nbt_ib,
            bbt_bid,
            bbt_ib,
            amap_valid,
            _b_reserved,
            _w_reserved,
        ) = struct.unpack("<IQQQQQQQQBBH", data)
        return cls(
            file_eof=file_eof,
            amap_last=amap_last,
            amap_free=amap_free,
            pmap_free=pmap_free,
            nbt_root=BRef(nbt_bid, nbt_ib),
            bbt_root=BRef(bbt_bid, bbt_ib),
            amap_valid=amap_valid,
        )


@dataclass(frozen=True, slots=True)
class UnicodeHeader:
    """Serializable 564-byte Unicode PST HEADER."""

    root: Root
    bid_next_p: int = 1
    bid_next_b: int = 4
    unique: int = 1
    rgnid: tuple[int, ...] = field(default_factory=initial_rgnid)
    crypt_method: int = CRYPT_NONE

    def __post_init__(self) -> None:
        for name in ("bid_next_p", "bid_next_b"):
            value = getattr(self, name)
            if not isinstance(value, int) or not 0 <= value <= UINT64_MAX:
                raise ValueError(f"{name} must be an unsigned 64-bit integer")
        if self.bid_next_b & 0x03:
            raise ValueError("bid_next_b must have its two low bits clear")
        if not isinstance(self.unique, int) or not 0 <= self.unique <= 0xFFFFFFFF:
            raise ValueError("unique must be an unsigned 32-bit integer")
        if len(self.rgnid) != 32:
            raise ValueError("rgnid must contain exactly 32 counters")
        for value in self.rgnid:
            if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
                raise ValueError("each rgnid counter must fit in 32 bits")
        if self.crypt_method not in (0x00, 0x01, 0x02, 0x10):
            raise ValueError("unsupported MS-PST crypt method")

    def pack(self) -> bytes:
        header = bytearray(HEADER_SIZE)

        header[0:4] = MAGIC
        struct.pack_into("<H", header, 8, MAGIC_CLIENT)
        struct.pack_into("<H", header, 10, UNICODE_VERSION)
        struct.pack_into("<H", header, 12, CLIENT_VERSION)
        header[14] = 0x01
        header[15] = 0x01

        # Reserved fields and bidUnused remain zero-filled.
        struct.pack_into("<Q", header, OFFSET_BID_NEXT_P, self.bid_next_p)
        struct.pack_into("<I", header, OFFSET_UNIQUE, self.unique)

        for index, value in enumerate(self.rgnid):
            struct.pack_into("<I", header, OFFSET_RGNID + index * 4, value)

        header[OFFSET_ROOT : OFFSET_ROOT + ROOT_SIZE] = self.root.pack()

        # Deprecated maps are required to be all 0xFF.
        header[OFFSET_RGB_FM : OFFSET_RGB_FM + 128] = b"\xFF" * 128
        header[OFFSET_RGB_FP : OFFSET_RGB_FP + 128] = b"\xFF" * 128

        header[OFFSET_SENTINEL] = SENTINEL
        header[OFFSET_CRYPT_METHOD] = self.crypt_method
        struct.pack_into("<Q", header, OFFSET_BID_NEXT_B, self.bid_next_b)

        full_crc = compute_crc(
            header[
                HEADER_FULL_CRC_START :
                HEADER_FULL_CRC_START + HEADER_FULL_CRC_LENGTH
            ]
        )
        struct.pack_into("<I", header, HEADER_FULL_CRC_OFFSET, full_crc)

        partial_crc = compute_crc(
            header[
                HEADER_PARTIAL_CRC_START :
                HEADER_PARTIAL_CRC_START + HEADER_PARTIAL_CRC_LENGTH
            ]
        )
        struct.pack_into("<I", header, HEADER_PARTIAL_CRC_OFFSET, partial_crc)

        return bytes(header)
