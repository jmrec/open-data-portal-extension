"""Integration tests that run the real mapshaper and tippecanoe binaries."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from ph_administrative_boundaries.build import (
    BuildPipeline,
    JsonCache,
    Runner,
    SubprocessRunner,
)
from ph_administrative_boundaries.cli import app
from ph_administrative_boundaries.ingest import LocalDataIngestor, sha256_file
from ph_administrative_boundaries.manifest import ManifestError, YamlManifest
from typer.testing import CliRunner

SOURCE = Path(__file__).resolve().parent / "fixtures" / "country" / "country.0.1.json"

requires_tools = pytest.mark.skipif(
    shutil.which("mapshaper") is None or shutil.which("tippecanoe") is None,
    reason="mapshaper and tippecanoe must be installed",
)

STEPS = [
    {
        "run": "mapshaper -i {in} -clean -simplify visvalingam 10% keep-shapes "
        "-o {out} precision=0.00001"
    },
    {
        "run": "tippecanoe -o {out} -f -P --layer=country -Z4 -z14 {in}",
        "out": "country.pmtiles",
    },
]
MANIFEST = {"datasets": {"country": {"source": "raw/source.geojson", "steps": STEPS}}}


class CountingRunner:
    """Delegates to the real runner and records each tool invocation."""

    def __init__(self) -> None:
        self.inner = SubprocessRunner()
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, stream: bool = False) -> str:
        if argv[1:] != ["--version"]:
            self.calls.append([*argv])
        return self.inner.run(argv, stream=stream)


@pytest.fixture(scope="module")
def source_slice(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not SOURCE.is_file():
        pytest.skip(f"missing source data: {SOURCE}")
    collection = json.loads(SOURCE.read_text())
    collection["features"] = collection["features"][:2]
    path = tmp_path_factory.mktemp("slice") / "source.geojson"
    path.write_text(json.dumps(collection))
    return path


@pytest.fixture()
def project(tmp_path: Path, source_slice: Path) -> Path:
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    shutil.copy(source_slice, raw / "source.geojson")
    (tmp_path / "manifest.yml").write_text(yaml.safe_dump(MANIFEST, sort_keys=False))
    return tmp_path


def pipeline(root: Path, runner: Runner, manifest: Path | None = None) -> BuildPipeline:
    workspace = root / ".cache" / "build"
    return BuildPipeline(
        manifest=YamlManifest().load(manifest or root / "manifest.yml"),
        ingestor=LocalDataIngestor(workspace),
        runner=runner,
        cache=JsonCache(workspace / "cache.json"),
        workspace=workspace,
        output_dir=root / "data" / "processed",
    )


def test_manifest_maps_steps(project: Path) -> None:
    spec = YamlManifest().load(project / "manifest.yml").get("country")

    assert spec.sources == {"source": project / "data" / "raw" / "source.geojson"}
    assert [step.out for step in spec.steps] == [None, "country.pmtiles"]


def test_unknown_dataset_is_reported(project: Path) -> None:
    manifest = YamlManifest().load(project / "manifest.yml")

    with pytest.raises(ManifestError, match="unknown dataset 'provinces'"):
        manifest.get("provinces")


def test_ingest_hashes_the_declared_source(project: Path) -> None:
    spec = YamlManifest().load(project / "manifest.yml").get("country")

    artifact = LocalDataIngestor().ingest(spec)["source"]

    assert artifact.path == spec.sources["source"]
    assert artifact.sha256 == sha256_file(spec.sources["source"])


def test_step_without_placeholders_is_rejected(project: Path) -> None:
    config = {
        "datasets": {
            "country": {
                "source": "raw/source.geojson",
                "steps": [{"run": "mapshaper -o out.geojson", "out": "x.geojson"}],
            }
        }
    }
    (project / "manifest.yml").write_text(yaml.safe_dump(config))

    with pytest.raises(ManifestError, match="must use"):
        YamlManifest().load(project / "manifest.yml")


@requires_tools
def test_build_writes_pmtiles(project: Path) -> None:
    artifacts = pipeline(project, CountingRunner()).build("country")

    artifact = artifacts[0]
    assert artifact.path == project / "data" / "processed" / "country.pmtiles"
    assert artifact.path.read_bytes()[:7] == b"PMTiles"
    assert artifact.sha256 == sha256_file(artifact.path)


@requires_tools
def test_rebuild_runs_no_tools(project: Path) -> None:
    first = pipeline(project, CountingRunner()).build("country")
    runner = CountingRunner()

    second = pipeline(project, runner).build("country")

    assert runner.calls == []
    assert second[0].sha256 == first[0].sha256


@requires_tools
def test_changed_command_reruns_tippecanoe_only(project: Path) -> None:
    pipeline(project, CountingRunner()).build("country")
    config = yaml.safe_load((project / "manifest.yml").read_text())
    config["datasets"]["country"]["steps"][1]["run"] = (
        "tippecanoe -o {out} -f -P --layer=country -Z4 -z13 {in}"
    )
    changed = project / "changed.yml"
    changed.write_text(yaml.safe_dump(config))
    runner = CountingRunner()

    pipeline(project, runner, changed).build("country")

    assert [call[0] for call in runner.calls] == ["tippecanoe"]


def test_cli_reports_unknown_dataset(project: Path) -> None:
    result = CliRunner().invoke(
        app, ["build", "provinces", "--manifest", str(project / "manifest.yml")]
    )

    assert result.exit_code == 1
    assert "unknown dataset 'provinces'" in result.output


@requires_tools
def test_cli_build_writes_to_data_processed(project: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "build",
            "country",
            "--manifest",
            str(project / "manifest.yml"),
            "--workspace",
            str(project / ".cache" / "build"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (project / "data" / "processed" / "country.pmtiles").is_file()
