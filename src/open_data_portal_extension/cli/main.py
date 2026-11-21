"""Command-line interface: ``open-data-portal-extension --help``."""

from __future__ import annotations

import json
import os
import tomllib
from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from .. import evaluation
from ..catalog import export_catalog
from ..dataset import ColumnDetector
from ..manifest import DEFAULT_MANIFEST, DatasetConfig, Manifest, load_manifest
from ..models.psgc import GeoLevel, PsgcSnapshot
from ..reference import ReferenceStore
from ..reference_build import SourceError, build
from ..tabular import COLUMN_CHOICES, TableResult, tag_table
from ..tagging import TaggingPipeline

DEFAULT_DB = Path("data/psgc-v1.0.1.duckdb")

app = typer.Typer(
    help="Tag Philippine datasets with PSGC codes.",
    no_args_is_help=True,
    add_completion=False,
)

DbOption = Annotated[
    Path | None,
    typer.Option(
        "--db",
        help=f"Reference database. Defaults to $PSGC_REFERENCE_DB, then {DEFAULT_DB}.",
        show_default=False,
    ),
]

ManifestOption = Annotated[
    Path, typer.Option("--manifest", help="Manifest listing the datasets.")
]


def _open_store(db: Path | None) -> ReferenceStore:
    path = db or Path(os.environ.get("PSGC_REFERENCE_DB", DEFAULT_DB))
    if not path.exists():
        typer.echo(
            f"No reference database at {path}. Run `just build-reference` first.",
            err=True,
        )
        raise typer.Exit(1)
    return ReferenceStore.open(path)


@app.command("build-reference")
def build_reference(
    source_dir: Annotated[
        Path, typer.Argument(help="Folder with the four PH_Adm*.csv files.")
    ],
    out_path: Annotated[Path, typer.Argument(help="Reference database to write.")],
    version: Annotated[
        str, typer.Option(help="Release tag the CSVs came from, e.g. v1.0.1.")
    ],
    released_on: Annotated[
        str,
        typer.Option(help="Date of the PSGC update the release matches, YYYY-MM-DD."),
    ],
    changes: Annotated[
        Path | None,
        typer.Option(
            help="PSA's Summary of Changes workbook (.xlsx), for old names, "
            "codes, and parents."
        ),
    ] = None,
    boundaries: Annotated[
        Path | None,
        typer.Option(
            help="Barangay boundaries as GeoParquet (PH_Adm4_BgySubMuns.parquet "
            "built in boundaries/), for tagging coordinates."
        ),
    ] = None,
) -> None:
    """Build a reference database from one release's PSGC CSVs."""
    try:
        snapshot = PsgcSnapshot(
            version=version, released_on=date.fromisoformat(released_on)
        )
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--released-on") from error
    try:
        report = build(
            source_dir,
            out_path,
            snapshot,
            changes_path=changes,
            boundaries_path=boundaries,
        )
    except SourceError as error:
        typer.echo(f"Build failed: {error}", err=True)
        raise typer.Exit(1) from error
    for level in GeoLevel:
        typer.echo(f"{level.value:>18}  {report.counts.get(level, 0):>6}")
    typer.echo(
        f"{'aliases':>18}  {report.aliases:>6}\n"
        f"{'crosswalk':>18}  {report.crosswalk:>6}\n"
        f"{'former parents':>18}  {report.former_parents:>6}\n"
        f"{'boundaries':>18}  {report.boundaries:>6}"
    )
    typer.echo(f"Wrote {report.total} entries ({version}) to {out_path}")


