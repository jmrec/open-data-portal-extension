from __future__ import annotations

import csv
import json

import duckdb
import pytest

from open_data_portal_extension.reference import BOUNDARY_CRS, ReferenceStore
from open_data_portal_extension.reference_build import write_reference
from open_data_portal_extension.tabular import tag_table
from tests.catalog import (
    BARANGAY_SAN_ISIDRO,
    SNAPSHOT,
    VIGAN,
    make_entries,
)

# A point in Vigan, and the barangay drawn as a 1 km square around it.
LAT, LON = 17.5747, 120.3869
NEARBY = (LAT, LON + 0.0060)  # about 100 m east of the square's edge
FAR = (LAT, LON + 0.1)  # about 10 km east


def _square_wkt(lat: float, lon: float, half_m: float) -> str:
    """A square ``half_m`` meters from its center to each side, in lon/lat."""
    connection = duckdb.connect()
    try:
        connection.execute("INSTALL spatial; LOAD spatial")
        return connection.execute(
            "SELECT ST_AsText(ST_Transform(ST_Buffer(ST_Transform(ST_Point(?, ?), "
            f"'EPSG:4326', '{BOUNDARY_CRS}', always_xy := true), ?, 1), "
            f"'{BOUNDARY_CRS}', 'EPSG:4326', always_xy := true))",
            [lon, lat, half_m],
        ).fetchone()[0]
    finally:
        connection.close()


@pytest.fixture
def located_reference(tmp_path):
    try:
        square = _square_wkt(LAT, LON, 500)
        boundaries = _geoparquet(
            tmp_path / "bgy.parquet", [(BARANGAY_SAN_ISIDRO, "Bgy", square)]
        )
    except duckdb.Error as error:  # no network to install the extension
        pytest.skip(f"DuckDB spatial extension unavailable: {error}")
    path = tmp_path / "psgc.duckdb"
    write_reference(path, SNAPSHOT, make_entries(), boundaries=boundaries)
    with ReferenceStore.open(path) as store:
        yield store


def _csv(path, header, *rows):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _read(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_locate_inside_nearby_and_far(located_reference):
    found = located_reference.locate([(LAT, LON), NEARBY, FAR])
    assert found[(LAT, LON)] == (BARANGAY_SAN_ISIDRO, 0.0)
    code, meters = found[NEARBY]
    assert code == BARANGAY_SAN_ISIDRO and 50 < meters < 250
    assert FAR not in found


def test_points_only_are_tagged_at_barangay_level(located_reference, tmp_path):
    source = _csv(
        tmp_path / "points.csv",
        ["name", "latitude", "longitude"],
        ["inside", LAT, LON],
        ["nearby", *NEARBY],
        ["far", *FAR],
    )
    out = tmp_path / "out.csv"

    result = tag_table(source, located_reference, output=out)

    rows = {row["name"]: row for row in _read(out)}
    assert rows["inside"]["psgc_code"] == BARANGAY_SAN_ISIDRO
    assert rows["inside"]["psgc_level"] == "barangay"
    assert rows["inside"]["psgc_status"] == "auto"
    assert rows["nearby"]["psgc_status"] == "needs_review"
    assert rows["far"]["psgc_status"] == "needs_review"
    assert result.coordinates == "latitude, longitude"
    assert result.points == {"inside": 1, "nearby": 1, "not_found": 1}
    assert result.reported_level.value == "barangay"
    assert "latitude" in _read(out)[0]  # source columns are kept as they were


def test_a_matching_name_confirms_a_nearby_point(located_reference, tmp_path):
    source = _csv(tmp_path / "p.csv", ["City", "lat", "lng"], ["Vigan", *NEARBY])
    out = tmp_path / "out.csv"

    tag_table(source, located_reference, output=out)

    row = _read(out)[0]
    # The City column makes this a city-level dataset; the point agrees with it.
    assert (row["psgc_code"], row["psgc_status"]) == (VIGAN, "auto")


def test_coordinate_columns_can_be_set_in_overrides(located_reference, tmp_path):
    source = _csv(tmp_path / "p.csv", ["y", "x"], [LAT, LON])
    result = tag_table(
        source, located_reference, overrides={"y": "latitude", "x": "longitude"}
    )
    assert result.rows_by_status == {"auto": 1}


def test_only_one_coordinate_override_is_an_error(located_reference, tmp_path):
    source = _csv(tmp_path / "p.csv", ["y", "x"], [LAT, LON])
    with pytest.raises(ValueError, match="both a latitude and a longitude"):
        tag_table(source, located_reference, overrides={"y": "latitude"})


def test_geojson_geometry_in_a_json_array(located_reference, tmp_path):
    source = tmp_path / "facilities.json"
    source.write_text(
        json.dumps(
            [
                {
                    "name": "Health Station",
                    "geometry": {"type": "Point", "coordinates": [LON, LAT]},
                }
            ]
        )
    )
    result = tag_table(source, located_reference)
    assert result.coordinates == "geometry"
    assert result.rows_by_status == {"auto": 1}


def test_geojson_feature_collection(located_reference, tmp_path):
    source = tmp_path / "facilities.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Health Station"},
                        "geometry": {"type": "Point", "coordinates": [LON, LAT]},
                    }
                ],
            }
        )
    )
    out = tmp_path / "out.csv"

    tag_table(source, located_reference, output=out)

    assert _read(out)[0]["psgc_code"] == BARANGAY_SAN_ISIDRO


