"""Assembly of a complete minimal Unicode PST NDB image."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .amap import AmapAllocator
from .blocks import DataBlockImage, DataBlockStore
from .btree import BTreeResult, NbtEntry, build_bbt, build_nbt
from .ndb import Root, UnicodeHeader, VALID_AMAP
from .primitives import BlockBidAllocator, PageBidAllocator


@dataclass(frozen=True, slots=True)
class NdbBuildResult:
    """Finished PST NDB bytes and the structures used to build them."""

    data: bytes
    header: UnicodeHeader
    nbt: BTreeResult
    bbt: BTreeResult
    blocks: tuple[DataBlockImage, ...]
    amap: AmapAllocator

    def write(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.write_bytes(self.data)
        return destination


@dataclass(slots=True)
class NdbImageBuilder:
    """Build a self-contained Unicode PST NDB layer.

    This deliberately stops at the NDB boundary: callers supply node payload
    bytes and NIDs. LTP/Messaging will later construct the payloads.
    """

    amap: AmapAllocator = field(default_factory=AmapAllocator)
    block_bids: BlockBidAllocator = field(
        default_factory=lambda: BlockBidAllocator(4)
    )
    page_bids: PageBidAllocator = field(
        default_factory=lambda: PageBidAllocator(1)
    )
    unique: int = 1
    _nodes: list[NbtEntry] = field(default_factory=list, init=False)
    _blocks: DataBlockStore = field(init=False)

    def __post_init__(self) -> None:
        self._blocks = DataBlockStore(
            offset_allocator=self.amap.block_allocator(),
            bid_allocator=self.block_bids,
        )

    @property
    def nodes(self) -> tuple[NbtEntry, ...]:
        return tuple(self._nodes)

    @property
    def blocks(self) -> tuple[DataBlockImage, ...]:
        return self._blocks.blocks

    @property
    def bbt_entries(self):
        return self._blocks.bbt_entries

    def add_block(
        self,
        payload: bytes | bytearray | memoryview,
        *,
        c_ref: int = 1,
    ) -> DataBlockImage:
        return self._blocks.add(payload, c_ref=c_ref)

    def add_node(
        self,
        nid: int,
        data_bid: int,
        *,
        sub_bid: int = 0,
        parent_nid: int = 0,
    ) -> NbtEntry:
        entry = NbtEntry(
            nid=nid,
            data_bid=data_bid,
            sub_bid=sub_bid,
            parent_nid=parent_nid,
        )
        if any(existing.nid == entry.nid for existing in self._nodes):
            raise ValueError(f"duplicate NID: {nid:#x}")
        self._nodes.append(entry)
        return entry

    def add_data_node(
        self,
        nid: int,
        payload: bytes | bytearray | memoryview,
        *,
        parent_nid: int = 0,
        sub_bid: int = 0,
        c_ref: int = 1,
    ) -> NbtEntry:
        block = self.add_block(payload, c_ref=c_ref)
        return self.add_node(
            nid,
            block.bref.bid,
            sub_bid=sub_bid,
            parent_nid=parent_nid,
        )

    def build(self) -> NdbBuildResult:
        """Build HEADER + AMaps + blocks + NBT/BBT pages into one PST image."""

        page_allocator = self.amap.page_allocator()

        nbt = build_nbt(
            self._nodes,
            offset_allocator=page_allocator,
            bid_allocator=self.page_bids,
        )

        # BBT contains data/internal blocks, not NBT/BBT pages.
        bbt = build_bbt(
            self._blocks.bbt_entries,
            offset_allocator=page_allocator,
            bid_allocator=self.page_bids,
        )

        root = Root(
            file_eof=self.amap.file_eof,
            amap_last=self.amap.last_amap_ib,
            amap_free=self.amap.free_bytes,
            pmap_free=0,
            nbt_root=nbt.root,
            bbt_root=bbt.root,
            amap_valid=VALID_AMAP,
        )
        header = UnicodeHeader(
            root=root,
            bid_next_p=self.page_bids.next_bid,
            bid_next_b=self.block_bids.next_bid,
            unique=self.unique,
        )

        image = bytearray(root.file_eof)
        _write_chunk(image, 0, header.pack(), "HEADER")

        # Generate AMap bytes only after every block/page allocation has been
        # recorded, otherwise the bitmap would describe a stale layout.
        for ib, data in self.amap.chunks:
            _write_chunk(image, ib, data, f"AMap@{ib:#x}")

        for ib, data in self._blocks.chunks:
            _write_chunk(image, ib, data, f"block@{ib:#x}")

        for page in (*nbt.pages, *bbt.pages):
            _write_chunk(
                image,
                page.bref.ib,
                page.data,
                f"{page.page_type.name}@{page.bref.ib:#x}",
            )

        return NdbBuildResult(
            data=bytes(image),
            header=header,
            nbt=nbt,
            bbt=bbt,
            blocks=self._blocks.blocks,
            amap=self.amap,
        )


def build_minimal_ndb() -> NdbBuildResult:
    """Build the smallest useful NDB used by integration tests.

    NID 0x21 is the well-known Message Store node. Its payload is intentionally
    opaque at this layer; pypff opening the file validates the NDB structures.
    """

    builder = NdbImageBuilder()
    builder.add_data_node(0x21, b"x" * 64)
    return builder.build()


def _write_chunk(
    target: bytearray,
    offset: int,
    data: bytes,
    label: str,
) -> None:
    end = offset + len(data)
    if offset < 0 or end > len(target):
        raise ValueError(
            f"{label} does not fit in image: {offset:#x}..{end:#x}"
        )
    target[offset:end] = data