@app.command()
def resolve(
    text: Annotated[
        str, typer.Argument(help='A place, e.g. "Saysain, Bagac, Bataan".')
    ],
    limit: Annotated[int, typer.Option(min=1, help="How many candidates to list.")] = 5,
    db: DbOption = None,
) -> None:
    """Tag one place string and show the candidates."""
    store = _open_store(db)
    try:
        row = {"Location": text}
        profile = ColumnDetector().profile([row], dataset_key="cli")
        tag = TaggingPipeline(store).tag_row(profile, row, row_id="1")
        if tag is None:
            typer.echo("No place name found in that text.", err=True)
            raise typer.Exit(1)

        typer.echo(f"{tag.status.value}  confidence {tag.confidence:.3f}")
        for candidate in tag.candidates[:limit]:
            entry = store.get(candidate.code)
            name = entry.name if entry else "?"
            marker = "*" if candidate.code == tag.code else " "
            typer.echo(
                f" {marker} {candidate.code}  {candidate.score:.3f}  "
                f"{candidate.level.value:<17}  {name}"
            )
        hidden = len(tag.candidates) - limit
        if hidden > 0:
            typer.echo(
                f"   ... and {hidden} more (show them with --limit {len(tag.candidates)})"
            )
        if not tag.candidates:
            typer.echo("   no candidates")
    finally:
        store.close()


@app.command()
def tag(
    source: Annotated[
        str,
        typer.Argument(
            help="Dataset to tag: a .csv, .tsv, .json, .jsonl or .parquet file, "
            "or an https URL to one."
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write the tagged table here (.csv, .parquet or .jsonl). "
            "Without it, only the report is shown.",
        ),
    ] = None,
    column: Annotated[
        list[str] | None,
        typer.Option(
            "--column",
            metavar="NAME=SETTING",
            help="Override detection for one column. SETTING is a PSGC level, "
            "free_text, or ignore. Repeatable.",
        ),
    ] = None,
    failures: Annotated[
        int, typer.Option(min=0, help="How many places sent to review to list.")
    ] = 10,
    db: DbOption = None,
) -> None:
    """Tag every row of a dataset with a PSGC code and report what resolved."""
    overrides = dict(_parse_override(value) for value in column or [])
    store = _open_store(db)
    try:
        result = _tag_or_exit(source, store, overrides=overrides, output=output)
        _report(result, store, failures=failures)
    finally:
        store.close()
    if output:
        typer.echo(f"Wrote {output}", err=True)


@app.command()
def run(
    names: Annotated[
        list[str] | None,
        typer.Argument(help="Datasets to tag. Defaults to every one in the manifest."),
    ] = None,
    manifest: ManifestOption = DEFAULT_MANIFEST,
    failures: Annotated[
        int, typer.Option(min=0, help="How many places sent to review to list.")
    ] = 5,
    db: DbOption = None,
) -> None:
    """Tag the datasets listed in manifest.toml and write each tagged copy."""
    config = _load_manifest_or_exit(manifest)
    datasets = _select_or_exit(config, names)
    store = _open_store(db or config.reference.db)
    try:
        for dataset in datasets:
            typer.echo(f"\n== {dataset.name}", err=True)
            result = _tag_or_exit(
                dataset.source,
                store,
                dataset_key=dataset.name,
                overrides=dataset.columns,
                output=dataset.output,
            )
            _report(result, store, failures=failures, expected=dataset.level)
            typer.echo(f"Wrote {dataset.output}", err=True)
    finally:
        store.close()


