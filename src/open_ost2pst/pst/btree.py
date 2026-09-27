"""Node BTree (NBT) and Block BTree (BBT) page construction."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Protocol, Sequence, TypeVar

from .pages import (
    BT_ENTRY_AREA_SIZE,
    PageAllocator,
    PageImage,
    PageType,
    make_btree_page,
)
from .primitives import (
    BID_RESERVED,
    BLOCK_MAX_PAYLOAD,
    BRef,
    PageBidAllocator,
    UINT32_MAX,
    UINT64_MAX,
)


BT_ENTRY_SIZE = 24
NBT_LEAF_ENTRY_SIZE = 32
BBT_LEAF_ENTRY_SIZE = 24
MAX_BLOCK_PAYLOAD = BLOCK_MAX_PAYLOAD


class _LeafEntry(Protocol):
    @property
    def key(self) -> int: ...

    def pack(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class BtEntry:
    """Intermediate BTree entry: key + child BREF."""

    btkey: int
    child: BRef

    def __post_init__(self) -> None:
        _validate_uint64(self.btkey, "btkey")

    @property
    def key(self) -> int:
        return self.btkey

    def pack(self) -> bytes:
        return struct.pack("<Q", self.btkey) + self.child.pack()


@dataclass(frozen=True, slots=True)
class NbtEntry:
    """Unicode NBT leaf entry (32 bytes)."""

    nid: int
    data_bid: int
    sub_bid: int = 0
    parent_nid: int = 0

    def __post_init__(self) -> None:
        _validate_uint32(self.nid, "nid")
        _validate_uint64(self.data_bid, "data_bid")
        _validate_uint64(self.sub_bid, "sub_bid")
        _validate_uint32(self.parent_nid, "parent_nid")

    @property
    def key(self) -> int:
        return self.nid

    def pack(self) -> bytes:
        return struct.pack(
            "<QQQII",
            self.nid,
            self.data_bid,
            self.sub_bid,
            self.parent_nid,
            0,
        )


@dataclass(frozen=True, slots=True)
class BbtEntry:
    """Unicode BBT leaf entry (24 bytes)."""

    bid: int
    ib: int
    cb: int
    c_ref: int = 1

    def __post_init__(self) -> None:
        _validate_uint64(self.bid, "bid")
        _validate_uint64(self.ib, "ib")
        if self.bid & BID_RESERVED:
            raise ValueError("writers must keep the BID reserved bit clear")
        if not 0 <= self.cb <= MAX_BLOCK_PAYLOAD:
            raise ValueError(f"cb must be between 0 and {MAX_BLOCK_PAYLOAD}")
        if not 0 <= self.c_ref <= 0xFFFF:
            raise ValueError("c_ref must fit in 16 bits")

    @property
    def key(self) -> int:
        return self.bid

    def pack(self) -> bytes:
        return struct.pack("<QQHHI", self.bid, self.ib, self.cb, self.c_ref, 0)


@dataclass(frozen=True, slots=True)
class BTreeResult:
    """Serialized pages for one NBT or BBT, including its root BREF."""

    root: BRef
    pages: tuple[PageImage, ...]
    height: int

    def page_at(self, ib: int) -> PageImage:
        for page in self.pages:
            if page.bref.ib == ib:
                return page
        raise KeyError(ib)


T = TypeVar("T", bound=_LeafEntry)


def build_nbt(
    entries: Sequence[NbtEntry],
    *,
    offset_allocator: PageAllocator,
    bid_allocator: PageBidAllocator,
) -> BTreeResult:
    return _build_btree(
        entries,
        page_type=PageType.NBT,
        leaf_entry_size=NBT_LEAF_ENTRY_SIZE,
        offset_allocator=offset_allocator,
        bid_allocator=bid_allocator,
    )


def build_bbt(
    entries: Sequence[BbtEntry],
    *,
    offset_allocator: PageAllocator,
    bid_allocator: PageBidAllocator,
) -> BTreeResult:
    return _build_btree(
        entries,
        page_type=PageType.BBT,
        leaf_entry_size=BBT_LEAF_ENTRY_SIZE,
        offset_allocator=offset_allocator,
        bid_allocator=bid_allocator,
    )


def _build_btree(
    entries: Sequence[T],
    *,
    page_type: PageType,
    leaf_entry_size: int,
    offset_allocator: PageAllocator,
    bid_allocator: PageBidAllocator,
) -> BTreeResult:
    ordered = sorted(entries, key=lambda entry: entry.key)
    _reject_duplicate_keys(ordered)

    pages: list[PageImage] = []
    leaf_capacity = BT_ENTRY_AREA_SIZE // leaf_entry_size

    if not ordered:
        root = make_btree_page(
            page_type=page_type,
            entries=[],
            entry_size=leaf_entry_size,
            level=0,
            first_key=None,
            offset_allocator=offset_allocator,
            bid_allocator=bid_allocator,
        )
        pages.append(root)
        return BTreeResult(root=root.bref, pages=tuple(pages), height=0)

    current: list[PageImage] = []
    for start in range(0, len(ordered), leaf_capacity):
        group = ordered[start : start + leaf_capacity]
        page = make_btree_page(
            page_type=page_type,
            entries=[entry.pack() for entry in group],
            entry_size=leaf_entry_size,
            level=0,
            first_key=group[0].key,
            offset_allocator=offset_allocator,
            bid_allocator=bid_allocator,
        )
        pages.append(page)
        current.append(page)

    level = 1
    intermediate_capacity = BT_ENTRY_AREA_SIZE // BT_ENTRY_SIZE

    while len(current) > 1:
        parents: list[PageImage] = []
        for start in range(0, len(current), intermediate_capacity):
            children = current[start : start + intermediate_capacity]
            bt_entries = [
                BtEntry(btkey=_require_first_key(child), child=child.bref)
                for child in children
            ]
            parent = make_btree_page(
                page_type=page_type,
                entries=[entry.pack() for entry in bt_entries],
                entry_size=BT_ENTRY_SIZE,
                level=level,
                first_key=bt_entries[0].key,
                offset_allocator=offset_allocator,
                bid_allocator=bid_allocator,
            )
            pages.append(parent)
            parents.append(parent)

        current = parents
        level += 1

    root_page = current[0]
    return BTreeResult(
        root=root_page.bref,
        pages=tuple(pages),
        height=root_page.level,
    )


def _require_first_key(page: PageImage) -> int:
    if page.first_key is None:
        raise ValueError("non-empty BTree child page must have a first key")
    return page.first_key


def _reject_duplicate_keys(entries: Sequence[_LeafEntry]) -> None:
    previous: int | None = None
    for entry in entries:
        if previous is not None and entry.key == previous:
            raise ValueError(f"duplicate BTree key: {entry.key:#x}")
        previous = entry.key


def _validate_uint32(value: int, name: str) -> None:
    if not isinstance(value, int) or not 0 <= value <= UINT32_MAX:
        raise ValueError(f"{name} must be an unsigned 32-bit integer")


def _validate_uint64(value: int, name: str) -> None:
    if not isinstance(value, int) or not 0 <= value <= UINT64_MAX:
        raise ValueError(f"{name} must be an unsigned 64-bit integer")
