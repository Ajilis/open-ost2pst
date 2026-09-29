"""Bounded, seekable binary payload helpers.

Large attachment payloads can live in a temporary file instead of one giant
Python bytes object. Consumers can iterate them in bounded chunks, compute a
stable SHA-256 digest without rematerializing the value, and close them
explicitly when a conversion is complete.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
from typing import BinaryIO, Iterable, Iterator, TypeAlias


DEFAULT_BINARY_CHUNK_SIZE = 1024 * 1024


class TemporaryBinaryPayload:
    """Seekable named temporary payload with cached size and SHA-256."""

    __slots__ = ("_file", "_path", "_size", "_sha256", "_closed")

    def __init__(
        self,
        file_object: BinaryIO,
        *,
        path: str | Path,
        size: int,
        sha256: str,
    ) -> None:
        self._file = file_object
        self._path = Path(path)
        self._size = size
        self._sha256 = sha256
        self._closed = False

    @classmethod
    def from_chunks(
        cls,
        chunks: Iterable[bytes | bytearray | memoryview],
        *,
        max_bytes: int | None = None,
        directory: str | Path | None = None,
        prefix: str = ".open-ost2pst-",
    ) -> "TemporaryBinaryPayload":
        temp_directory = None if directory is None else str(Path(directory))
        handle = tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=temp_directory,
            prefix=prefix,
            suffix=".tmp",
            delete=False,
        )
        path = Path(handle.name)
        digest = hashlib.sha256()
        size = 0
        try:
            for chunk in chunks:
                raw = bytes(chunk)
                if not raw:
                    continue
                size += len(raw)
                if max_bytes is not None and size > max_bytes:
                    raise ValueError(
                        f"temporary binary payload exceeds {max_bytes} bytes"
                    )
                handle.write(raw)
                digest.update(raw)
            handle.flush()
            handle.seek(0)
            return cls(
                handle,
                path=path,
                size=size,
                sha256=digest.hexdigest(),
            )
        except Exception:
            handle.close()
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @property
    def path(self) -> Path:
        return self._path

    @property
    def size(self) -> int:
        return self._size

    @property
    def sha256(self) -> str:
        return self._sha256

    @property
    def closed(self) -> bool:
        return self._closed

    def iter_chunks(
        self,
        chunk_size: int = DEFAULT_BINARY_CHUNK_SIZE,
    ) -> Iterator[bytes]:
        if self._closed:
            raise ValueError("temporary binary payload is closed")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

        self._file.seek(0)
        try:
            while True:
                chunk = self._file.read(chunk_size)
                if not chunk:
                    break
                yield bytes(chunk)
        finally:
            if not self._closed:
                self._file.seek(0)

    def read_bytes(self) -> bytes:
        return b"".join(self.iter_chunks())

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._file.close()
        finally:
            try:
                self._path.unlink(missing_ok=True)
            except OSError:
                # Best effort in object finalization. Explicit conversion
                # cleanup still closes every temporary payload deterministically.
                pass

    def __len__(self) -> int:
        return self._size

    def __bytes__(self) -> bytes:
        return self.read_bytes()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TemporaryBinaryPayload):
            return (
                self.size == other.size
                and self.sha256 == other.sha256
                and bytes(self) == bytes(other)
            )
        if isinstance(other, (bytes, bytearray, memoryview)):
            raw = bytes(other)
            return (
                len(raw) == self.size
                and hashlib.sha256(raw).hexdigest() == self.sha256
                and bytes(self) == raw
            )
        return NotImplemented

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


BinaryData: TypeAlias = bytes | TemporaryBinaryPayload


def is_temporary_binary(value: object) -> bool:
    return isinstance(value, TemporaryBinaryPayload)


def binary_size(value: BinaryData | bytearray | memoryview) -> int:
    return len(value)


def iter_binary_chunks(
    value: BinaryData | bytearray | memoryview,
    chunk_size: int = DEFAULT_BINARY_CHUNK_SIZE,
) -> Iterator[bytes]:
    if isinstance(value, TemporaryBinaryPayload):
        yield from value.iter_chunks(chunk_size)
        return

    view = memoryview(value)
    for offset in range(0, len(view), chunk_size):
        yield bytes(view[offset : offset + chunk_size])


def binary_sha256(value: BinaryData | bytearray | memoryview) -> str:
    if isinstance(value, TemporaryBinaryPayload):
        return value.sha256

    digest = hashlib.sha256()
    for chunk in iter_binary_chunks(value):
        digest.update(chunk)
    return digest.hexdigest()


def binary_bytes(value: BinaryData | bytearray | memoryview) -> bytes:
    if isinstance(value, TemporaryBinaryPayload):
        return value.read_bytes()
    return bytes(value)
