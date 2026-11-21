import json
import sqlite3

import duckdb
import pytest
from typer.testing import CliRunner

from open_data_portal_extension.catalog import export_catalog
from open_data_portal_extension.cli.main import app
from open_data_portal_extension.manifest import DatasetConfig

CAR = "1400000000"
BENGUET = "1401100000"
LA_TRINIDAD = "1401110000"
BETAG = "1401110002"
BAGUIO = "1430300000"  # highly urbanized: its code doesn't hold Benguet's
KABAYANIHAN = "1430300142"
NCR = "1300000000"
MANILA_DISTRICT = "1303900000"
MANILA = "1380600000"
TONDO = "1380601000"  # sub-municipality, skipped in lineage
BARANGAY_1 = "1380601001"

ENTRIES = [
    (CAR, "Cordillera Administrative Region", "region", None),
    (BENGUET, "Benguet", "province", CAR),
    (LA_TRINIDAD, "La Trinidad", "city_municipality", BENGUET),
    (BETAG, "Betag", "barangay", LA_TRINIDAD),
    (BAGUIO, "City of Baguio", "city_municipality", BENGUET),
    (KABAYANIHAN, "Kabayanihan", "barangay", BAGUIO),
    (NCR, "National Capital Region", "region", None),
    (MANILA_DISTRICT, "NCR, City of Manila, First District", "province", NCR),
    (MANILA, "City of Manila", "city_municipality", MANILA_DISTRICT),
    (TONDO, "Tondo I/II", "sub_municipality", MANILA),
    (BARANGAY_1, "Barangay 1", "barangay", MANILA),
]

runner = CliRunner()


@pytest.fixture
def reference(tmp_path):
    path = tmp_path / "psgc.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE psgc_entries (code VARCHAR PRIMARY KEY, name VARCHAR, "
        "normalized_name VARCHAR, level VARCHAR, parent_code VARCHAR, "
        "valid_from DATE, valid_to DATE)"
    )
    con.executemany(
        "INSERT INTO psgc_entries VALUES (?, ?, lower(?), ?, ?, NULL, NULL)",
        [(code, name, name, level, parent) for code, name, level, parent in ENTRIES],
    )
    # A retired code: current tags never point here, so it isn't a place.
    con.execute(
        "INSERT INTO psgc_entries VALUES "
        "('1401199000', 'Old Town', 'old town', 'city_municipality', ?, NULL, "
        "DATE '2001-01-01')",
        [BENGUET],
    )
    con.close()
    return path


@pytest.fixture
def outputs(tmp_path):
    facilities = tmp_path / "facilities.csv"
    facilities.write_text(
        "name,kind,psgc_code,psgc_level,psgc_status,psgc_confidence\n"
        f"Notre Dame Hospital,hospital,{KABAYANIHAN},barangay,auto,1.0\n"
        f"Benguet State University,school,{BETAG},barangay,auto,0.9\n"
        f"Tondo Medical Center,hospital,{BARANGAY_1},barangay,auto,1.0\n"
        "Somewhere,school,,,needs_review,0.4\n"
    )
    officials = tmp_path / "officials.csv"
    officials.write_text(
        "official,town,psgc_code,psgc_level,psgc_status,psgc_confidence\n"
        f"A. Mayor,Baguio,{BAGUIO},city_municipality,auto,1.0\n"
        "B. Nobody,,,,no_place,\n"
    )
    return [
        DatasetConfig(
            name="facilities",
            source="x",
            output=facilities,
            description="Hospitals and schools",
            license="ODbL",
        ),
        DatasetConfig(name="officials", source="x", output=officials),
        DatasetConfig(name="untagged", source="x", output=tmp_path / "nope.csv"),
    ]


def _query(path, sql, *params):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def test_lineage_walks_parents_not_codes(reference, outputs, tmp_path):
    out = tmp_path / "catalog.sqlite"
    export_catalog(outputs, reference, out)

    lineage = {
        row[0]: row[1:]
        for row in _query(
            out,
            "SELECT code, barangay, city_municipality, province, region FROM lineage",
        )
    }
    assert lineage[KABAYANIHAN] == (KABAYANIHAN, BAGUIO, BENGUET, CAR)
    assert lineage[BAGUIO] == (None, BAGUIO, BENGUET, CAR)
    assert lineage[BARANGAY_1] == (BARANGAY_1, MANILA, MANILA_DISTRICT, NCR)
    assert TONDO in lineage  # listed, but no level of its own
    assert "1401199000" not in lineage


def test_rows_count_at_every_level_above_them(reference, outputs, tmp_path):
    out = tmp_path / "catalog.sqlite"
    summary = export_catalog(outputs, reference, out)

    assert summary.datasets == {"facilities": 3, "officials": 1}
    assert summary.missing == ["untagged"]
    counts = {
        (dataset, code): (level, rows)
        for dataset, code, level, rows in _query(
            out, "SELECT dataset, code, level, rows FROM place_counts"
        )
    }
    assert counts[("facilities", KABAYANIHAN)] == ("barangay", 1)
    assert counts[("facilities", BAGUIO)] == ("city_municipality", 1)
    assert counts[("facilities", BENGUET)] == ("province", 2)
    assert counts[("facilities", CAR)] == ("region", 2)
    assert counts[("facilities", NCR)] == ("region", 1)
    assert counts[("officials", BENGUET)] == ("province", 1)
    assert ("officials", KABAYANIHAN) not in counts


def test_rows_keep_source_columns_and_dataset_metadata(reference, outputs, tmp_path):
    out = tmp_path / "catalog.sqlite"
    export_catalog(outputs, reference, out)

    [(data, confidence)] = _query(
        out, "SELECT data, confidence FROM rows WHERE code = ?", BETAG
    )
    assert json.loads(data) == {"name": "Benguet State University", "kind": "school"}
    assert confidence == 0.9
    assert _query(out, "SELECT * FROM datasets WHERE name = 'facilities'") == [
        ("facilities", "Hospitals and schools", None, "ODbL", None, 4, 3, 1, 0)
    ]
    assert not out.with_name("catalog.sqlite.partial").exists()


def test_export_command_writes_next_to_the_manifest(reference, tmp_path):
    (tmp_path / "data/output").mkdir(parents=True)
    (tmp_path / "data/output/towns.csv").write_text(
        "Town,psgc_code,psgc_level,psgc_status,psgc_confidence\n"
        f"Baguio,{BAGUIO},city_municipality,auto,1.0\n"
    )
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        f'[reference]\ndb = "{reference}"\n\n'
        '[[datasets]]\nname = "towns"\nsource = "towns.csv"\n'
    )
    result = runner.invoke(app, ["export", "--manifest", str(manifest)])
    assert result.exit_code == 0, result.output
    assert "towns: 1 tagged rows" in result.output
    assert _query(
        tmp_path / "data/output/catalog.sqlite",
        "SELECT rows FROM place_counts WHERE code = ?",
        BENGUET,
    ) == [(1,)]
