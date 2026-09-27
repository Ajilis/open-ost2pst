import tempfile

import pytest

from open_ost2pst.pst.image import build_minimal_ndb


pypff = pytest.importorskip("pypff")


def test_libpff_opens_generated_minimal_ndb() -> None:
    result = build_minimal_ndb()

    with tempfile.NamedTemporaryFile(suffix=".pst") as handle:
        handle.write(result.data)
        handle.flush()

        store = pypff.file()
        store.open(handle.name)
        store.close()
