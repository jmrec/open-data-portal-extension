"""Pipeline behaviour, exercised with a fake runner that copies files.

No external tools are needed. The fake reads every argument that is an existing
file as an input and writes their concatenation to the `-o <path>` output.
"""

import re
from pathlib import Path

import pytest
import structlog
import yaml
from ph_administrative_boundaries.build import (
    BuildPipeline,
    JsonCache,
    ToolError,
    render,
)
from ph_administrative_boundaries.ingest import LocalDataIngestor
from ph_administrative_boundaries.manifest import ManifestError, YamlManifest
from structlog.testing import LogCapture
from structlog.typing import EventDict

MAPSHAPER = "mapshaper -i {in} -clean -o {out}"
TIPPECANOE = "tippecanoe -o {out} -f --layer=country {in}"
DEFAULT_STEPS = [
    {"run": MAPSHAPER},
    {"run": TIPPECANOE, "out": "country.pmtiles"},
]


class FakeRunner:
    def __init__(self) -> None:
        self.versions: dict[str, str] = {}
        self.no_version: set[str] = set()
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, stream: bool = False) -> str:
        if argv[1:] == ["--version"]:
            if argv[0] in self.no_version:
                raise ToolError(f"{argv[0]} has no --version")
            return self.versions.get(argv[0], "1.0")
        self.calls.append(argv)
        destination = Path(argv[argv.index("-o") + 1])
        inputs = [Path(arg) for arg in argv[1:] if Path(arg).is_file()]
        destination.write_text("".join(path.read_text() for path in inputs))
        return ""

    def count(self, tool: str) -> int:
        return sum(1 for call in self.calls if call[0] == tool)


@pytest.fixture()
def runner() -> FakeRunner:
    return FakeRunner()


def write_config(root: Path, datasets: dict) -> None:
    (root / "manifest.yml").write_text(yaml.safe_dump({"datasets": datasets}))


def write_country(root: Path, source: str = "raw/country.json", steps=None) -> None:
    write_config(
        root,
        {
            "country": {
                "source": source,
                "steps": DEFAULT_STEPS if steps is None else steps,
            }
        },
    )


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "country.json").write_text('{"v": 1}')
    write_country(tmp_path)
    return tmp_path


def make_pipeline(root: Path, runner: FakeRunner, keep: bool = False) -> BuildPipeline:
    workspace = root / ".cache" / "build"
    return BuildPipeline(
        manifest=YamlManifest().load(root / "manifest.yml"),
        ingestor=LocalDataIngestor(workspace),
        runner=runner,
        cache=JsonCache(workspace / "cache.json"),
        workspace=workspace,
        output_dir=root / "data" / "processed",
        keep_intermediates=keep,
    )


def test_unchanged_rebuild_runs_no_steps(root: Path, runner: FakeRunner) -> None:
    first = make_pipeline(root, runner).build("country")
    assert len(runner.calls) == 2

    second = make_pipeline(root, runner).build("country")

    assert len(runner.calls) == 2
    assert second[0].sha256 == first[0].sha256


@pytest.mark.parametrize("keep", [False, True])
def test_changed_source_reruns_every_step(
    root: Path, runner: FakeRunner, keep: bool
) -> None:
    make_pipeline(root, runner, keep).build("country")
    (root / "data" / "raw" / "country.json").write_text('{"v": 2}')

    artifacts = make_pipeline(root, runner, keep).build("country")

    assert runner.count("mapshaper") == 2
    assert runner.count("tippecanoe") == 2
    assert artifacts[0].path.read_text() == '{"v": 2}'


def test_edited_last_command_reruns_only_that_step(
    root: Path, runner: FakeRunner
) -> None:
    make_pipeline(root, runner).build("country")
    write_country(
        root,
        steps=[
            {"run": MAPSHAPER},
            {
                "run": "tippecanoe -o {out} -f --layer=country -z13 {in}",
                "out": "country.pmtiles",
            },
        ],
    )

    make_pipeline(root, runner).build("country")

    assert runner.count("mapshaper") == 1
    assert runner.count("tippecanoe") == 2


def test_edited_first_command_reruns_it_and_later_only_if_output_changes(
    root: Path, runner: FakeRunner
) -> None:
    make_pipeline(root, runner).build("country")
    write_country(
        root,
        steps=[
            {"run": MAPSHAPER + " -quiet"},
            {"run": TIPPECANOE, "out": "country.pmtiles"},
        ],
    )

    make_pipeline(root, runner).build("country")

    # The fake copies its input, so the output bytes are unchanged and tippecanoe is cached.
    assert runner.count("mapshaper") == 2
    assert runner.count("tippecanoe") == 1


