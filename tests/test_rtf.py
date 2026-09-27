import struct

from open_ost2pst.pst.rtf import (
    RTF_COMPRESSED_MAGIC,
    RTF_UNCOMPRESSED_MAGIC,
    RtfCompressedHeader,
    compress_rtf,
    unwrap_rtf_uncompressed,
    weak_crc32,
    wrap_rtf_uncompressed,
)


def test_weak_crc32_known_vector() -> None:
    assert weak_crc32(b"123456789") == 0x2DFD2D88


def test_literal_only_lzfu_header_and_endrun() -> None:
    value = compress_rtf(b"abc")
    header = RtfCompressedHeader.unpack(value)

    assert header.compressed_size == len(value) - 4
    assert header.raw_size == 3
    assert header.compression_type == RTF_COMPRESSED_MAGIC

    contents = value[16:]
    assert contents == b"\x08abc\x0d\x20"
    assert header.crc == weak_crc32(contents)


def test_literal_only_lzfu_full_literal_group_then_endrun() -> None:
    value = compress_rtf(b"abcdefgh")
    contents = value[16:]

    assert contents[:9] == b"\x00abcdefgh"
    assert contents[9] == 0x01

    write_offset = 207 + 8
    assert contents[10:] == struct.pack(">H", write_offset << 4)


def test_mela_wrapper_remains_available_for_diagnostics() -> None:
    raw = b"{\\rtf1\\ansi test}"
    value = wrap_rtf_uncompressed(raw)
    header = RtfCompressedHeader.unpack(value)

    assert header.compression_type == RTF_UNCOMPRESSED_MAGIC
    assert header.crc == 0
    assert unwrap_rtf_uncompressed(value) == raw
