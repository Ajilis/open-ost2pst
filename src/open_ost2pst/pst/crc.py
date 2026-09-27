"""CRC primitives for the MS-PST NDB layer."""

from __future__ import annotations

_POLYNOMIAL = 0xEDB88320


def _build_crc_table() -> tuple[int, ...]:
    table: list[int] = []
    for value in range(256):
        crc = value
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ _POLYNOMIAL
            else:
                crc >>= 1
        table.append(crc & 0xFFFFFFFF)
    return tuple(table)


_CRC_TABLE = _build_crc_table()


def compute_crc(data: bytes | bytearray | memoryview, seed: int = 0) -> int:
    """Return the MS-PST CRC for *data*.

    MS-PST section 5.3 uses the reflected CRC-32 polynomial 0xEDB88320,
    seeded with zero and without the conventional initial/final XOR used by
    many general-purpose CRC-32 APIs.
    """

    crc = seed & 0xFFFFFFFF
    for value in memoryview(data).cast("B"):
        crc = _CRC_TABLE[(crc ^ value) & 0xFF] ^ (crc >> 8)
    return crc & 0xFFFFFFFF