@app.command()
def export(
    names: Annotated[
        list[str] | None,
        typer.Argument(
            help="Datasets to export. Defaults to every one in the manifest."
        ),
    ] = None,
    manifest: ManifestOption = DEFAULT_MANIFEST,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Catalog to write (default: data/output/catalog.sqlite by the manifest).",
            show_default=False,
        ),
    ] = None,
    db: DbOption = None,
) -> None:
    """Write the tagged datasets, rolled up by place, to a catalog for the viewer."""
    config = _load_manifest_or_exit(manifest)
    datasets = _select_or_exit(config, names)
    reference = (
        db
        or config.reference.db
        or Path(os.environ.get("PSGC_REFERENCE_DB", DEFAULT_DB))
    )
    if not reference.exists():
        typer.echo(
            f"No reference database at {reference}. Run `just build-reference` first.",
            err=True,
        )
        raise typer.Exit(1)
    out = output or manifest.resolve().parent / "data/output/catalog.sqlite"

    summary = export_catalog(datasets, reference, out)
    for name, rows in summary.datasets.items():
        typer.echo(f"{name}: {rows} tagged rows", err=True)
    for name, rows in summary.unknown_codes.items():
        typer.echo(
            f"Warning: {name}: {rows} rows have codes not in the reference; skipped",
            err=True,
        )
    if summary.missing:
        typer.echo(
            f"Skipped, not tagged yet: {', '.join(summary.missing)} (run `just run`)",
            err=True,
        )
    if not summary.datasets:
        typer.echo("Nothing to export.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Wrote {summary.out}", err=True)


@app.command("eval")
def evaluate(
    names: Annotated[
        list[str] | None,
        typer.Argument(
            help="Datasets to evaluate. Defaults to those with eval = true."
        ),
    ] = None,
    manifest: ManifestOption = DEFAULT_MANIFEST,
    save: Annotated[
        bool,
        typer.Option(help="Save the new numbers as the baselines (after review)."),
    ] = False,
    sample: Annotated[
        int,
        typer.Option(
            min=0,
            help="Add this many unlabeled places to each labels file, to check by hand.",
        ),
    ] = 0,
    failures: Annotated[
        int, typer.Option(min=0, help="How many places sent to review to list.")
    ] = 0,
    db: DbOption = None,
) -> None:
    """Tag evaluation datasets, score them against labels, and compare with the
    saved baselines."""
    config = _load_manifest_or_exit(manifest)
    datasets = (
        _select_or_exit(config, names)
        if names
        else [dataset for dataset in config.datasets if dataset.eval]
    )
    if not datasets:
        typer.echo("No datasets have eval = true in the manifest.", err=True)
        raise typer.Exit(1)

    store = _open_store(db or config.reference.db)
    try:
        version = store.snapshot().version
        for dataset in datasets:
            typer.echo(f"\n== {dataset.name}")
            result = _tag_or_exit(
                dataset.source,
                store,
                dataset_key=dataset.name,
                overrides=dataset.columns,
            )
            labels = config.eval.labels / f"{dataset.name}.csv"
            summary = result.summary(version)
            scored = evaluation.score(result.places, labels)
            if scored is not None:
                summary["labels"] = scored.summary()
            baseline = config.eval.baselines / f"{dataset.name}.json"
            previous = json.loads(baseline.read_text()) if baseline.exists() else None
            _compare(summary, previous)
            if scored is not None:
                _list_wrong(scored)
            _warn_level(result, dataset.level)
            _list_failures(result, failures)
            if sample:
                added = evaluation.sample(
                    result.places, labels, store, size=sample, seed=dataset.name
                )
                typer.echo(
                    f"Added {added} places to {labels}: correct expected_code "
                    "where needed, then fill in checked."
                )
            if save:
                baseline.parent.mkdir(parents=True, exist_ok=True)
                baseline.write_text(json.dumps(summary, indent=2) + "\n")
        if not save:
            typer.echo("\nBaselines unchanged. Rerun with --save to accept these.")
    finally:
        store.close()


def _list_wrong(scored: evaluation.Score, limit: int = 10) -> None:
    if scored.unmatched:
        typer.echo(
            f"Warning: {scored.unmatched} checked labels match no place; "
            "were the place columns detected differently?",
            err=True,
        )
    for values, expected, tagged in scored.wrong[:limit]:
        place = " | ".join(values.values())
        typer.echo(f"  wrong  {place}  expected {expected or 'none'}, got {tagged}")


