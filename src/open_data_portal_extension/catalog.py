"""Export the manifest's tagged datasets to one SQLite file for the web viewer.

The viewer only reads; every PSGC rule stays here. Each tagged row counts at
its own place and at every place above it, following ``parent_code``, so a
highly urbanized city rolls up into the province it sits in (City of Baguio
into Benguet) even though its code doesn't contain the province's.

Tables:

- ``datasets``: one row per exported dataset, with its manifest metadata and
  status counts.
- ``places``: current PSGC entries.
- ``lineage``: each place's barangay, city or municipality, province, and
  region; a place's own level points at itself.
- ``place_counts``: tagged rows per dataset and place, at every level.
- ``rows``: each tagged row, its source columns as a JSON object.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .manifest import DatasetConfig
from .tabular import OUTPUT_COLUMNS

LEVELS = ("barangay", "city_municipality", "province", "region")

SCHEMA = """
CREATE TABLE datasets (
    name TEXT PRIMARY KEY,
    description TEXT,
    attribution TEXT,
    license TEXT,
    url TEXT,
    rows INTEGER NOT NULL,
    auto INTEGER NOT NULL,
    needs_review INTEGER NOT NULL,
    no_place INTEGER NOT NULL
);
CREATE TABLE places (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level TEXT NOT NULL,
    parent_code TEXT
);
CREATE TABLE lineage (
    code TEXT PRIMARY KEY,
    barangay TEXT,
    city_municipality TEXT,
    province TEXT,
    region TEXT
);
CREATE TABLE place_counts (
    dataset TEXT NOT NULL,
    code TEXT NOT NULL,
    level TEXT NOT NULL,
    rows INTEGER NOT NULL,
    PRIMARY KEY (dataset, code)
);
CREATE TABLE rows (
    dataset TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    confidence REAL,
    data TEXT NOT NULL,
    PRIMARY KEY (dataset, row_id)
);
CREATE INDEX place_counts_by_level ON place_counts (level, dataset);
CREATE INDEX place_counts_by_code ON place_counts (code);
CREATE INDEX rows_by_code ON rows (code, dataset);
CREATE INDEX lineage_by_city ON lineage (city_municipality);
CREATE INDEX lineage_by_province ON lineage (province);
CREATE INDEX lineage_by_region ON lineage (region);
"""


@dataclass
class ExportSummary:
    out: Path
    datasets: dict[str, int] = field(default_factory=dict)
    """Tagged rows exported, by dataset."""
    missing: list[str] = field(default_factory=list)
    """Datasets skipped because their tagged output doesn't exist yet."""
    unknown_codes: dict[str, int] = field(default_factory=dict)
    """Rows whose code isn't a current PSGC entry, by dataset: not exported."""


def export_catalog(
    datasets: list[DatasetConfig], reference_db: Path, out: Path
) -> ExportSummary:
    """Write ``out`` from each dataset's tagged output, replacing it atomically."""
    summary = ExportSummary(out=out)
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH {_literal(str(reference_db))} AS ref (READ_ONLY)")
        _load_places(con)

        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_name(out.name + ".partial")
        partial.unlink(missing_ok=True)
        sqlite = sqlite3.connect(partial)
        try:
            sqlite.executescript(SCHEMA)
            _copy(
                con,
                sqlite,
                "places",
                "SELECT code, name, level, parent_code FROM places",
            )
            _copy(
                con,
                sqlite,
                "lineage",
                "SELECT code, barangay, city_municipality, province, region FROM lineage",
            )
            for dataset in datasets:
                assert dataset.output is not None  # load_manifest fills it in
                if not dataset.output.exists():
                    summary.missing.append(dataset.name)
                    continue
                _export_dataset(con, sqlite, dataset, summary)
            sqlite.commit()
        finally:
            sqlite.close()
        os.replace(partial, out)
    finally:
        con.close()
    return summary


