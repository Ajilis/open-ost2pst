"""Physical Unicode PST data-block serialization and layout."""

from __future__ import annotations

from dataclasses import dataclass, field
import struct
from typing import Iterable

from .btree import BbtEntry
from .crc import compute_crc
from .primitives import (
    BID_INTERNAL,
    BLOCK_ALIGNMENT,
    BLOCK_MAX_PAYLOAD,
    BLOCK_MAX_SIZE,
    BLOCK_TRAILER_SIZE,
    BRef,
    BlockBidAllocator,
    UINT64_MAX,
    block_aligned_size,
    compute_sig,
)


@dataclass(frozen=True, slots=True)
class BlockTrailer:
    """Unicode BLOCKTRAILER (16 bytes)."""

    cb: int
    signature: int
    crc: int
    bid: int

    def __post_init__(self) -> None:
        if not 0 <= self.cb <= BLOCK_MAX_PAYLOAD:
            raise ValueError(
                f"cb must be between 0 and {BLOCK_MAX_PAYLOAD} bytes"
            )
        if not 0 <= self.signature <= 0xFFFF:
            raise ValueError("signature must fit in 16 bits")
        if not 0 <= self.crc <= 0xFFFFFFFF:
            raise ValueError("crc must fit in 32 bits")
        if not 0 <= self.bid <= UINT64_MAX:
            raise ValueError("bid must fit in 64 bits")

    def pack(self) -> bytes:
        return struct.pack("<HHIQ", self.cb, self.signature, self.crc, self.bid)

    @classmethod
    def for_block(cls, *, payload: bytes, ib: int, bid: int) -> "BlockTrailer":
        if len(payload) > BLOCK_MAX_PAYLOAD:
            raise ValueError(
                f"data block payload exceeds {BLOCK_MAX_PAYLOAD} bytes"
            )
        return cls(
            cb=len(payload),
            signature=compute_sig(ib, bid),
            crc=compute_crc(payload),
            bid=bid,
        )


@dataclass(slots=True)
class BlockOffsetAllocator:
    """Allocate physical block positions on 64-byte boundaries."""

    next_ib: int

    def __post_init__(self) -> None:
        if not isinstance(self.next_ib, int) or self.next_ib < 0:
            raise ValueError("next_ib must be a non-negative integer")
        self.next_ib = _align_up(self.next_ib, BLOCK_ALIGNMENT)

    def allocate(self, payload_size: int) -> int:
        if not 0 <= payload_size <= BLOCK_MAX_PAYLOAD:
            raise ValueError(
                f"payload_size must be between 0 and {BLOCK_MAX_PAYLOAD}"
            )
        ib = self.next_ib
        self.next_ib += block_aligned_size(payload_size)
        return ib


@dataclass(frozen=True, slots=True)
class DataBlockImage:
    """One fully serialized external data block and its BBT record."""

    bref: BRef
    payload_size: int
    padding_size: int
    data: bytes
    bbt_entry: BbtEntry

    def __post_init__(self) -> None:
        if self.bref.bid & BID_INTERNAL:
            raise ValueError("data blocks must use external BIDs")
        if self.payload_size != self.bbt_entry.cb:
            raise ValueError("payload_size must match BBT cb")
        if self.bref.bid != self.bbt_entry.bid:
            raise ValueError("BREF BID must match BBT BID")
        if self.bref.ib != self.bbt_entry.ib:
            raise ValueError("BREF IB must match BBT IB")
        if len(self.data) % BLOCK_ALIGNMENT:
            raise ValueError("serialized block must be a multiple of 64 bytes")
        if len(self.data) > BLOCK_MAX_SIZE:
            raise ValueError("serialized block exceeds 8192 bytes")


@dataclass(slots=True)
class DataBlockStore:
    """Allocate, serialize, and index external data blocks."""

    offset_allocator: BlockOffsetAllocator
    bid_allocator: BlockBidAllocator
    _blocks: list[DataBlockImage] = field(default_factory=list)

    @property
    def blocks(self) -> tuple[DataBlockImage, ...]:
        return tuple(self._blocks)

    @property
    def bbt_entries(self) -> tuple[BbtEntry, ...]:
        return tuple(block.bbt_entry for block in self._blocks)

    def add(self, payload: bytes | bytearray | memoryview, *, c_ref: int = 1) -> DataBlockImage:
        raw = bytes(payload)
        if len(raw) > BLOCK_MAX_PAYLOAD:
            raise ValueError(
                "payload exceeds one data block; XBLOCK/XXBLOCK support "
                "belongs to the next large-data milestone"
            )

        ib = self.offset_allocator.allocate(len(raw))
        bid = self.bid_allocator.allocate(internal=False)
        block_data = pack_data_block(payload=raw, ib=ib, bid=bid)
        padding_size = len(block_data) - len(raw) - BLOCK_TRAILER_SIZE

        image = DataBlockImage(
            bref=BRef(bid=bid, ib=ib),
            payload_size=len(raw),
            padding_size=padding_size,
            data=block_data,
            bbt_entry=BbtEntry(
                bid=bid,
                ib=ib,
                cb=len(raw),
                c_ref=c_ref,
            ),
        )
        self._blocks.append(image)
        return image

    def extend(
        self,
        payloads: Iterable[bytes | bytearray | memoryview],
        *,
        c_ref: int = 1,
    ) -> tuple[DataBlockImage, ...]:
        return tuple(self.add(payload, c_ref=c_ref) for payload in payloads)


def pack_data_block(*, payload: bytes, ib: int, bid: int) -> bytes:
    """Serialize one external Unicode data block.

    The trailer is placed at the end of the aligned block. Padding lies
    between the payload and trailer and is excluded from the CRC.
    """

    raw = bytes(payload)
    if len(raw) > BLOCK_MAX_PAYLOAD:
        raise ValueError(
            f"data block payload exceeds {BLOCK_MAX_PAYLOAD} bytes"
        )
    if bid & BID_INTERNAL:
        raise ValueError("data blocks must use external BIDs")
    if ib < 0 or ib > UINT64_MAX:
        raise ValueError("ib must fit in 64 bits")
    if ib % BLOCK_ALIGNMENT:
        raise ValueError("data block IB must be aligned to 64 bytes")

    total_size = block_aligned_size(len(raw))
    if total_size > BLOCK_MAX_SIZE:
        raise ValueError("data block exceeds the 8192-byte MS-PST limit")

    trailer = BlockTrailer.for_block(payload=raw, ib=ib, bid=bid).pack()
    padding_size = total_size - len(raw) - BLOCK_TRAILER_SIZE

    result = raw + (b"\x00" * padding_size) + trailer
    assert len(result) == total_size
    assert len(result) % BLOCK_ALIGNMENT == 0
    return result


def parse_block_trailer(block: bytes) -> BlockTrailer:
    """Parse the final 16 bytes of a serialized Unicode block."""

    if len(block) < BLOCK_ALIGNMENT or len(block) % BLOCK_ALIGNMENT:
        raise ValueError("block must be a non-empty multiple of 64 bytes")
    if len(block) > BLOCK_MAX_SIZE:
        raise ValueError("block exceeds 8192 bytes")

    cb, signature, crc, bid = struct.unpack("<HHIQ", block[-BLOCK_TRAILER_SIZE:])
    return BlockTrailer(cb=cb, signature=signature, crc=crc, bid=bid)


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)
