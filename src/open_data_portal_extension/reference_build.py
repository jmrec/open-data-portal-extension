"""Build the reference database from a faeldon/philippines-psgc-shapefiles release.

Source quirks handled here:

- Codes are stored as numbers, so regions 01-09 lose their leading zero.
- Level 4 mixes barangays with Manila's sub-municipalities and two rows with no
  level (gaps between barangays), which are dropped.
- Parents come from the ``admN_psgc`` columns, not the code's digits: highly
  urbanized cities sit under their geographic province.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .models.psgc import (
    GeoLevel,
    PsgcCrosswalk,
    PsgcEntry,
    PsgcFormerParent,
    PsgcSnapshot,
)
from .normalization import normalize_name
from .psa_changes import derive_history, read_changes
from .reference import BOUNDARY_CRS

SOURCE_FILES = {
    GeoLevel.REGION: "PH_Adm1_Regions.csv",
    GeoLevel.PROVINCE: "PH_Adm2_ProvDists.csv",
    GeoLevel.CITY_MUNICIPALITY: "PH_Adm3_MuniCities.csv",
    GeoLevel.BARANGAY: "PH_Adm4_BgySubMuns.csv",
}

# (code, name, parent_code, level) per level, read as text so nothing is coerced.
_QUERIES = {
    GeoLevel.REGION: """
        SELECT lpad(adm1_psgc, 10, '0'), adm1_en, NULL, 'region'
        FROM read_csv({path}, all_varchar = true)
    """,
    GeoLevel.PROVINCE: """
        SELECT lpad(adm2_psgc, 10, '0'), adm2_en, lpad(adm1_psgc, 10, '0'), 'province'
        FROM read_csv({path}, all_varchar = true)
    """,
    GeoLevel.CITY_MUNICIPALITY: """
        SELECT lpad(adm3_psgc, 10, '0'), adm3_en, lpad(adm2_psgc, 10, '0'),
               'city_municipality'
        FROM read_csv({path}, all_varchar = true)
    """,
    GeoLevel.BARANGAY: """
        SELECT lpad(adm4_psgc, 10, '0'), adm4_en, lpad(adm3_psgc, 10, '0'),
               CASE geo_level WHEN 'Bgy' THEN 'barangay'
                              WHEN 'SubMun' THEN 'sub_municipality' END
        FROM read_csv({path}, all_varchar = true)
        WHERE geo_level IN ('Bgy', 'SubMun')
    """,
}


MANUAL_ALIASES: list[tuple[str, str]] = [
    # PSA records BARMM as a new region with no old code
    ("1900000000", "Autonomous Region in Muslim Mindanao"),
    ("1900000000", "ARMM"),
    # PSGC names it "NCR, City of Manila, First District"
    ("1303900000", "NCR, First District"),
]


class SourceError(ValueError):
    """The source files are missing or break an invariant."""


@dataclass(frozen=True)
class BuildReport:
    counts: dict[GeoLevel, int]
    aliases: int = 0
    crosswalk: int = 0
    former_parents: int = 0
    boundaries: int = 0

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def load_entries(source_dir: Path) -> list[PsgcEntry]:
    missing = [
        name for name in SOURCE_FILES.values() if not (source_dir / name).exists()
    ]
    if missing:
        raise SourceError(f"missing in {source_dir}: {', '.join(missing)}")

    connection = duckdb.connect(":memory:")
    try:
        rows: list[tuple[str, str, str | None, str]] = []
        for level, query in _QUERIES.items():
            path = (source_dir / SOURCE_FILES[level]).as_posix()
            sql = query.format(path="'" + path.replace("'", "''") + "'")
            rows.extend(connection.execute(sql).fetchall())
    finally:
        connection.close()

    entries = [
        PsgcEntry(code=code, name=name, level=GeoLevel(level), parent_code=parent)
        for code, name, parent, level in rows
    ]
    _validate(entries)
    return entries


_PARENTHETICAL = re.compile(r"\(([^)]*)\)")
_NOT_A_NAME = ("not ", "claimed")


def parenthetical_aliases(entries: list[PsgcEntry]) -> list[tuple[str, str]]:
    """Aliases for names like "Region III (Central Luzon)".

    ``normalize_name`` drops parentheticals, so the bracketed name would
    otherwise be unreachable.
    """
    aliases: list[tuple[str, str]] = []
    for entry in entries:
        for inner in _PARENTHETICAL.findall(entry.name):
            text = inner.strip()
            if text and not text.casefold().startswith(_NOT_A_NAME):
                aliases.append((entry.code, text))
    return aliases


def build(
    source_dir: Path,
    out_path: Path,
    snapshot: PsgcSnapshot,
    *,
    changes_path: Path | None = None,
    boundaries_path: Path | None = None,
) -> BuildReport:
    """Write a reference database, replacing ``out_path`` only once complete."""
    entries = load_entries(source_dir)
    codes = {entry.code for entry in entries}
    aliases = parenthetical_aliases(entries) + [
        (code, alias) for code, alias in MANUAL_ALIASES if code in codes
    ]
    crosswalk, former_parents = [], []
    if changes_path is not None:
        if not changes_path.exists():
            raise SourceError(f"no changes workbook at {changes_path}")
        history = derive_history(
            read_changes(changes_path), entries, released_on=snapshot.released_on
        )
        aliases += history.aliases
        crosswalk, former_parents = history.crosswalk, history.former_parents
    if boundaries_path is not None and not boundaries_path.exists():
        raise SourceError(f"no boundaries at {boundaries_path}")

    tmp_path = out_path.with_name(out_path.name + ".tmp")
    tmp_path.unlink(missing_ok=True)
    try:
        try:
            boundaries = write_reference(
                tmp_path,
                snapshot,
                entries,
                aliases=aliases,
                crosswalk=crosswalk,
                former_parents=former_parents,
                boundaries=boundaries_path,
            )
        except ValueError as error:
            raise SourceError(str(error)) from error
        os.replace(tmp_path, out_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return BuildReport(
        counts=dict(Counter(entry.level for entry in entries)),
        aliases=len(aliases),
        crosswalk=len(crosswalk),
        former_parents=len(former_parents),
        boundaries=boundaries,
    )


_SCHEMA = """
CREATE TABLE psgc_snapshot (
    id TINYINT PRIMARY KEY,
    version VARCHAR NOT NULL,
    released_on DATE NOT NULL
);
CREATE TABLE psgc_entries (
    code VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL,
    level VARCHAR NOT NULL,
    parent_code VARCHAR
);
CREATE TABLE psgc_aliases (
    code VARCHAR NOT NULL,
    normalized_alias VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    UNIQUE (code, normalized_alias)
);
CREATE TABLE psgc_crosswalk (
    old_code VARCHAR NOT NULL,
    new_code VARCHAR NOT NULL,
    change VARCHAR NOT NULL,
    effective DATE NOT NULL,
    UNIQUE (old_code, new_code, effective)
);
CREATE TABLE psgc_former_parents (
    code VARCHAR NOT NULL,
    parent_code VARCHAR NOT NULL,
    until DATE NOT NULL,
    UNIQUE (code, parent_code, until)
);
"""


def write_reference(
    path: Path,
    snapshot: PsgcSnapshot,
    entries: Iterable[PsgcEntry],
    *,
    aliases: Iterable[tuple[str, str]] = (),
    crosswalk: Iterable[PsgcCrosswalk] = (),
    former_parents: Iterable[PsgcFormerParent] = (),
    boundaries: Path | None = None,
) -> int:
    """Write a new database at ``path``; returns the number of boundaries."""
    connection = duckdb.connect(str(path))
    try:
        connection.execute(_SCHEMA)
        connection.execute(
            "INSERT INTO psgc_snapshot VALUES (1, ?, ?)",
            [snapshot.version, snapshot.released_on],
        )
        _insert(
            connection,
            "psgc_entries",
            [
                (e.code, e.name, normalize_name(e.name), e.level.value, e.parent_code)
                for e in entries
            ],
        )
        _insert(
            connection,
            "psgc_aliases",
            list(
                dict.fromkeys(
                    (code, normalize_name(text), "build")
                    for code, text in aliases
                    if normalize_name(text)
                )
            ),
            conflict="OR IGNORE",
        )
        _insert(
            connection,
            "psgc_crosswalk",
            [
                (c.old_code, new, c.change, c.effective)
                for c in crosswalk
                for new in c.new_codes
            ],
            conflict="OR IGNORE",
        )
        _insert(
            connection,
            "psgc_former_parents",
            [(f.code, f.parent_code, f.until) for f in former_parents],
            conflict="OR IGNORE",
        )
        return _load_boundaries(connection, boundaries) if boundaries else 0
    finally:
        connection.close()


def _insert(connection, table: str, rows: list[tuple], conflict: str = "") -> None:
    if not rows:
        return
    placeholders = ", ".join(["?"] * len(rows[0]))
    connection.executemany(
        f"INSERT {conflict} INTO {table} VALUES ({placeholders})", rows
    )


def _load_boundaries(connection, path: Path, *, simplify_m: float = 1.0) -> int:
    """Load ``PH_Adm4_BgySubMuns.parquet`` built in ``boundaries/``.

    Sub-municipalities are skipped: they overlap their barangays.
    """
    connection.execute("INSTALL spatial; LOAD spatial")
    source = "read_parquet(" + _literal(str(path)) + ")"
    columns = {
        name
        for name, *_ in connection.execute(
            f"DESCRIBE SELECT * FROM {source}"
        ).fetchall()
    }
    missing = {"adm4_psgc", "geo_level", "geom"} - columns
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
    xmin, ymin, xmax, ymax = connection.execute(
        f"SELECT min(ST_XMin(geom)), min(ST_YMin(geom)), "
        f"max(ST_XMax(geom)), max(ST_YMax(geom)) FROM {source}"
    ).fetchone()
    if not (110 <= xmin <= xmax <= 130 and 0 <= ymin <= ymax <= 25):
        raise ValueError(
            f"{path} does not look like WGS 84 longitude/latitude for the "
            f"Philippines (extent {xmin}, {ymin}, {xmax}, {ymax})"
        )
    projected = (
        f"ST_Transform(b.geom, 'EPSG:4326', '{BOUNDARY_CRS}', always_xy := true)"
    )
    connection.execute(
        f"CREATE TABLE psgc_boundaries AS "
        f"SELECT b.adm4_psgc AS code, "
        f"ST_SimplifyPreserveTopology({projected}, {float(simplify_m)}) AS geom "
        f"FROM {source} AS b "
        f"WHERE b.geo_level = 'Bgy' "
        f"AND b.adm4_psgc IN (SELECT code FROM psgc_entries)"
    )
    connection.execute(
        "CREATE INDEX psgc_boundaries_geom_idx ON psgc_boundaries USING RTREE (geom)"
    )
    return connection.execute("SELECT count(*) FROM psgc_boundaries").fetchone()[0]


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _validate(entries: list[PsgcEntry]) -> None:
    by_code: dict[str, PsgcEntry] = {}
    duplicates: list[str] = []
    for entry in entries:
        if entry.code in by_code:
            duplicates.append(entry.code)
        by_code[entry.code] = entry
    if duplicates:
        raise SourceError(f"duplicate codes: {', '.join(sorted(duplicates)[:10])}")

    expected_parent = {
        GeoLevel.PROVINCE: GeoLevel.REGION,
        GeoLevel.CITY_MUNICIPALITY: GeoLevel.PROVINCE,
        GeoLevel.SUB_MUNICIPALITY: GeoLevel.CITY_MUNICIPALITY,
        GeoLevel.BARANGAY: GeoLevel.CITY_MUNICIPALITY,
    }
    problems: list[str] = []
    for entry in entries:
        if entry.level is GeoLevel.REGION:
            continue
        parent = by_code.get(entry.parent_code or "")
        want = expected_parent[entry.level]
        if parent is None:
            problems.append(
                f"{entry.code} {entry.name!r}: parent {entry.parent_code} not found"
            )
        elif parent.level is not want:
            problems.append(
                f"{entry.code} {entry.name!r}: parent {parent.code} is {parent.level}, "
                f"expected {want}"
            )
    if problems:
        shown = "\n  ".join(problems[:10])
        more = f"\n  ... and {len(problems) - 10} more" if len(problems) > 10 else ""
        raise SourceError(
            f"{len(problems)} entries have a bad parent:\n  {shown}{more}"
        )