def _load_places(con) -> None:
    columns = {
        name
        for (name,) in con.execute(
            "SELECT column_name FROM duckdb_columns() "
            "WHERE database_name = 'ref' AND table_name = 'psgc_entries'"
        ).fetchall()
    }
    current = "WHERE valid_to IS NULL" if "valid_to" in columns else ""
    con.execute(
        "CREATE TEMP TABLE places AS SELECT code, name, level, parent_code "
        f"FROM ref.psgc_entries {current}"
    )
    picks = ",\n".join(
        f"max(ancestor) FILTER (WHERE ancestor_level = '{level}') AS {level}"
        for level in LEVELS
    )
    con.execute(
        f"""
        CREATE TEMP TABLE lineage AS
        WITH RECURSIVE up(code, ancestor, ancestor_level) AS (
            SELECT code, code, level FROM places
            UNION ALL
            SELECT up.code, parent.code, parent.level
            FROM up
            JOIN places AS child ON child.code = up.ancestor
            JOIN places AS parent ON parent.code = child.parent_code
        )
        SELECT code, {picks} FROM up GROUP BY code
        """
    )


def _export_dataset(
    con, sqlite, dataset: DatasetConfig, summary: ExportSummary
) -> None:
    name = dataset.name
    con.execute(
        "CREATE OR REPLACE TEMP TABLE t AS "
        f"SELECT row_number() OVER () - 1 AS row_id, * FROM {_reader(dataset.output)}"
    )
    source_columns = [
        column
        for (column,) in con.execute(
            "SELECT column_name FROM duckdb_columns() "
            "WHERE database_name = 'temp' AND table_name = 't' "
            "ORDER BY column_index"
        ).fetchall()
        if column != "row_id" and column not in OUTPUT_COLUMNS
    ]

    total, auto, review, no_place = con.execute(
        "SELECT count(*), "
        "count(*) FILTER (WHERE psgc_status = 'auto'), "
        "count(*) FILTER (WHERE psgc_status = 'needs_review'), "
        "count(*) FILTER (WHERE psgc_status = 'no_place') FROM t"
    ).fetchone()
    sqlite.execute(
        "INSERT INTO datasets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            dataset.description,
            dataset.attribution,
            dataset.license,
            dataset.url,
            total,
            auto,
            review,
            no_place,
        ),
    )

    unknown = con.execute(
        "SELECT count(*) FROM t WHERE psgc_code IS NOT NULL "
        "AND psgc_code NOT IN (SELECT code FROM lineage)"
    ).fetchone()[0]
    if unknown:
        summary.unknown_codes[name] = unknown

    levels = ", ".join(f"(l.{level}, '{level}')" for level in LEVELS)
    _copy(
        con,
        sqlite,
        "place_counts",
        f"""
        SELECT ?, a.code, a.level, count(*)
        FROM t JOIN lineage AS l ON l.code = t.psgc_code,
        LATERAL (VALUES {levels}) AS a(code, level)
        WHERE a.code IS NOT NULL
        GROUP BY a.code, a.level
        """,
        [name],
    )

    data = (
        "struct_pack("
        + ", ".join(
            f"{_quote(column)} := {_quote(column)}" for column in source_columns
        )
        + ")"
    )
    summary.datasets[name] = _copy(
        con,
        sqlite,
        "rows",
        f"""
        SELECT ?, row_id, psgc_code, TRY_CAST(psgc_confidence AS DOUBLE),
            to_json({data})::VARCHAR
        FROM t WHERE psgc_code IN (SELECT code FROM lineage)
        ORDER BY row_id
        """,
        [name],
    )


def _copy(con, sqlite, table: str, query: str, params=None, batch: int = 10_000) -> int:
    cursor = con.execute(query, params or [])
    width = len(cursor.description)
    insert = f"INSERT INTO {table} VALUES ({', '.join(['?'] * width)})"
    copied = 0
    while chunk := cursor.fetchmany(batch):
        sqlite.executemany(insert, chunk)
        copied += len(chunk)
    return copied


def _reader(path: Path) -> str:
    source = _literal(str(path))
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        # Text throughout: codes keep their leading zeros.
        return f"read_csv({source}, header = true, all_varchar = true)"
    if suffix == ".parquet":
        return f"read_parquet({source})"
    if suffix in (".jsonl", ".ndjson", ".json"):
        return f"read_json({source}, format = 'newline_delimited')"
    raise ValueError(f"unsupported output format: {path}")


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
