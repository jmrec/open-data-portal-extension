from __future__ import annotations

from datetime import date

from open_data_portal_extension.models.psgc import GeoLevel, PsgcCrosswalk
from open_data_portal_extension.reference import ReferenceStore
from open_data_portal_extension.reference_build import write_reference
from tests.catalog import (
    BATAC,
    ILOCOS_NORTE,
    LAOAG,
    OLD_LAOAG,
    REGION_I,
    REGION_II,
    SAN_ISIDRO_NORTE,
    SNAPSHOT,
    VIGAN,
    make_crosswalk,
    make_entries,
)


def test_snapshot(reference):
    assert reference.snapshot().version == SNAPSHOT.version


def test_lookup_is_scoped_to_parent(reference):
    scoped = reference.lookup(GeoLevel.CITY_MUNICIPALITY, "san isidro", ILOCOS_NORTE)
    assert [entry.code for entry in scoped] == [SAN_ISIDRO_NORTE]

    nationwide = reference.lookup(GeoLevel.CITY_MUNICIPALITY, "san isidro")
    assert len(nationwide) == 2


def test_children_and_get(reference):
    assert [entry.code for entry in reference.children(None)] == [REGION_I, REGION_II]
    assert [entry.code for entry in reference.children(ILOCOS_NORTE)] == [
        LAOAG,
        BATAC,
        SAN_ISIDRO_NORTE,
    ]
    assert reference.get(LAOAG).name == "City of Laoag"
    assert reference.get("0000000000") is None


def test_crosswalk_resolution(reference):
    assert reference.resolve_crosswalk(OLD_LAOAG) == [LAOAG]
    assert reference.resolve_crosswalk(VIGAN) == [VIGAN]


def test_crosswalk_after_the_snapshot_is_ignored():
    later = PsgcCrosswalk(
        old_code=OLD_LAOAG,
        new_codes=[LAOAG],
        change="merged",
        effective=date(2030, 1, 1),
    )
    store = ReferenceStore(SNAPSHOT, make_entries(), crosswalk=[later])
    assert store.resolve_crosswalk(OLD_LAOAG) == [OLD_LAOAG]


def test_written_database_reads_back(tmp_path):
    path = tmp_path / "psgc.duckdb"
    write_reference(
        path,
        SNAPSHOT,
        make_entries(),
        aliases=[(LAOAG, "Laoag City Proper"), (LAOAG, "LAOAG CITY PROPER")],
        crosswalk=make_crosswalk(),
    )
    with ReferenceStore.open(path) as store:
        assert store.snapshot() == SNAPSHOT
        matches = store.lookup(GeoLevel.CITY_MUNICIPALITY, "laoag")
        assert [entry.code for entry in matches] == [LAOAG]
        assert store.resolve_crosswalk(OLD_LAOAG) == [LAOAG]
        aliased = store.lookup(GeoLevel.CITY_MUNICIPALITY, "laoag city proper")
        assert [entry.code for entry in aliased] == [LAOAG]
        assert not store.has_boundaries()


def test_alias_resolves_to_the_same_entry():
    store = ReferenceStore(
        SNAPSHOT,
        make_entries(),
        aliases=[(LAOAG, "Laoag City Proper"), (LAOAG, "Laoag")],
    )
    matches = store.lookup(GeoLevel.CITY_MUNICIPALITY, "laoag city proper")
    assert [entry.code for entry in matches] == [LAOAG]
    scoped = store.lookup(GeoLevel.CITY_MUNICIPALITY, "laoag city proper", ILOCOS_NORTE)
    assert [entry.code for entry in scoped] == [LAOAG]
    # An alias equal to the official name returns the entry once, not twice.
    assert len(store.lookup(GeoLevel.CITY_MUNICIPALITY, "laoag")) == 1
