"""Integration tests against the real reference database.

They need ``data/psgc-v1.0.1.duckdb`` (``just build-reference``), or another one
in ``$PSGC_REFERENCE_DB``, and are skipped without it. Run only these with
``just test-integration``.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from open_data_portal_extension.cli import app
from open_data_portal_extension.dataset import ColumnDetector
from open_data_portal_extension.models.tagging import MatchMethod, TagStatus
from open_data_portal_extension.reference import ReferenceStore
from open_data_portal_extension.tagging import TaggingPipeline

REAL_DB = Path(
    os.environ.get(
        "PSGC_REFERENCE_DB",
        Path(__file__).parent.parent / "data" / "psgc-v1.0.1.duckdb",
    )
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not REAL_DB.exists(), reason="run `just build-reference` first"),
]


@pytest.fixture(scope="module")
def store():
    with ReferenceStore.open(REAL_DB) as store:
        yield store


def _tag(store, row):
    profile = ColumnDetector().profile([row], dataset_key="d")
    return TaggingPipeline(store).tag_row(profile, row, row_id="1")


@pytest.mark.parametrize(
    ("location", "code"),
    [
        ("Saysain, Bagac, Bataan", "0300802014"),
        ("Bataan", "0300800000"),  # a bare name is the coarsest place
        ("Orani, Bataan Philippines", "0300809000"),
        ("Orani, Bataan, Philippines", "0300809000"),
        ("Orani, Bataan", "0300809000"),
    ],
)
def test_free_text(store, location, code):
    tag = _tag(store, {"Location": location})
    assert (tag.status, tag.code) == (TagStatus.AUTO, code)


@pytest.mark.parametrize(
    ("province", "city", "code"),
    [
        # A town written with its former name, as election data does.
        ("PALAWAN", "EL NIDO BACUIT", "1705312000"),
        ("RIZAL", "RODRIGUEZ MONTALBAN", "0405808000"),
        ("SULTAN KUDARAT", "LAMBAYONG MARIANO MARCOS", "1206508000"),
        ("CEBU", "LAPU LAPU CITY OPON", "0731100000"),
        # A name split by a space: the edit ratio, not the token set, finds these.
        ("ABRA", "SAL LAPADAN", "1400120000"),
        ("DAVAO ORIENTAL", "BANAY BANAY", "1102502000"),
    ],
)
def test_fuzzy_names(store, province, city, code):
    tag = _tag(store, {"Province": province, "City": city})
    assert (tag.status, tag.code) == (TagStatus.AUTO, code)
    assert tag.method is MatchMethod.NAME_FUZZY


def test_a_former_province_still_finds_the_town(store):
    # Davao Occidental was carved out of Davao del Sur in 2013.
    tag = _tag(store, {"Province": "DAVAO DEL SUR", "City": "SANTA MARIA"})
    assert (tag.status, tag.code) == (TagStatus.AUTO, "1108604000")


def test_a_string_naming_two_towns_goes_to_review(store):
    tag = _tag(store, {"Province": "LAGUNA", "City": "CALAMBA SAN PEDRO"})
    assert tag.status is TagStatus.NEEDS_REVIEW
    assert {c.code for c in tag.candidates[:2]} == {"0403405000", "0403425000"}


def test_cli_tags_a_file_end_to_end(tmp_path):
    source = tmp_path / "towns.csv"
    source.write_text(
        "id,Province,City\n"
        "1,PALAWAN,EL NIDO BACUIT\n"
        "2,LAGUNA,CALAMBA SAN PEDRO\n"
        "3,,\n"
        "4,PALAWAN,EL NIDO BACUIT\n"
    )
    out = tmp_path / "tagged.csv"
    result = CliRunner().invoke(
        app, ["tag", str(source), "-o", str(out), "--db", str(REAL_DB)]
    )
    assert result.exit_code == 0, result.output
    assert "Tagged 4 rows (2 distinct places)" in result.output

    with out.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["id"] for row in rows] == ["1", "2", "3", "4"]  # order kept
    assert [(row["psgc_code"], row["psgc_status"]) for row in rows] == [
        ("1705312000", "auto"),
        ("", "needs_review"),
        ("", "no_place"),
        ("1705312000", "auto"),
    ]
    assert rows[0]["psgc_level"] == "city_municipality"
