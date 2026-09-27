"""MS-OXRTFCP helpers for PidTagRtfCompressed."""

from __future__ import annotations

from dataclasses import dataclass
import struct


RTF_COMPRESSED_MAGIC = 0x75465A4C  # "LZFu"
RTF_UNCOMPRESSED_MAGIC = 0x414C454D  # "MELA"
RTF_HEADER_SIZE = 16


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
    def unpack(cls, data: bytes | bytearray | memoryview) -> "RtfCompressedHeader":
        raw = bytes(data)
        if len(raw) < RTF_HEADER_SIZE:
            raise ValueError("RTF compressed header is truncated")
        return cls(*struct.unpack_from("<IIII", raw, 0))


def wrap_rtf_uncompressed(
    rtf: bytes | bytearray | memoryview,
) -> bytes:
    """Wrap raw RTF bytes in the valid MS-OXRTFCP uncompressed form.

    The property is still PidTagRtfCompressed; MS-OXRTFCP explicitly permits
    COMPTYPE=UNCOMPRESSED ("MELA"), with CRC set to zero.
    """

    raw = bytes(rtf)
    if len(raw) > 0xFFFFFFFF:
        raise ValueError("RTF payload exceeds 32-bit RAWSIZE")

    compressed_size = len(raw) + 12
    if compressed_size > 0xFFFFFFFF:
        raise ValueError("RTF payload exceeds 32-bit COMPSIZE")

    header = RtfCompressedHeader(
        compressed_size=compressed_size,
        raw_size=len(raw),
        compression_type=RTF_UNCOMPRESSED_MAGIC,
        crc=0,
    )
    return header.pack() + raw


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
