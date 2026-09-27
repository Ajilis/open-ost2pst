"""MS-PST large-data trees: XBLOCK and XXBLOCK."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterable, Sequence

from .blocks import DataBlockImage, DataBlockStore
from .primitives import (
    BID_INTERNAL,
    BLOCK_MAX_PAYLOAD,
    UINT32_MAX,
)


XBLOCK_TYPE = 0x01
XBLOCK_LEVEL = 0x01
XXBLOCK_LEVEL = 0x02
XBLOCK_HEADER_SIZE = 8
UNICODE_BID_SIZE = 8
XBLOCK_MAX_ENTRIES = (
    BLOCK_MAX_PAYLOAD - XBLOCK_HEADER_SIZE
) // UNICODE_BID_SIZE


@dataclass(frozen=True, slots=True)
class DataTreeImage:
    """Root BID plus every physical block used by one logical data stream."""

    root_bid: int
    logical_size: int
    data_blocks: tuple[DataBlockImage, ...]
    index_blocks: tuple[DataBlockImage, ...]

    @property
    def all_blocks(self) -> tuple[DataBlockImage, ...]:
        return self.data_blocks + self.index_blocks

    @property
    def uses_xblock(self) -> bool:
        return bool(self.index_blocks)

    @property
    def uses_xxblock(self) -> bool:
        if not self.index_blocks:
            return False
        return _index_level_from_block(self.index_blocks[-1]) == XXBLOCK_LEVEL


def pack_xblock(
    bids: Sequence[int],
    *,
    total_size: int,
    level: int = XBLOCK_LEVEL,
) -> bytes:
    """Pack the payload of one Unicode XBLOCK or XXBLOCK."""

    if level not in (XBLOCK_LEVEL, XXBLOCK_LEVEL):
        raise ValueError("XBLOCK level must be 1 or 2")
    if not bids:
        raise ValueError("XBLOCK must contain at least one BID")
    if len(bids) > XBLOCK_MAX_ENTRIES:
        raise ValueError(
            f"XBLOCK exceeds {XBLOCK_MAX_ENTRIES} Unicode BID entries"
        )
    if not 0 <= total_size <= UINT32_MAX:
        raise ValueError("lcbTotal must fit in 32 bits")

    if level == XBLOCK_LEVEL:
        if any(bid & BID_INTERNAL for bid in bids):
            raise ValueError("XBLOCK level 1 must reference external blocks")
    else:
        if any(not (bid & BID_INTERNAL) for bid in bids):
            raise ValueError("XXBLOCK must reference internal XBLOCKs")

    return struct.pack(
        f"<BBHI{len(bids)}Q",
        XBLOCK_TYPE,
        level,
        len(bids),
        total_size,
        *bids,
    )


def parse_xblock(payload: bytes) -> tuple[int, int, tuple[int, ...]]:
    """Return level, lcbTotal and BIDs from an index-block payload."""

    if len(payload) < XBLOCK_HEADER_SIZE:
        raise ValueError("XBLOCK payload is truncated")

    btype, level, count, total_size = struct.unpack_from("<BBHI", payload, 0)
    if btype != XBLOCK_TYPE:
        raise ValueError("payload is not an XBLOCK or XXBLOCK")
    if level not in (XBLOCK_LEVEL, XXBLOCK_LEVEL):
        raise ValueError("invalid XBLOCK level")
    if count == 0 or count > XBLOCK_MAX_ENTRIES:
        raise ValueError("invalid XBLOCK entry count")

    expected = XBLOCK_HEADER_SIZE + count * UNICODE_BID_SIZE
    if len(payload) != expected:
        raise ValueError("XBLOCK payload size does not match entry count")

    bids = struct.unpack_from(f"<{count}Q", payload, XBLOCK_HEADER_SIZE)
    return level, total_size, tuple(bids)


def store_data_stream(
    store: DataBlockStore,
    data: bytes | bytearray | memoryview,
    *,
    c_ref: int = 1,
) -> DataTreeImage:
    """Store arbitrary logical bytes using data blocks plus XBLOCK or XXBLOCK."""

    raw = bytes(data)
    chunks = [
        raw[offset : offset + BLOCK_MAX_PAYLOAD]
        for offset in range(0, len(raw), BLOCK_MAX_PAYLOAD)
    ]
    if not chunks:
        chunks = [b""]

    return store_block_sequence(
        store,
        chunks,
        logical_size=len(raw),
        c_ref=c_ref,
    )


def store_block_sequence(
    store: DataBlockStore,
    payloads: Iterable[bytes | bytearray | memoryview],
    *,
    logical_size: int | None = None,
    c_ref: int = 1,
) -> DataTreeImage:
    """Store a logical stream while preserving caller-supplied block boundaries."""

    chunks = tuple(bytes(payload) for payload in payloads)
    if not chunks:
        chunks = (b"",)

    for payload in chunks:
        if len(payload) > BLOCK_MAX_PAYLOAD:
            raise ValueError(
                f"data block payload exceeds {BLOCK_MAX_PAYLOAD} bytes"
            )

    calculated_size = sum(len(payload) for payload in chunks)
    if logical_size is None:
        logical_size = calculated_size
    if not 0 <= logical_size <= UINT32_MAX:
        raise ValueError("logical stream size must fit in 32 bits")

    data_blocks = tuple(
        store.add(payload, c_ref=c_ref, internal=False)
        for payload in chunks
    )

    if len(data_blocks) == 1:
        return DataTreeImage(
            root_bid=data_blocks[0].bref.bid,
            logical_size=logical_size,
            data_blocks=data_blocks,
            index_blocks=(),
        )

    xblocks: list[DataBlockImage] = []
    for start in range(0, len(data_blocks), XBLOCK_MAX_ENTRIES):
        group = data_blocks[start : start + XBLOCK_MAX_ENTRIES]
        group_size = sum(block.payload_size for block in group)
        payload = pack_xblock(
            [block.bref.bid for block in group],
            total_size=group_size,
            level=XBLOCK_LEVEL,
        )
        xblocks.append(store.add_internal(payload, c_ref=c_ref))

    if len(xblocks) == 1:
        return DataTreeImage(
            root_bid=xblocks[0].bref.bid,
            logical_size=logical_size,
            data_blocks=data_blocks,
            index_blocks=tuple(xblocks),
        )

    if len(xblocks) > XBLOCK_MAX_ENTRIES:
        raise ValueError(
            "data stream exceeds one XXBLOCK; deeper data trees are unsupported"
        )

    xx_payload = pack_xblock(
        [block.bref.bid for block in xblocks],
        total_size=logical_size,
        level=XXBLOCK_LEVEL,
    )
    xxblock = store.add_internal(xx_payload, c_ref=c_ref)

    return DataTreeImage(
        root_bid=xxblock.bref.bid,
        logical_size=logical_size,
        data_blocks=data_blocks,
        index_blocks=tuple(xblocks) + (xxblock,),
    )


def _index_level_from_block(block: DataBlockImage) -> int:
    payload = block.data[: block.payload_size]
    level, _total_size, _bids = parse_xblock(payload)
    return level