def _tag_or_exit(source, store, **options) -> TableResult:
    try:
        return tag_table(source, store, **options)
    except (ValueError, duckdb.Error) as error:
        typer.echo(f"Could not tag {source}: {error}", err=True)
        raise typer.Exit(1) from error


def _report(
    result: TableResult,
    store: ReferenceStore,
    *,
    failures: int,
    expected: GeoLevel | None = None,
) -> None:
    detected = ", ".join(
        f"{m.column} ({m.level.value if m.level else 'free text'})"
        for m in result.profile.mappings
    )
    typer.echo(f"Place columns: {detected or 'none found'}", err=True)
    counts = ", ".join(
        f"{n} {status}" for status, n in sorted(result.rows_by_status.items())
    )
    typer.echo(
        f"Tagged {result.rows} rows ({result.distinct_places} distinct places): "
        f"{counts or 'nothing to tag'}",
        err=True,
    )
    if result.rows:
        levels = ", ".join(
            f"{n} {level}" for level, n in result.auto_rows_by_level.most_common()
        )
        typer.echo(
            f"Auto-tagged {result.auto_rate:.1%}"
            + (f", by level: {levels}" if levels else ""),
            err=True,
        )
    if result.coordinates:
        located = ", ".join(f"{n} {k}" for k, n in sorted(result.points.items()))
        typer.echo(
            f"Coordinates from {result.coordinates}"
            + (f": distinct points {located}" if located else ""),
            err=True,
        )
    for note in result.notes:
        typer.echo(f"Note: {note}", err=True)
    _warn_level(result, expected)
    _list_failures(result, failures)


def _compare(summary: dict, previous: dict | None) -> None:
    for label, key in [
        ("Detected columns", "detected"),
        ("Rows", "rows"),
        ("Distinct places", "distinct_places"),
        ("Auto-tag rate", "auto_rate"),
        ("Rows by status", "rows_by_status"),
        ("Auto rows by level", "auto_rows_by_level"),
        ("Points", "points"),
        ("Labels", "labels"),
    ]:
        if key not in summary and not (previous and key in previous):
            continue
        now = summary.get(key)
        before = previous.get(key) if previous else None
        changed = f"   (was {before})" if previous and before != now else ""
        typer.echo(f"{label:<20} {now}{changed}")


def _warn_level(result: TableResult, expected: GeoLevel | None) -> None:
    found = result.reported_level
    order = list(GeoLevel)
    if expected is not None and (
        found is None or order.index(found) < order.index(expected)
    ):
        typer.echo(
            f"Warning: expected {expected.value} but the finest level found "
            f"is {found.value if found else 'none'}. A column may need an override.",
            err=True,
        )


def _list_failures(result: TableResult, limit: int) -> None:
    if not limit or not result.failures:
        return
    typer.echo("Top places sent to review, by rows affected:", err=True)
    for failure in result.failures[:limit]:
        place = " | ".join(str(value) for value in failure.values.values())
        typer.echo(
            f"  {failure.rows:>7}  {place}  "
            f"(confidence {failure.confidence:.2f}, {failure.candidates} candidates)",
            err=True,
        )


def _parse_override(value: str) -> tuple[str, str]:
    name, _, setting = value.rpartition("=")
    if not name or setting not in COLUMN_CHOICES:
        raise typer.BadParameter(
            f"expected NAME=SETTING with SETTING one of {', '.join(COLUMN_CHOICES)}",
            param_hint="--column",
        )
    return name, setting


def _load_manifest_or_exit(path: Path) -> Manifest:
    if not path.exists():
        typer.echo(f"No manifest at {path}.", err=True)
        raise typer.Exit(1)
    try:
        return load_manifest(path)
    except (ValueError, tomllib.TOMLDecodeError) as error:
        typer.echo(f"Invalid manifest {path}:\n{error}", err=True)
        raise typer.Exit(1) from error


def _select_or_exit(config: Manifest, names: list[str] | None) -> list[DatasetConfig]:
    try:
        return config.select(names)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
