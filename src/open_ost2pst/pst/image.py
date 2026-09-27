"""Assembly of a complete Unicode PST NDB image."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .amap import AmapAllocator
from .blocks import DataBlockImage, DataBlockStore
from .btree import BTreeResult, NbtEntry, build_bbt, build_nbt
from .large_data import (
    DataTreeImage,
    store_block_sequence,
    store_data_stream as store_large_data_stream,
)
from .ltp.heap import HeapImage, HeapNode
from .ltp.pc import PropertyContext
from .ltp.storage import ExternalValue
from .ltp.tc import TableContext
from .ndb import Root, UnicodeHeader, VALID_AMAP
from .primitives import BlockBidAllocator, PageBidAllocator
from .subnodes import SubnodeEntry, pack_slblock


@dataclass(frozen=True, slots=True)
class StoredNode:
    """NDB data BID plus optional local subnodes."""

    data_bid: int
    subnodes: Mapping[int, "StoredNode"] = field(default_factory=dict)


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
    """Build a self-contained Unicode PST NDB layer."""

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
        internal: bool = False,
    ) -> DataBlockImage:
        return self._blocks.add(
            payload,
            c_ref=c_ref,
            internal=internal,
        )

    def add_internal_block(
        self,
        payload: bytes | bytearray | memoryview,
        *,
        c_ref: int = 1,
    ) -> DataBlockImage:
        return self._blocks.add_internal(payload, c_ref=c_ref)

    def store_data_stream(
        self,
        data: bytes | bytearray | memoryview,
        *,
        c_ref: int = 1,
    ) -> DataTreeImage:
        return store_large_data_stream(
            self._blocks,
            data,
            c_ref=c_ref,
        )

    def store_heap_image(
        self,
        heap: HeapImage,
        *,
        c_ref: int = 1,
    ) -> DataTreeImage:
        return store_block_sequence(
            self._blocks,
            (block.data for block in heap.blocks),
            c_ref=c_ref,
        )

    def store_property_context_node(
        self,
        context: PropertyContext,
        *,
        c_ref: int = 1,
    ) -> StoredNode:
        image = context.build()
        data_tree = self.store_heap_image(image.heap, c_ref=c_ref)
        subnodes = self._store_external_values(
            image.external_values,
            c_ref=c_ref,
        )
        return StoredNode(
            data_bid=data_tree.root_bid,
            subnodes=subnodes,
        )

    def store_table_context_node(
        self,
        context: TableContext,
        *,
        c_ref: int = 1,
    ) -> StoredNode:
        image = context.build()
        data_tree = self.store_heap_image(image.heap, c_ref=c_ref)
        subnodes = self._store_external_values(
            image.external_values,
            c_ref=c_ref,
        )
        return StoredNode(
            data_bid=data_tree.root_bid,
            subnodes=subnodes,
        )

    def store_property_context(
        self,
        context: PropertyContext,
        *,
        c_ref: int = 1,
    ) -> int:
        """Legacy helper for a PC that has no external-value subnodes."""

        stored = self.store_property_context_node(context, c_ref=c_ref)
        if stored.subnodes:
            raise ValueError(
                "Property Context has external subnodes; "
                "use store_property_context_node()"
            )
        return stored.data_bid

    def store_table_context(
        self,
        context: TableContext,
        *,
        c_ref: int = 1,
    ) -> int:
        """Legacy helper for a TC that has no external-value subnodes."""

        stored = self.store_table_context_node(context, c_ref=c_ref)
        if stored.subnodes:
            raise ValueError(
                "Table Context has external subnodes; "
                "use store_table_context_node()"
            )
        return stored.data_bid

    def add_subnode_tree(
        self,
        subnodes: Mapping[int, object],
    ) -> int:
        entries: list[SubnodeEntry] = []
        for nid in sorted(subnodes):
            value = subnodes[nid]

            if isinstance(value, StoredNode):
                data_bid = value.data_bid
                nested = value.subnodes
            elif isinstance(value, tuple):
                data_bid, nested = value
            else:
                data_bid = value
                nested = {}

            sub_bid = self.add_subnode_tree(nested) if nested else 0
            entries.append(
                SubnodeEntry(
                    nid=nid,
                    data_bid=int(data_bid),
                    sub_bid=sub_bid,
                )
            )

        block = self.add_internal_block(pack_slblock(entries))
        return block.bref.bid

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

    def add_heap_node(
        self,
        nid: int,
        heap: HeapNode,
        *,
        parent_nid: int = 0,
        sub_bid: int = 0,
        c_ref: int = 1,
    ) -> NbtEntry:
        heap_image = heap.build()
        data_tree = self.store_heap_image(heap_image, c_ref=c_ref)
        return self.add_node(
            nid,
            data_tree.root_bid,
            parent_nid=parent_nid,
            sub_bid=sub_bid,
        )

    def add_property_context(
        self,
        nid: int,
        context: PropertyContext,
        *,
        parent_nid: int = 0,
        sub_bid: int = 0,
        c_ref: int = 1,
    ) -> NbtEntry:
        stored = self.store_property_context_node(context, c_ref=c_ref)
        generated_sub_bid = (
            self.add_subnode_tree(stored.subnodes)
            if stored.subnodes
            else 0
        )
        if generated_sub_bid and sub_bid:
            raise ValueError(
                "cannot combine explicit sub_bid with PC external subnodes"
            )
        return self.add_node(
            nid,
            stored.data_bid,
            parent_nid=parent_nid,
            sub_bid=generated_sub_bid or sub_bid,
        )

    def add_table_context(
        self,
        nid: int,
        context: TableContext,
        *,
        parent_nid: int = 0,
        sub_bid: int = 0,
        c_ref: int = 1,
    ) -> NbtEntry:
        stored = self.store_table_context_node(context, c_ref=c_ref)
        generated_sub_bid = (
            self.add_subnode_tree(stored.subnodes)
            if stored.subnodes
            else 0
        )
        if generated_sub_bid and sub_bid:
            raise ValueError(
                "cannot combine explicit sub_bid with TC external subnodes"
            )
        return self.add_node(
            nid,
            stored.data_bid,
            parent_nid=parent_nid,
            sub_bid=generated_sub_bid or sub_bid,
        )

    def add_data_node(
        self,
        nid: int,
        payload: bytes | bytearray | memoryview,
        *,
        parent_nid: int = 0,
        sub_bid: int = 0,
        c_ref: int = 1,
    ) -> NbtEntry:
        data_tree = self.store_data_stream(payload, c_ref=c_ref)
        return self.add_node(
            nid,
            data_tree.root_bid,
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

    def _store_external_values(
        self,
        values: tuple[ExternalValue, ...],
        *,
        c_ref: int,
    ) -> dict[int, StoredNode]:
        result: dict[int, StoredNode] = {}
        for value in values:
            tree = self.store_data_stream(value.data, c_ref=c_ref)
            result[value.nid] = StoredNode(data_bid=tree.root_bid)
        return result


def build_minimal_ndb() -> NdbBuildResult:
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
