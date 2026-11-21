from __future__ import annotations

import csv

import pytest
from typer.testing import CliRunner

from open_data_portal_extension.cli import app
from tests.test_reference_build import (
    BARANGAYS,
    CITIES,
    PROVINCES,
    REGIONS,
)

runner = CliRunner()


@pytest.fixture
def db(tmp_path):
    source = tmp_path / "csvs"
    source.mkdir()
    (source / "PH_Adm1_Regions.csv").write_text(REGIONS)
    (source / "PH_Adm2_ProvDists.csv").write_text(PROVINCES)
    (source / "PH_Adm3_MuniCities.csv").write_text(CITIES)
    (source / "PH_Adm4_BgySubMuns.csv").write_text(BARANGAYS)
    out = tmp_path / "psgc.duckdb"
    result = runner.invoke(
        app,
        [
            "build-reference",
            str(source),
            str(out),
            "--version",
            "v1.0.1",
            "--released-on",
            "2026-10-12",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Wrote 9 entries (v1.0.1)" in result.output
    return out


def test_resolve_prints_the_chosen_place(db):
    result = runner.invoke(app, ["resolve", "Saysain, Bagac", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("auto")
    assert "* 0300802014" in result.output
    assert "Saysain" in result.output


def test_tag_adds_psgc_columns(db, tmp_path):
    source = tmp_path / "facilities.csv"
    source.write_text('id,Location\na,"Saysain, Bagac"\nb,Nowhere\nc,\n')
    out = tmp_path / "tagged.csv"

    result = runner.invoke(
        app,
        ["tag", str(source), "-o", str(out), "--db", str(db)],
    )

    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(out.open()))
    assert [(r["id"], r["psgc_code"], r["psgc_status"]) for r in rows] == [
        ("a", "0300802014", "auto"),
        ("b", "", "needs_review"),
        ("c", "", "no_place"),
    ]
    assert "Tagged 3 rows (2 distinct places): 1 auto, 1 needs_review, 1 no_place" in (
        result.output
    )


def test_tag_without_output_only_reports(db, tmp_path):
    source = tmp_path / "x.csv"
    source.write_text('Location\n"Saysain, Bagac"\n')
    result = runner.invoke(app, ["tag", str(source), "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "Auto-tagged 100.0%" in result.output
    assert "psgc_code" not in result.output


def test_tag_rejects_a_bad_override(db, tmp_path):
    source = tmp_path / "x.csv"
    source.write_text("Town\nBagac\n")
    result = runner.invoke(
        app, ["tag", str(source), "--column", "Town=town", "--db", str(db)]
    )
    assert result.exit_code == 2
    assert "NAME=SETTING" in result.output


def _manifest(tmp_path, db):
    (tmp_path / "towns.csv").write_text("Province,Town\nBataan,Bagac\n")
    (tmp_path / "places.csv").write_text('Location\n"Saysain, Bagac"\n')
    path = tmp_path / "manifest.toml"
    path.write_text(
        f"""
[reference]
db = "{db}"

[[datasets]]
name = "towns"
source = "towns.csv"
level = "city_municipality"
eval = true

[datasets.columns]
Town = "city_municipality"

[[datasets]]
name = "places"
source = "places.csv"
level = "barangay"
"""
    )
    return path


def test_run_tags_every_manifest_dataset(db, tmp_path):
    manifest = _manifest(tmp_path, db)
    result = runner.invoke(app, ["run", "--manifest", str(manifest)])
    assert result.exit_code == 0, result.output

    towns = list(csv.DictReader((tmp_path / "data/output/towns.csv").open()))
    assert towns[0]["psgc_code"] == "0300802000"
    places = list(csv.DictReader((tmp_path / "data/output/places.csv").open()))
    assert places[0]["psgc_code"] == "0300802014"
    # Free text has no column level, so the expected level cannot be confirmed.
    assert "Warning: expected barangay" in result.output


def test_run_one_dataset_and_reject_unknown_names(db, tmp_path):
    manifest = _manifest(tmp_path, db)
    result = runner.invoke(app, ["run", "towns", "--manifest", str(manifest)])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "data/output/places.csv").exists()

    result = runner.invoke(app, ["run", "nope", "--manifest", str(manifest)])
    assert result.exit_code == 1
    assert "not in the manifest: nope" in result.output


def test_eval_saves_and_compares_baselines(db, tmp_path):
    manifest = _manifest(tmp_path, db)
    first = runner.invoke(app, ["eval", "--save", "--manifest", str(manifest)])
    assert first.exit_code == 0, first.output
    assert "== towns" in first.output and "== places" not in first.output
    baseline = tmp_path / "evals/baselines/towns.json"
    assert '"auto_rate": 1.0' in baseline.read_text()

    (tmp_path / "towns.csv").write_text("Province,Town\nBataan,Bagac\nBataan,Nowhere\n")
    second = runner.invoke(app, ["eval", "--manifest", str(manifest)])
    assert "Auto-tag rate        0.5   (was 1.0)" in second.output


def test_invalid_manifest_is_reported(tmp_path):
    path = tmp_path / "manifest.toml"
    path.write_text('[[datasets]]\nname = "Bad Name"\nsource = "x.csv"\n')
    result = runner.invoke(app, ["run", "--manifest", str(path)])
    assert result.exit_code == 1
    assert "Invalid manifest" in result.output


def test_missing_database_explains_how_to_build_it(tmp_path):
    result = runner.invoke(
        app, ["resolve", "Bataan", "--db", str(tmp_path / "x.duckdb")]
    )
    assert result.exit_code == 1
    assert "just build-reference" in result.output


def test_bad_release_date_is_rejected(tmp_path):
    result = runner.invoke(
        app,
        [
            "build-reference",
            str(tmp_path),
            str(tmp_path / "o.duckdb"),
            "--version",
            "v1",
            "--released-on",
            "October",
        ],
    )
    assert result.exit_code == 2


def test_resolve_says_how_many_candidates_are_hidden(tmp_path):
    from datetime import date

    from open_data_portal_extension.models.psgc import GeoLevel, PsgcEntry, PsgcSnapshot
    from open_data_portal_extension.reference_build import write_reference

    path = tmp_path / "many.duckdb"
    write_reference(
        path,
        PsgcSnapshot(version="t", released_on=date(2026, 1, 1)),
        [
            PsgcEntry(code=f"0{n}00000000", name=f"Region {n}", level=GeoLevel.REGION)
            for n in range(1, 8)
        ]
        + [
            PsgcEntry(
                code=f"0{n}01000000",
                name="San Isidro",
                level=GeoLevel.PROVINCE,
                parent_code=f"0{n}00000000",
            )
            for n in range(1, 8)
        ],
    )

    result = runner.invoke(app, ["resolve", "San Isidro", "--db", str(path)])
    assert result.exit_code == 0, result.output
    assert "... and 2 more (show them with --limit 7)" in result.output

    result = runner.invoke(
        app, ["resolve", "San Isidro", "--limit", "7", "--db", str(path)]
    )
    assert "more" not in result.output
    assert result.output.count("San Isidro") == 7


def test_eval_samples_labels_and_scores_checked_ones(db, tmp_path):
    manifest = _manifest(tmp_path, db)
    (tmp_path / "towns.csv").write_text(
        "Province,Town\nBataan,Bagac\nBataan,Nowhere\nBataan,Bagac\n"
    )
    sampled = runner.invoke(app, ["eval", "--sample", "5", "--manifest", str(manifest)])
    assert sampled.exit_code == 0, sampled.output
    assert "Added 2 places" in sampled.output
    assert "Baselines unchanged" in sampled.output
    assert not (tmp_path / "evals/baselines/towns.json").exists()

    labels = tmp_path / "evals/labels/towns.csv"
    with labels.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    bagac = next(row for row in rows if row["Town"] == "Bagac")
    assert bagac["proposed_code"] == "0300802000"
    assert bagac["proposed_place"].startswith("Bagac, Bataan")
    assert bagac["rows"] == "2"

    # A reviewer says Bagac is really some other code: the auto tag is now wrong.
    for row in rows:
        row["checked"] = "jm"
        if row["Town"] == "Bagac":
            row["expected_code"] = "0300899000"
    with labels.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    scored = runner.invoke(app, ["eval", "--manifest", str(manifest)])
    assert scored.exit_code == 0, scored.output
    assert "'auto_precision': 0.0" in scored.output
    assert "wrong  Bataan | Bagac  expected 0300899000, got 0300802000" in scored.output

    again = runner.invoke(app, ["eval", "--sample", "5", "--manifest", str(manifest)])
    assert "Added 0 places" in again.output
