"""MS-OXRTFCP helpers for PidTagRtfCompressed."""

from __future__ import annotations

from dataclasses import dataclass
import struct


RTF_COMPRESSED_MAGIC = 0x75465A4C  # "LZFu"
RTF_UNCOMPRESSED_MAGIC = 0x414C454D  # "MELA"
RTF_HEADER_SIZE = 16
RTF_DICTIONARY_INITIAL_SIZE = 207
RTF_DICTIONARY_SIZE = 4096


@dataclass(frozen=True, slots=True)
class RtfCompressedHeader:
    compressed_size: int
    raw_size: int
    compression_type: int
    crc: int

    def pack(self) -> bytes:
        return struct.pack(
            "<IIII",
            self.compressed_size,
            self.raw_size,
            self.compression_type,
            self.crc,
        )

    @classmethod
    def unpack(
        cls,
        data: bytes | bytearray | memoryview,
    ) -> "RtfCompressedHeader":
        raw = bytes(data)
        if len(raw) < RTF_HEADER_SIZE:
            raise ValueError("RTF compressed header is truncated")
        return cls(*struct.unpack_from("<IIII", raw, 0))


def compress_rtf(
    rtf: bytes | bytearray | memoryview,
) -> bytes:
    """Encode raw RTF using a valid literal-only LZFu stream.

    The encoder deliberately does not search the LZFu dictionary for matches.
    It emits literal tokens and a standards-compliant ENDRUN reference. This
    trades compression ratio for a small, auditable implementation while
    remaining fully compatible with MS-OXRTFCP readers.
    """

    raw = bytes(rtf)
    if len(raw) > 0xFFFFFFFF:
        raise ValueError("RTF payload exceeds 32-bit RAWSIZE")

    contents = bytearray()
    offset = 0

    while offset + 8 <= len(raw):
        contents.append(0x00)
        contents.extend(raw[offset : offset + 8])
        offset += 8

    remainder = raw[offset:]
    endrun_bit = 1 << len(remainder)
    contents.append(endrun_bit)
    contents.extend(remainder)

    write_offset = (
        RTF_DICTIONARY_INITIAL_SIZE + len(raw)
    ) % RTF_DICTIONARY_SIZE
    endrun = (write_offset << 4) & 0xFFFF
    contents.extend(struct.pack(">H", endrun))

    compressed_size = len(contents) + 12
    if compressed_size > 0xFFFFFFFF:
        raise ValueError("RTF payload exceeds 32-bit COMPSIZE")

    header = RtfCompressedHeader(
        compressed_size=compressed_size,
        raw_size=len(raw),
        compression_type=RTF_COMPRESSED_MAGIC,
        crc=weak_crc32(contents),
    )
    return header.pack() + contents


def wrap_rtf_uncompressed(
    rtf: bytes | bytearray | memoryview,
) -> bytes:
    """Wrap raw RTF in the MS-OXRTFCP uncompressed MELA form."""

    raw = bytes(rtf)
    if len(raw) > 0xFFFFFFFF:
        raise ValueError("RTF payload exceeds 32-bit RAWSIZE")

    compressed_size = len(raw) + 12
    if compressed_size > 0xFFFFFFFF:
        raise ValueError("RTF payload exceeds 32-bit COMPSIZE")

    return RtfCompressedHeader(
        compressed_size=compressed_size,
        raw_size=len(raw),
        compression_type=RTF_UNCOMPRESSED_MAGIC,
        crc=0,
    ).pack() + raw


def unwrap_rtf_uncompressed(
    value: bytes | bytearray | memoryview,
) -> bytes:
    """Parse the uncompressed MS-OXRTFCP form for diagnostics/tests."""

    raw = bytes(value)
    header = RtfCompressedHeader.unpack(raw)

    if header.compression_type != RTF_UNCOMPRESSED_MAGIC:
        raise ValueError("RTF stream is not the uncompressed MELA form")
    if header.crc != 0:
        raise ValueError("uncompressed RTF CRC must be zero")

    contents = raw[RTF_HEADER_SIZE:]
    if header.compressed_size != len(contents) + 12:
        raise ValueError("RTF COMPSIZE does not match payload")
    if header.raw_size != len(contents):
        raise ValueError("RTF RAWSIZE does not match payload")
    return contents


def weak_crc32(
    data: bytes | bytearray | memoryview,
    *,
    initial: int = 0,
) -> int:
    """MS-OXRTFCP weak CRC-32 (reflected polynomial, no XOR in/out)."""

    crc = initial & 0xFFFFFFFF
    for value in bytes(data):
        crc ^= value
        for _ in range(8):
            if crc & 1:
                crc = 0xEDB88320 ^ (crc >> 1)
            else:
                crc >>= 1
    return crc & 0xFFFFFFFF
