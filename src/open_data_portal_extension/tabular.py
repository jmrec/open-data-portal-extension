"""Tag a whole table in DuckDB, resolving each distinct place once.

Datasets repeat places (86,234 election records name 1,760), so only distinct
combinations of place columns go through ``TaggingPipeline``; the codes are
joined back in row order.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .dataset import ColumnDetector, is_code_column
from .models.dataset import ColumnMapping, DatasetProfile
from .models.psgc import GeoLevel
from .reference import ReferenceStore
from .tagging import TaggingPipeline

OUTPUT_COLUMNS = ("psgc_code", "psgc_level", "psgc_status", "psgc_confidence")
COLUMN_CHOICES = tuple(level.value for level in GeoLevel) + (
    "free_text",
    "latitude",
    "longitude",
    "ignore",
)

_ROW = "__psgc_row"
_LAT, _LON = "__psgc_lat", "__psgc_lon"
_SAMPLE = 200
_COORDINATE_KINDS = ("latitude", "longitude")


@dataclass
class Place:
    """One distinct combination of place values, and how it was tagged."""

    values: dict[str, object]
    """The key columns, with points as ``latitude`` and ``longitude``."""

    rows: int
    status: str
    code: str | None = None
    level: str | None = None
    confidence: float = 0.0
    candidates: int = 0
    best_code: str | None = None
    """The top candidate, even when it was not accepted."""


@dataclass
class TableResult:
    profile: DatasetProfile
    rows: int = 0
    distinct_places: int = 0
    rows_by_status: Counter[str] = field(default_factory=Counter)
    places_by_status: Counter[str] = field(default_factory=Counter)
    auto_rows_by_level: Counter[str] = field(default_factory=Counter)
    places: list[Place] = field(default_factory=list)

    coordinates: str | None = None

    points: Counter[str] = field(default_factory=Counter)
    """Distinct points: inside, nearby, or not_found."""

    notes: list[str] = field(default_factory=list)

    @property
    def reported_level(self) -> GeoLevel | None:
        level = self.profile.reported_level
        if level is None and any(self.points[k] for k in ("inside", "nearby")):
            return GeoLevel.BARANGAY
        return level

    @property
    def failures(self) -> list[Place]:
        """Places sent to review, most rows first."""
        review = [p for p in self.places if p.status == "needs_review"]
        return sorted(review, key=lambda place: -place.rows)

    @property
    def auto_rate(self) -> float:
        return self.rows_by_status["auto"] / self.rows if self.rows else 0.0

    def summary(self, psgc_version: str) -> dict:
        """The shape eval baselines are saved in."""
        return {
            "dataset": self.profile.dataset_key,
            "psgc_version": psgc_version,
            "detected": {
                m.column: (m.level.value if m.level else m.kind)
                for m in self.profile.mappings
            },
            "rows": self.rows,
            "distinct_places": self.distinct_places,
            "rows_by_status": dict(self.rows_by_status),
            "places_by_status": dict(self.places_by_status),
            "auto_rate": round(self.auto_rate, 4),
            "auto_rows_by_level": dict(self.auto_rows_by_level),
            **({"points": dict(self.points)} if self.coordinates else {}),
        }


def tag_table(
    source: str | Path,
    reference: ReferenceStore,
    *,
    dataset_key: str | None = None,
    overrides: dict[str, str] | None = None,
    output: Path | None = None,
) -> TableResult:
    """Tag ``source`` (a file or https URL), writing the result to ``output``.

    ``overrides`` maps columns to a ``COLUMN_CHOICES`` setting.
    """
    source = str(source)
    connection = duckdb.connect()
    try:
        connection.execute(
            f"CREATE TEMP TABLE src AS SELECT row_number() OVER () AS {_ROW}, * "
            f"FROM {_reader(source)}"
        )
        columns = [
            name
            for name, *_ in connection.execute("DESCRIBE src").fetchall()
            if name != _ROW
        ]
        sample = _fetch_dicts(
            connection, f"SELECT * EXCLUDE ({_ROW}) FROM src LIMIT {_SAMPLE}"
        )
        profile = ColumnDetector().profile(
            sample or [dict.fromkeys(columns)],
            dataset_key=dataset_key or _stem(source),
        )
        if overrides:
            profile = apply_overrides(profile, overrides)

        result = TableResult(profile=profile)
        used = _add_coordinates(connection, columns, profile, result)
        # Resolution reads the parsed points, not the source columns.
        mappings = [m for m in profile.mappings if m.kind not in _COORDINATE_KINDS]
        if used:
            mappings += [
                ColumnMapping(column=column, kind=kind, confidence=1.0, source="manual")
                for column, kind in zip((_LAT, _LON), _COORDINATE_KINDS)
            ]
        resolving = profile.model_copy(update={"mappings": mappings})
        retagging = "psgc_status" in columns
        keys = _key_columns(resolving, columns, retagging=retagging, skipped=used)
        _resolve(connection, reference, resolving, keys, result)
        if output is not None:
            _write(connection, columns, keys, output, retagging=retagging)
        return result
    finally:
        connection.close()


def apply_overrides(
    profile: DatasetProfile, overrides: dict[str, str]
) -> DatasetProfile:
    """Replace detection for the columns in ``overrides`` (``COLUMN_CHOICES``)."""
    unknown = sorted(set(overrides) - set(profile.columns))
    if unknown:
        raise ValueError(f"no such column: {', '.join(unknown)}")
    bad = sorted(value for value in overrides.values() if value not in COLUMN_CHOICES)
    if bad:
        raise ValueError(
            f"unknown column setting {', '.join(bad)}; "
            f"use one of {', '.join(COLUMN_CHOICES)}"
        )
    coordinates = [v for v in overrides.values() if v in _COORDINATE_KINDS]
    if coordinates and sorted(coordinates) != sorted(_COORDINATE_KINDS):
        raise ValueError("set both a latitude and a longitude column, or neither")

    mappings = [
        m
        for m in profile.mappings
        if m.column not in overrides
        and not (coordinates and m.kind in _COORDINATE_KINDS)
    ]
    for column, setting in overrides.items():
        if setting == "ignore":
            continue
        place = setting not in ("free_text", *_COORDINATE_KINDS)
        mappings.append(
            ColumnMapping(
                column=column,
                kind="place" if place else setting,
                level=GeoLevel(setting) if place else None,
                confidence=1.0,
                source="manual",
            )
        )
    return profile.model_copy(update={"mappings": mappings})


def _resolve(connection, reference, profile, keys, result: TableResult) -> None:
    result.rows = connection.execute("SELECT count(*) FROM src").fetchone()[0]
    if not keys:
        result.rows_by_status["no_place"] = result.rows
        return

    quoted = ", ".join(_quote(key) for key in keys)
    grouped = connection.execute(
        f"SELECT {quoted}, count(*) FROM src GROUP BY ALL"
    ).fetchall()

    # Neutral names: a key may itself be called psgc_code.
    renamed = ", ".join(f"{_quote(key)} AS k{i}" for i, key in enumerate(keys))
    connection.execute(
        f"CREATE TEMP TABLE psgc_tags AS SELECT {renamed} FROM src LIMIT 0"
    )
    connection.execute(
        "ALTER TABLE psgc_tags ADD COLUMN psgc_code VARCHAR;"
        "ALTER TABLE psgc_tags ADD COLUMN psgc_level VARCHAR;"
        "ALTER TABLE psgc_tags ADD COLUMN psgc_status VARCHAR;"
        "ALTER TABLE psgc_tags ADD COLUMN psgc_confidence DOUBLE;"
    )

    located = _locate(connection, reference, result) if _LAT in keys else None
    pipeline = TaggingPipeline(reference, located=located)
    tagged = []
    for *values, weight in grouped:
        place = dict(zip(keys, values))
        tag = pipeline.tag_row(profile, place, row_id="")
        status = tag.status.value if tag else "no_place"
        if tag is not None:
            result.distinct_places += 1
        result.places_by_status[status] += 1
        result.rows_by_status[status] += weight
        if tag is not None and tag.code is not None and tag.level is not None:
            result.auto_rows_by_level[tag.level.value] += weight
        level = tag.level.value if tag and tag.level else None
        result.places.append(
            Place(
                values=_as_row(place),
                rows=weight,
                status=status,
                code=tag.code if tag else None,
                level=level,
                confidence=tag.confidence if tag else 0.0,
                candidates=len(tag.candidates) if tag else 0,
                best_code=tag.candidates[0].code if tag and tag.candidates else None,
            )
        )
        tagged.append(
            (
                *values,
                tag.code if tag else None,
                level,
                status,
                round(tag.confidence, 3) if tag else None,
            )
        )

    placeholders = ", ".join(["?"] * (len(keys) + len(OUTPUT_COLUMNS)))
    connection.executemany(f"INSERT INTO psgc_tags VALUES ({placeholders})", tagged)


def _add_coordinates(
    connection, columns: list[str], profile: DatasetProfile, result: TableResult
) -> list[str]:
    """Add ``__psgc_lat``/``__psgc_lon`` to ``src``; return the columns used.

    Uses the profile's latitude and longitude columns, else a geometry column.
    """
    types = {
        name: kind for name, kind, *_ in connection.execute("DESCRIBE src").fetchall()
    }
    lat, lon = profile.coordinates or (None, None)
    if lat and lon:
        lat_sql, lon_sql = (f"TRY_CAST({_quote(c)} AS DOUBLE)" for c in (lat, lon))
        result.coordinates, used = f"{lat}, {lon}", [lat, lon]
    else:
        geometry = next(
            (c for c in columns if types[c] == "GEOMETRY" or _is_geojson(types[c])),
            None,
        )
        if geometry is None:
            return []
        column = _quote(geometry)
        if types[geometry] == "GEOMETRY":
            connection.execute("INSTALL spatial; LOAD spatial")
            surface = f"ST_PointOnSurface({column})"
            lat_sql, lon_sql = f"ST_Y({surface})", f"ST_X({surface})"
        else:  # GeoJSON as plain JSON: [longitude, latitude]
            point = f"{column}.type = 'Point'"
            lat_sql = f"CASE WHEN {point} THEN {column}.coordinates[2] END"
            lon_sql = f"CASE WHEN {point} THEN {column}.coordinates[1] END"
        result.coordinates, used = geometry, [geometry]

    connection.execute(
        f"ALTER TABLE src ADD COLUMN {_LAT} DOUBLE; "
        f"ALTER TABLE src ADD COLUMN {_LON} DOUBLE; "
        f"UPDATE src SET {_LAT} = {lat_sql}, {_LON} = {lon_sql}"
    )
    return used


def _is_geojson(kind: str) -> bool:
    return kind.startswith("STRUCT(") and "coordinates" in kind and '"type"' in kind


def _locate(connection, reference: ReferenceStore, result: TableResult):
    points = connection.execute(
        f"SELECT DISTINCT {_LAT}, {_LON} FROM src "
        f"WHERE {_LAT} IS NOT NULL AND {_LON} IS NOT NULL"
    ).fetchall()
    if not reference.has_boundaries():
        result.notes.append(
            "Coordinates were found, but the reference has no boundaries, so they "
            "were not used. Build PH_Adm4_BgySubMuns.parquet in "
            "ph-administrative-boundaries, then run `just build-reference`."
        )
        return None
    located = reference.locate(points)
    for point in points:
        found = located.get(point)
        if found is None:
            outcome = "not_found"
        elif found.outside_m > 0:
            outcome = "nearby"
        else:
            outcome = "inside"
        result.points[outcome] += 1
    return located


def _as_row(place: dict[str, object]) -> dict[str, object]:
    row = {key: value for key, value in place.items() if key not in (_LAT, _LON)}
    if _LAT in place:
        row["latitude"], row["longitude"] = place[_LAT], place[_LON]
    return row


def _write(
    connection, columns: list[str], keys: list[str], output: Path, *, retagging: bool
) -> None:
    replaced = OUTPUT_COLUMNS if retagging else ("psgc_code",)
    kept = [column for column in columns if column not in replaced]
    selected = ", ".join(f"src.{_quote(column)}" for column in kept)
    if keys:
        joined = " AND ".join(
            f"src.{_quote(key)} IS NOT DISTINCT FROM t.k{i}"
            for i, key in enumerate(keys)
        )
        query = (
            f"SELECT {selected}, t.psgc_code, t.psgc_level, "
            f"coalesce(t.psgc_status, 'no_place') AS psgc_status, t.psgc_confidence "
            f"FROM src LEFT JOIN psgc_tags AS t ON {joined} ORDER BY src.{_ROW}"
        )
    else:
        query = (
            f"SELECT {selected}, NULL::VARCHAR AS psgc_code, "
            f"NULL::VARCHAR AS psgc_level, 'no_place' AS psgc_status, "
            f"NULL::DOUBLE AS psgc_confidence FROM src ORDER BY {_ROW}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"COPY ({query}) TO {_literal(str(output))} ({_output_format(output)})"
    )


def _key_columns(
    profile: DatasetProfile,
    columns: list[str],
    *,
    retagging: bool,
    skipped: list[str],
) -> list[str]:
    """The columns that identify a place: names, codes, then parsed points."""
    keys = [m.column for m in profile.mappings if m.kind in ("place", "free_text")]
    ignored = set(skipped) | (set(OUTPUT_COLUMNS) if retagging else set())
    keys = [key for key in keys if key not in ignored]
    keys += [
        c for c in columns if is_code_column(c) and c not in keys and c not in ignored
    ]
    if profile.coordinates:
        keys += list(profile.coordinates)
    return keys


def _reader(source: str) -> str:
    name = source.split("?")[0].casefold()
    literal = _literal(source)
    if ".csv" in name or ".tsv" in name or name.endswith(".txt"):
        # Read as text: PSGC codes would otherwise lose their leading zeros.
        return f"read_csv({literal}, all_varchar = true)"
    if name.endswith(
        (".json", ".jsonl", ".ndjson", ".geojson", ".json.gz", ".jsonl.gz")
    ):
        return f"read_json_auto({literal})"
    if name.endswith(".parquet"):
        return f"read_parquet({literal})"
    raise ValueError(
        f"unsupported dataset format: {source} "
        "(use .csv, .tsv, .json, .jsonl, .ndjson, .geojson, or .parquet)"
    )


def _output_format(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        return "FORMAT csv, HEADER"
    if suffix == ".parquet":
        return "FORMAT parquet"
    if suffix in (".jsonl", ".ndjson", ".json"):
        return "FORMAT json"
    raise ValueError(f"unsupported output format: {path} (use .csv, .parquet, .jsonl)")


def _fetch_dicts(connection, sql: str) -> list[dict[str, object]]:
    cursor = connection.execute(sql)
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _stem(source: str) -> str:
    name = Path(source.split("?")[0]).name
    for suffix in (
        ".gz",
        ".csv",
        ".tsv",
        ".parquet",
        ".jsonl",
        ".ndjson",
        ".geojson",
        ".json",
    ):
        name = name.removesuffix(suffix)
    return name


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"
