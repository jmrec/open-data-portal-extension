from __future__ import annotations

import csv

import duckdb
import pytest

from open_data_portal_extension.tabular import tag_table
from tests.catalog import LAOAG, VIGAN


def write_csv(path, text):
    path.write_text(text)
    return path


def read(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_tags_every_row_and_keeps_order(reference, tmp_path):
    source = write_csv(
        tmp_path / "facilities.csv",
        "id,Province,City\n"
        "3,Ilocos Sur,Vigan\n"
        "1,Ilocos Norte,Laoag\n"
        "2,Ilocos Norte,Laoag\n"
        "4,Ilocos Norte,\n"
        "5,,\n",
    )
    out = tmp_path / "out.csv"

    result = tag_table(source, reference, output=out)

    rows = read(out)
    assert [row["id"] for row in rows] == ["3", "1", "2", "4", "5"]
    assert [row["psgc_code"] for row in rows[:3]] == [VIGAN, LAOAG, LAOAG]
    assert rows[3]["psgc_level"] == "province"
    assert rows[4]["psgc_status"] == "no_place"
    assert result.rows == 5
    assert result.distinct_places == 3  # Laoag twice is resolved once
    assert result.failures == []  # a row with no place is not a review
    assert result.rows_by_status == {"auto": 4, "no_place": 1}


def test_a_datasets_own_codes_are_evidence_and_keep_leading_zeros(reference, tmp_path):
    source = write_csv(tmp_path / "coded.csv", f"id,psgc_code\na,{LAOAG}\n")
    out = tmp_path / "out.csv"

    result = tag_table(source, reference, output=out)

    assert result.rows_by_status == {"auto": 1}
    row = read(out)[0]
    assert row["psgc_code"] == LAOAG
    assert list(row) == [
        "id",
        "psgc_code",
        "psgc_level",
        "psgc_status",
        "psgc_confidence",
    ]


def test_overrides_replace_detection(reference, tmp_path):
    source = write_csv(tmp_path / "towns.csv", "Lalawigan,Bayan\nIlocos Norte,Laoag\n")

    detected = tag_table(source, reference)
    assert detected.rows_by_status == {"no_place": 1}

    overridden = tag_table(
        source,
        reference,
        overrides={"Lalawigan": "province", "Bayan": "city_municipality"},
    )
    assert overridden.rows_by_status == {"auto": 1}
    assert overridden.auto_rows_by_level == {"city_municipality": 1}


def test_unknown_override_column_is_an_error(reference, tmp_path):
    source = write_csv(tmp_path / "x.csv", "City\nLaoag\n")
    with pytest.raises(ValueError, match="no such column: Town"):
        tag_table(source, reference, overrides={"Town": "city_municipality"})


def test_retagging_replaces_earlier_psgc_columns(reference, tmp_path):
    source = write_csv(tmp_path / "x.csv", "City\nLaoag\n")
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    tag_table(source, reference, output=first)
    tag_table(first, reference, output=second)

    header = second.read_text().splitlines()[0].split(",")
    assert header == [
        "City",
        "psgc_code",
        "psgc_level",
        "psgc_status",
        "psgc_confidence",
    ]
    assert read(second)[0]["psgc_code"] == LAOAG


@pytest.mark.parametrize("suffix", [".parquet", ".jsonl"])
def test_writes_parquet_and_json_lines(reference, tmp_path, suffix):
    source = write_csv(tmp_path / "x.csv", "City\nLaoag\n")
    out = tmp_path / f"out{suffix}"

    tag_table(source, reference, output=out)

    reader = "read_parquet" if suffix == ".parquet" else "read_json_auto"
    rows = duckdb.sql(f"SELECT psgc_code FROM {reader}('{out}')").fetchall()
    assert rows == [(LAOAG,)]


def test_unsupported_format_is_an_error(reference, tmp_path):
    source = tmp_path / "x.xlsx"
    source.write_text("")
    with pytest.raises(ValueError, match="unsupported dataset format"):
        tag_table(source, reference)
