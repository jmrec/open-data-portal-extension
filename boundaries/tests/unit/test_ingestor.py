"""Unit tests for `LocalDataIngestor`.

`tests/fixtures/municities` is a miniature project mirroring the `municities`
dataset in `manifest.yml`, whose source is a glob (`raw/municities/*.json`).
"""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from ph_administrative_boundaries.ingest import LocalDataIngestor, sha256_file
from ph_administrative_boundaries.manifest import YamlManifest
from ph_administrative_boundaries.types import DatasetSpec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "municities"


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    destination = tmp_path / "project"
    shutil.copytree(FIXTURES, destination)
    return destination


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path / ".cache" / "build"


@pytest.fixture()
def municities(project: Path) -> DatasetSpec:
    return YamlManifest().load(project / "manifest.yml").get("municities")


@pytest.fixture()
def ingestor(workspace: Path) -> LocalDataIngestor:
    return LocalDataIngestor(workspace)


def declare(project: Path, source: str) -> DatasetSpec:
    """Load a dataset from a manifest declaring `source` outside the fixture."""
    path = project / "declared.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "datasets": {
                    "municities": {
                        "source": source,
                        "steps": [
                            {
                                "run": "mapshaper -i {in} -o {out}",
                                "out": "municities.geojson",
                            }
                        ],
                    }
                }
            }
        )
    )
    return YamlManifest().load(path).get("municities")


def test_manifest_resolves_glob_under_data(
    project: Path, municities: DatasetSpec
) -> None:
    assert municities.sources == {
        "source": project / "data" / "raw" / "municities" / "*.json"
    }


def test_ingestor_can_ingest_glob(
    municities: DatasetSpec, ingestor: LocalDataIngestor, workspace: Path
) -> None:
    artifact = ingestor.ingest(municities)["source"]

    assert artifact.path == workspace / "raw" / "municities" / "source.geojson"
    assert artifact.sha256 == sha256_file(artifact.path)

    sources = sorted(municities.sources["source"].parent.glob("*.json"))
    assert len(sources) > 1
    assert json.loads(artifact.path.read_text()) == {
        "type": "FeatureCollection",
        "features": [
            feature
            for source in sources
            for feature in json.loads(source.read_text())["features"]
        ],
    }


def test_glob_merge_is_deterministic(
    municities: DatasetSpec, ingestor: LocalDataIngestor
) -> None:
    first = ingestor.ingest(municities)["source"]
    second = ingestor.ingest(municities)["source"]

    assert second.sha256 == first.sha256


def test_ingestor_reports_glob_matching_nothing(
    project: Path, ingestor: LocalDataIngestor
) -> None:
    spec = declare(project, "raw/municities/*.geojson")

    with pytest.raises(FileNotFoundError, match="matched no files"):
        ingestor.ingest(spec)


def test_ingestor_passes_a_single_source_through(
    project: Path, ingestor: LocalDataIngestor, workspace: Path
) -> None:
    source = "raw/municities/bgysubmuns-municity-1001301000.0.1.json"
    spec = declare(project, source)

    artifact = ingestor.ingest(spec)["source"]

    assert artifact.path == project / "data" / source
    assert artifact.sha256 == sha256_file(artifact.path)
    assert not (workspace / "raw").exists()


def test_ingestor_reports_a_missing_source(
    project: Path, ingestor: LocalDataIngestor
) -> None:
    spec = declare(project, "raw/missing.geojson")

    with pytest.raises(FileNotFoundError, match="is missing"):
        ingestor.ingest(spec)
