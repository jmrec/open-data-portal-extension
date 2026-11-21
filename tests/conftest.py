from __future__ import annotations

import pytest

from open_data_portal_extension.reference import ReferenceStore
from open_data_portal_extension.reference_build import write_reference
from tests.catalog import SNAPSHOT, make_crosswalk, make_entries


@pytest.fixture
def snapshot():
    return SNAPSHOT


@pytest.fixture(params=["memory", "duckdb"])
def reference(request, snapshot, tmp_path):
    """The same catalog, built in memory and read back from a written database."""
    if request.param == "memory":
        yield ReferenceStore(snapshot, make_entries(), crosswalk=make_crosswalk())
        return
    path = tmp_path / "psgc.duckdb"
    write_reference(path, snapshot, make_entries(), crosswalk=make_crosswalk())
    with ReferenceStore.open(path) as store:
        yield store