def test_without_boundaries_coordinates_are_noted_not_used(reference, tmp_path):
    source = _csv(tmp_path / "p.csv", ["latitude", "longitude"], [LAT, LON])
    result = tag_table(source, reference)
    assert result.rows_by_status == {"needs_review": 1}
    assert any("no boundaries" in note for note in result.notes)


def _geoparquet(path, rows):
    """Write ``(adm4_psgc, geo_level, WKT in lon/lat)`` rows like
    ph-administrative-boundaries' PH_Adm4_BgySubMuns.parquet."""
    connection = duckdb.connect()
    try:
        connection.execute("INSTALL spatial; LOAD spatial")
        connection.execute(
            "CREATE TABLE b AS SELECT * FROM (VALUES "
            + ", ".join(["(?, ?, ?)"] * len(rows))
            + ") AS t(adm4_psgc, geo_level, wkt)",
            [value for row in rows for value in row],
        )
        connection.execute(
            "COPY (SELECT adm4_psgc, geo_level, ST_GeomFromText(wkt) AS geom FROM b) "
            f"TO '{path}' (FORMAT parquet)"
        )
    finally:
        connection.close()
    return path


def test_boundaries_load_from_geoparquet(tmp_path):
    d = 0.004  # about 450 m
    square = (
        f"POLYGON(({LON - d} {LAT - d}, {LON + d} {LAT - d}, {LON + d} {LAT + d}, "
        f"{LON - d} {LAT + d}, {LON - d} {LAT - d}))"
    )
    try:
        path = _geoparquet(
            tmp_path / "bgy.parquet",
            [
                (BARANGAY_SAN_ISIDRO, "Bgy", square),
                ("0129019999", "Bgy", square),  # not in this snapshot: skipped
                ("0129010000", "SubMun", square),  # overlaps barangays: skipped
            ],
        )
    except duckdb.Error as error:
        pytest.skip(f"DuckDB spatial extension unavailable: {error}")
    db = tmp_path / "psgc.duckdb"
    assert write_reference(db, SNAPSHOT, make_entries(), boundaries=path) == 1
    with ReferenceStore.open(db) as store:
        assert store.locate([(LAT, LON)])[(LAT, LON)] == (BARANGAY_SAN_ISIDRO, 0.0)


def test_boundaries_must_be_longitude_latitude(tmp_path):
    try:
        path = _geoparquet(
            tmp_path / "utm.parquet",
            [(BARANGAY_SAN_ISIDRO, "Bgy", "POLYGON((0 0, 1000 0, 1000 1000, 0 0))")],
        )
    except duckdb.Error as error:
        pytest.skip(f"DuckDB spatial extension unavailable: {error}")
    with pytest.raises(ValueError, match="longitude/latitude"):
        write_reference(
            tmp_path / "psgc.duckdb", SNAPSHOT, make_entries(), boundaries=path
        )