def test_mapshaper_version_change_reruns_mapshaper_and_later_only_if_output_changes(
    root: Path, runner: FakeRunner
) -> None:
    make_pipeline(root, runner).build("country")
    runner.versions["mapshaper"] = "2.0"

    make_pipeline(root, runner).build("country")

    assert runner.count("mapshaper") == 2
    assert runner.count("tippecanoe") == 1


def test_tippecanoe_version_change_reruns_only_tippecanoe(
    root: Path, runner: FakeRunner
) -> None:
    make_pipeline(root, runner).build("country")
    runner.versions["tippecanoe"] = "2.0"

    make_pipeline(root, runner).build("country")

    assert runner.count("mapshaper") == 1
    assert runner.count("tippecanoe") == 2


def test_final_output_is_written_to_processed(root: Path, runner: FakeRunner) -> None:
    artifacts = make_pipeline(root, runner).build("country")

    assert artifacts[0].path == root / "data" / "processed" / "country.pmtiles"
    assert artifacts[0].path.is_file()


def test_intermediate_is_kept_in_workspace(root: Path, runner: FakeRunner) -> None:
    make_pipeline(root, runner).build("country")

    assert (root / ".cache" / "build" / "steps" / "country" / "step1.geojson").is_file()


def test_glob_merge_is_removed_unless_kept(root: Path, runner: FakeRunner) -> None:
    country = root / "data" / "raw" / "country"
    country.mkdir()
    (country / "a.json").write_text('{"features": []}')
    write_country(root, source="raw/country/*.json")
    merged = root / ".cache" / "build" / "raw" / "country" / "source.geojson"

    make_pipeline(root, runner).build("country")
    assert not merged.exists()

    make_pipeline(root, runner, keep=True).build("country")
    assert merged.is_file()


def test_declared_source_is_never_removed(root: Path, runner: FakeRunner) -> None:
    make_pipeline(root, runner).build("country")

    assert (root / "data" / "raw" / "country.json").is_file()


def test_render_keeps_a_spaced_path_as_one_argument() -> None:
    argv = render(
        "tool -i {in} -o {out}",
        {"in": Path("/a b/in.json"), "out": Path("/c/out.json")},
    )

    assert argv == ["tool", "-i", "/a b/in.json", "-o", "/c/out.json"]


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([{"run": "tool -o {out}", "out": "x.pmtiles"}], "must read {in}"),
        ([{"run": "tool {in}", "out": "x.pmtiles"}], "must use {out}"),
        ([{"run": 'tool "{in} -o {out}', "out": "x.pmtiles"}], "is malformed"),
        ([{"run": MAPSHAPER}], "must set 'out'"),
        ([{"run": TIPPECANOE, "out": "sub/x.pmtiles"}], "plain file name"),
        ([], "non-empty 'steps' list"),
    ],
)
def test_invalid_steps_are_rejected(root: Path, steps: list, message: str) -> None:
    write_country(root, steps=steps)

    with pytest.raises(ManifestError, match=re.escape(message)):
        YamlManifest().load(root / "manifest.yml")


def test_two_datasets_cannot_write_the_same_file(root: Path) -> None:
    write_config(
        root,
        {
            "country": {"source": "raw/country.json", "steps": DEFAULT_STEPS},
            "regions": {"source": "raw/country.json", "steps": DEFAULT_STEPS},
        },
    )

    with pytest.raises(ManifestError, match=re.escape("both write 'country.pmtiles'")):
        YamlManifest().load(root / "manifest.yml")


def test_any_command_works_even_without_a_version_flag(
    root: Path, runner: FakeRunner
) -> None:
    runner.no_version.add("mlt")
    write_country(
        root,
        steps=[
            {"run": MAPSHAPER},
            {"run": "mlt -i {in} -o {out}", "out": "country.mlt"},
        ],
    )

    artifacts = make_pipeline(root, runner).build("country")
    make_pipeline(root, runner).build("country")

    assert artifacts[-1].path.name == "country.mlt"
    assert runner.count("mlt") == 1


