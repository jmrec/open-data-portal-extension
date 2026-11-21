from __future__ import annotations

import pytest
from pydantic import ValidationError

from open_data_portal_extension.manifest import load_manifest
from open_data_portal_extension.models.psgc import GeoLevel


def write(tmp_path, text):
    path = tmp_path / "manifest.toml"
    path.write_text(text)
    return path


def test_paths_are_relative_to_the_manifest(tmp_path):
    manifest = load_manifest(
        write(
            tmp_path,
            """
[reference]
db = "data/psgc.duckdb"

[[datasets]]
name = "schools"
source = "data/schools.csv"
level = "barangay"

[datasets.columns]
street_address = "free_text"

[[datasets]]
name = "winners"
source = "https://example.org/winners.csv"
output = "out/winners.parquet"
eval = true
""",
        )
    )

    schools, winners = manifest.datasets
    assert manifest.reference.db == tmp_path / "data/psgc.duckdb"
    assert schools.source == str(tmp_path / "data/schools.csv")
    assert schools.output == tmp_path / "data/output/schools.csv"
    assert schools.level is GeoLevel.BARANGAY
    assert schools.columns == {"street_address": "free_text"}
    assert winners.source == "https://example.org/winners.csv"
    assert winners.output == tmp_path / "out/winners.parquet"
    assert manifest.eval.baselines == tmp_path / "evals/baselines"


def test_typos_are_rejected(tmp_path):
    path = write(tmp_path, '[[datasets]]\nname = "a"\nsource = "a.csv"\ncolums = {}\n')
    with pytest.raises(ValidationError, match="colums"):
        load_manifest(path)


def test_column_settings_are_checked(tmp_path):
    path = write(
        tmp_path,
        '[[datasets]]\nname = "a"\nsource = "a.csv"\n'
        '[datasets.columns]\nTown = "municipality"\n',
    )
    with pytest.raises(ValidationError, match="Town = 'municipality'"):
        load_manifest(path)


def test_names_are_unique(tmp_path):
    path = write(
        tmp_path,
        '[[datasets]]\nname = "a"\nsource = "a.csv"\n'
        '[[datasets]]\nname = "a"\nsource = "b.csv"\n',
    )
    with pytest.raises(ValidationError, match="unique: a"):
        load_manifest(path)


def test_select_keeps_manifest_order_and_rejects_unknown_names(tmp_path):
    manifest = load_manifest(
        write(
            tmp_path,
            '[[datasets]]\nname = "a"\nsource = "a.csv"\n'
            '[[datasets]]\nname = "b"\nsource = "b.csv"\n',
        )
    )
    assert [d.name for d in manifest.select(["b", "a"])] == ["a", "b"]
    assert [d.name for d in manifest.select()] == ["a", "b"]
    with pytest.raises(ValueError, match="not in the manifest: c"):
        manifest.select(["c"])
