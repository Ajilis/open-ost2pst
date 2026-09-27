import struct

import pytest

from open_ost2pst.pst.crc import compute_crc
from open_ost2pst.pst.ndb import (
    HEADER_FULL_CRC_LENGTH,
    HEADER_FULL_CRC_OFFSET,
    HEADER_PARTIAL_CRC_LENGTH,
    HEADER_PARTIAL_CRC_OFFSET,
    HEADER_SIZE,
    OFFSET_BID_NEXT_B,
    OFFSET_BID_NEXT_P,
    OFFSET_CRYPT_METHOD,
    OFFSET_RGNID,
    OFFSET_ROOT,
    OFFSET_SENTINEL,
    ROOT_SIZE,
    Root,
    UnicodeHeader,
    initial_rgnid,
)
from open_ost2pst.pst.primitives import (
    BID_INTERNAL,
    BRef,
    BlockBidAllocator,
    NidType,
    PageBidAllocator,
    bid_index,
    block_aligned_size,
    canonical_bid,
    compute_sig,
    is_internal_bid,
    make_block_bid,
    make_nid,
    nid_index,
    nid_type,
)


def test_ms_pst_crc_known_vector() -> None:
    # MS-PST CRC is the reflected CRC-32 recurrence with seed 0 and no
    # initial/final XOR. This differs intentionally from zlib.crc32.
    assert compute_crc(b"123456789") == 0x2DFD2D88


def test_nid_round_trip() -> None:
    nid = make_nid(NidType.NORMAL_MESSAGE, 0x10000)

    assert nid == 0x00200004
    assert nid_type(nid) == NidType.NORMAL_MESSAGE
    assert nid_index(nid) == 0x10000


@pytest.mark.parametrize("nid_type_value", [-1, 0x20])
def test_nid_type_rejects_values_outside_five_bits(nid_type_value: int) -> None:
    with pytest.raises(ValueError):
        make_nid(nid_type_value, 1)


def test_block_bid_flags_and_index() -> None:
    external = make_block_bid(0x1234)
    internal = make_block_bid(0x1234, internal=True)

    assert external == 0x48D0
    assert internal == external | BID_INTERNAL
    assert bid_index(internal) == 0x1234
    assert is_internal_bid(external) is False
    assert is_internal_bid(internal) is True
    assert canonical_bid(internal | 0x01) == internal


def test_bid_allocators_follow_ms_pst_increment_rules() -> None:
    blocks = BlockBidAllocator(next_bid=4)
    pages = PageBidAllocator(next_bid=7)

    assert blocks.allocate() == 4
    assert blocks.allocate(internal=True) == 10
    assert blocks.next_bid == 12

    assert pages.allocate() == 7
    assert pages.allocate() == 8
    assert pages.next_bid == 9


def test_compute_sig_uses_low_32_bits_of_ib_xor_bid() -> None:
    ib = 0x0000000100005000
    bid = 0x0000000000001234

    value = (ib ^ bid) & 0xFFFFFFFF
    expected = ((value >> 16) ^ value) & 0xFFFF

    assert compute_sig(ib, bid) == expected


def test_block_geometry_includes_trailer_and_64_byte_alignment() -> None:
    assert block_aligned_size(0) == 64
    assert block_aligned_size(48) == 64
    assert block_aligned_size(49) == 128
    assert block_aligned_size(8176) == 8192


def test_bref_pack_round_trip() -> None:
    bref = BRef(bid=0x1122334455667788, ib=0x0102030405060708)

    packed = bref.pack()

    assert len(packed) == 16
    assert BRef.unpack(packed) == bref


def test_root_pack_is_exactly_72_bytes_and_round_trips() -> None:
    root = Root(
        file_eof=0x8000,
        amap_last=0x4400,
        amap_free=0x100,
        pmap_free=0,
        nbt_root=BRef(0x101, 0x6000),
        bbt_root=BRef(0x102, 0x6200),
        amap_valid=0x02,
    )

    packed = root.pack()

    assert len(packed) == ROOT_SIZE
    assert Root.unpack(packed) == root


def test_initial_rgnid_uses_specified_starting_indexes() -> None:
    values = initial_rgnid()

    assert len(values) == 32
    assert values[NidType.NORMAL_FOLDER] == 0x400
    assert values[NidType.SEARCH_FOLDER] == 0x4000
    assert values[NidType.NORMAL_MESSAGE] == 0x10000
    assert values[NidType.ASSOC_MESSAGE] == 0x8000
    assert values[NidType.ATTACHMENT] == 0x400


def test_unicode_header_binary_layout_and_crcs() -> None:
    root = Root(
        file_eof=0x9000,
        amap_last=0x4400,
        nbt_root=BRef(0x101, 0x6000),
        bbt_root=BRef(0x102, 0x6200),
        amap_valid=0x02,
    )
    header = UnicodeHeader(
        root=root,
        bid_next_p=0x103,
        bid_next_b=0x204,
        unique=7,
    ).pack()

    assert len(header) == HEADER_SIZE
    assert header[0:4] == b"!BDN"
    assert header[8:10] == b"SM"
    assert struct.unpack_from("<H", header, 10)[0] == 23
    assert struct.unpack_from("<H", header, 12)[0] == 19
    assert header[14:16] == b"\x01\x01"

    assert struct.unpack_from("<Q", header, OFFSET_BID_NEXT_P)[0] == 0x103
    assert struct.unpack_from("<Q", header, OFFSET_BID_NEXT_B)[0] == 0x204

    assert header[OFFSET_ROOT : OFFSET_ROOT + ROOT_SIZE] == root.pack()
    assert header[256:384] == b"\xFF" * 128
    assert header[384:512] == b"\xFF" * 128
    assert header[OFFSET_SENTINEL] == 0x80
    assert header[OFFSET_CRYPT_METHOD] == 0x00

    rgnid = struct.unpack_from("<32I", header, OFFSET_RGNID)
    assert rgnid == initial_rgnid()

    stored_partial = struct.unpack_from("<I", header, HEADER_PARTIAL_CRC_OFFSET)[0]
    stored_full = struct.unpack_from("<I", header, HEADER_FULL_CRC_OFFSET)[0]

    assert stored_partial == compute_crc(header[8 : 8 + HEADER_PARTIAL_CRC_LENGTH])
    assert stored_full == compute_crc(header[8 : 8 + HEADER_FULL_CRC_LENGTH])


def test_unicode_header_rejects_misaligned_next_block_bid() -> None:
    root = Root(file_eof=HEADER_SIZE, amap_last=0)

    with pytest.raises(ValueError):
        UnicodeHeader(root=root, bid_next_b=6)