BRANCH_SOURCES = {"barangays": "raw/country.json", "roads": "raw/roads.json"}
BRANCHED = [
    {"id": "brgy", "run": "mapshaper -i {barangays} -clean -o {out}"},
    {"id": "brgy_tiles", "run": "tippecanoe -o {out} -f --layer=barangays {brgy}"},
    {"id": "road_tiles", "run": "tippecanoe -o {out} -f --layer=roads {roads}"},
    {
        "run": "tile-join -o {out} -f {brgy_tiles} {road_tiles}",
        "out": "country.pmtiles",
    },
]


@pytest.fixture()
def branched(root: Path) -> Path:
    (root / "data" / "raw" / "roads.json").write_text('{"roads": 1}')
    write_config(root, {"country": {"source": BRANCH_SOURCES, "steps": BRANCHED}})
    return root


def test_branches_merge_into_the_final_output(
    branched: Path, runner: FakeRunner
) -> None:
    artifacts = make_pipeline(branched, runner).build("country")

    assert runner.count("mapshaper") == 1
    assert runner.count("tippecanoe") == 2
    assert runner.count("tile-join") == 1
    assert artifacts[0].path.read_text() == '{"v": 1}{"roads": 1}'


def test_a_change_to_one_branch_leaves_the_other_cached(
    branched: Path, runner: FakeRunner
) -> None:
    make_pipeline(branched, runner).build("country")
    (branched / "data" / "raw" / "roads.json").write_text('{"roads": 2}')

    artifacts = make_pipeline(branched, runner).build("country")

    assert runner.count("mapshaper") == 1
    assert runner.count("tippecanoe") == 3
    assert runner.count("tile-join") == 2
    assert artifacts[0].path.read_text() == '{"v": 1}{"roads": 2}'


@pytest.mark.parametrize(
    ("sources", "steps", "message"),
    [
        (
            {"source": "raw/country.json"},
            [{"run": "tool {nope} -o {out}", "out": "x.pmtiles"}],
            "unknown name '{nope}'",
        ),
        (
            {"source": "raw/country.json"},
            [
                {"id": "first", "run": "tool {second} -o {out}"},
                {"id": "second", "run": "tool {in} -o {out}", "out": "x.pmtiles"},
            ],
            "unknown name '{second}'",
        ),
        (
            BRANCH_SOURCES,
            [{"run": "tool {in} -o {out}", "out": "x.pmtiles"}],
            "several sources",
        ),
        (
            {"source": "raw/country.json"},
            [
                {"id": "a", "run": "tool {in} -o {out}"},
                {"id": "a", "run": "tool {in} -o {out}", "out": "x.pmtiles"},
            ],
            "used twice",
        ),
        (
            BRANCH_SOURCES,
            [
                {"id": "roads", "run": "tool {barangays} -o {out}"},
                {"run": "tool {roads} -o {out}", "out": "x.pmtiles"},
            ],
            "plain identifier",
        ),
        (
            {"source": "raw/country.json"},
            [{"run": "tool -o {out}", "out": "x.pmtiles"}],
            "must read {in}",
        ),
    ],
)
def test_invalid_references_are_rejected(
    root: Path, sources: dict, steps: list, message: str
) -> None:
    write_config(root, {"country": {"source": sources, "steps": steps}})

    with pytest.raises(ManifestError, match=re.escape(message)):
        YamlManifest().load(root / "manifest.yml")


@pytest.fixture()
def logs() -> list[EventDict]:
    capture = LogCapture()
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, capture])
    return capture.entries


def test_logs_each_step_and_cache_hits(
    root: Path, runner: FakeRunner, logs: list[EventDict]
) -> None:
    write_country(root)
    make_pipeline(root, runner).build("country")
    logs.clear()

    make_pipeline(root, runner).build("country")

    cached = [e for e in logs if e["event"] == "step_cached"]
    assert [e["step"] for e in cached] == [1, 2]
    assert all(e["dataset"] == "country" for e in cached)


def test_logs_command_for_steps_that_run(
    root: Path, runner: FakeRunner, logs: list[EventDict]
) -> None:
    write_country(root)

    make_pipeline(root, runner).build("country")

    started = [e for e in logs if e["event"] == "step_started"]
    assert [(e["step"], e["tool"]) for e in started] == [
        (1, "mapshaper"),
        (2, "tippecanoe"),
    ]
    assert started[0]["command"].startswith("mapshaper ")
    assert [e["event"] for e in logs][-1] == "build_finished"
