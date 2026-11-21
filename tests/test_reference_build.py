from __future__ import annotations

from datetime import date

import pytest

from open_data_portal_extension.models.psgc import GeoLevel, PsgcSnapshot
from open_data_portal_extension.reference import ReferenceStore
from open_data_portal_extension.reference_build import SourceError, build, load_entries

# Trimmed copies of real rows from release v1.0.1. Codes are written the way the
# source writes them: as numbers, so region 03 has lost its leading zero.
REGIONS = """adm1_psgc,adm1_en,geo_level,len_crs,area_crs,len_km,area_km2
300000000,Region III (Central Luzon),Reg,1,1,1,1.0
1300000000,National Capital Region (NCR),Reg,1,1,1,1.0
"""
PROVINCES = """adm1_psgc,adm2_psgc,adm2_en,geo_level,len_crs,area_crs,len_km,area_km2
300000000,300800000,Bataan,Prov,1,1,1,1.0
1300000000,1303900000,"NCR, City of Manila, First District (Not a Province)",Dist,1,1,1,1.0
"""
CITIES = """adm1_psgc,adm2_psgc,adm3_psgc,adm3_en,geo_level,len_crs,area_crs,len_km,area_km2
300000000,300800000,300802000,Bagac,Mun,1,1,1,1.0
1300000000,1303900000,1380600000,City of Manila,City,1,1,1,1.0
"""
BARANGAYS = """adm1_psgc,adm2_psgc,adm3_psgc,adm4_psgc,adm4_en,geo_level,geom_src,len_crs,area_crs,len_km,area_km2
300000000,300800000,300802000,300802014,Saysain,Bgy,source,1,1,1,1.0
1300000000,1303900000,1380600000,1380601000,Tondo I/II,SubMun,dissolved,1,1,1,1.0
1300000000,1303900000,1380600000,1380601001,Barangay 1,Bgy,source,1,1,1,1.0
1300000000,1303900000,1380600000,1303901906,Manila North Cemetery,,source,1,1,1,0.0
"""

SNAPSHOT = PsgcSnapshot(version="v1.0.1", released_on=date(2026, 10, 12))


@pytest.fixture
def source_dir(tmp_path):
    folder = tmp_path / "v1.0.1"
    folder.mkdir()
    (folder / "PH_Adm1_Regions.csv").write_text(REGIONS)
    (folder / "PH_Adm2_ProvDists.csv").write_text(PROVINCES)
    (folder / "PH_Adm3_MuniCities.csv").write_text(CITIES)
    (folder / "PH_Adm4_BgySubMuns.csv").write_text(BARANGAYS)
    return folder


def test_codes_are_padded_to_ten_digits(source_dir):
    codes = {entry.code for entry in load_entries(source_dir)}
    assert "0300000000" in codes
    assert "0300802014" in codes
    assert all(len(code) == 10 for code in codes)


def test_parents_come_from_the_adm_columns(source_dir):
    entries = {entry.code: entry for entry in load_entries(source_dir)}
    assert entries["0300802014"].parent_code == "0300802000"
    # Manila's code starts 1380 but its parent is the NCR district, 1303900000.
    assert entries["1380600000"].parent_code == "1303900000"
    assert entries["0300000000"].parent_code is None


def test_sub_municipalities_are_kept_and_unlabeled_rows_dropped(source_dir):
    entries = {entry.code: entry for entry in load_entries(source_dir)}
    assert entries["1380601000"].level is GeoLevel.SUB_MUNICIPALITY
    assert entries["1380601001"].level is GeoLevel.BARANGAY
    assert entries["1380601001"].parent_code == "1380600000"
    assert "1303901906" not in entries


def test_missing_parent_fails_the_build(source_dir):
    orphan = "300000000,300800000,300899000,300899001,Nowhere,Bgy,source,1,1,1,1.0\n"
    path = source_dir / "PH_Adm4_BgySubMuns.csv"
    path.write_text(path.read_text() + orphan)
    with pytest.raises(SourceError, match="0300899001"):
        load_entries(source_dir)


def test_missing_file_fails_the_build(source_dir):
    (source_dir / "PH_Adm2_ProvDists.csv").unlink()
    with pytest.raises(SourceError, match="PH_Adm2_ProvDists.csv"):
        load_entries(source_dir)


def test_build_writes_a_store_that_can_be_queried(source_dir, tmp_path):
    out = tmp_path / "psgc.duckdb"
    report = build(source_dir, out, SNAPSHOT)
    assert report.counts[GeoLevel.BARANGAY] == 2
    assert report.total == 9

    store = ReferenceStore.open(out)
    try:
        assert store.snapshot() == SNAPSHOT
        [bagac] = store.lookup(GeoLevel.CITY_MUNICIPALITY, "bagac")
        [saysain] = store.lookup(GeoLevel.BARANGAY, "saysain", bagac.code)
        assert saysain.code == "0300802014"
    finally:
        store.close()
    assert not out.with_name(out.name + ".tmp").exists()


def test_failed_build_keeps_the_previous_file(source_dir, tmp_path):
    out = tmp_path / "psgc.duckdb"
    build(source_dir, out, SNAPSHOT)
    before = out.read_bytes()

    (source_dir / "PH_Adm1_Regions.csv").unlink()
    with pytest.raises(SourceError):
        build(source_dir, out, SNAPSHOT)
    assert out.read_bytes() == before


def test_parenthetical_names_become_aliases(source_dir, tmp_path):
    out = tmp_path / "psgc.duckdb"
    build(source_dir, out, SNAPSHOT)
    store = ReferenceStore.open(out)
    try:
        [region] = store.lookup(GeoLevel.REGION, "central luzon")
        assert region.code == "0300000000"
        # "(Not a Province)" is a remark, not a name.
        assert store.lookup(GeoLevel.PROVINCE, "not a province") == []
    finally:
        store.close()
