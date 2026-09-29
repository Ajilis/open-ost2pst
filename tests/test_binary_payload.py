import hashlib

import pytest

from open_ost2pst.binary_payload import (
    TemporaryBinaryPayload,
    binary_sha256,
    binary_size,
    iter_binary_chunks,
)


def test_temporary_binary_payload_streams_and_hashes(tmp_path) -> None:
    chunks = [b"abc", b"defg", b"hij"]
    payload = TemporaryBinaryPayload.from_chunks(
        chunks,
        max_bytes=10,
        directory=tmp_path,
    )
    payload_path = payload.path

    assert payload_path.parent == tmp_path
    assert payload_path.exists()

    try:
        assert len(payload) == 10
        assert binary_size(payload) == 10
        assert binary_sha256(payload) == hashlib.sha256(b"abcdefghij").hexdigest()
        assert b"".join(iter_binary_chunks(payload, 3)) == b"abcdefghij"
        assert bytes(payload) == b"abcdefghij"
        assert payload == b"abcdefghij"
    finally:
        payload.close()

    assert payload.closed is True
    assert payload_path.exists() is False


def test_temporary_binary_payload_enforces_maximum_size(tmp_path) -> None:
    with pytest.raises(ValueError, match="exceeds 5 bytes"):
        TemporaryBinaryPayload.from_chunks(
            [b"abc", b"def"],
            max_bytes=5,
            directory=tmp_path,
        )

    assert list(tmp_path.glob(".open-ost2pst-*.tmp")) == []
