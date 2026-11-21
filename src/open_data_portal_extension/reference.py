"""PSGC reference data, read-only at runtime.

``reference_build`` writes the DuckDB file; ``ReferenceStore.open`` loads it
into memory, because resolution makes thousands of tiny lookups and a query
each was most of the run time. Only ``locate`` queries the file, for the
spatial join.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple, Self

import duckdb

from .models.psgc import (
    GeoLevel,
    PsgcCode,
    PsgcCrosswalk,
    PsgcEntry,
    PsgcFormerParent,
    PsgcSnapshot,
)
from .normalization import normalize_name

Point = tuple[float, float]

NEARBY_METERS = 250.0

BOUNDARY_CRS = "EPSG:32651"
"""UTM zone 51N, distances are in meters."""


class Location(NamedTuple):
    code: str
    outside_m: float
    """0 when inside the barangay."""


class ReferenceStore:
    def __init__(
        self,
        snapshot: PsgcSnapshot,
        entries: Iterable[PsgcEntry],
        *,
        aliases: Iterable[tuple[PsgcCode, str]] = (),
        crosswalk: Iterable[PsgcCrosswalk] = (),
        former_parents: Iterable[PsgcFormerParent] = (),
        connection: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        """``aliases`` are ``(code, text)``; ``connection`` holds boundaries."""
        self._snapshot = snapshot
        self._connection = connection
        self._entries: dict[str, PsgcEntry] = {}
        self._children: dict[str | None, list[PsgcEntry]] = defaultdict(list)
        self._names: dict[tuple[GeoLevel, str], list[PsgcEntry]] = defaultdict(list)
        for entry in entries:
            self._entries[entry.code] = entry
            self._children[entry.parent_code].append(entry)
            self._names[(entry.level, normalize_name(entry.name))].append(entry)

        for code, text in aliases:
            entry = self._entries.get(code)
            normalized = normalize_name(text)
            if entry is None or not normalized:
                continue
            named = self._names[(entry.level, normalized)]
            if entry not in named:
                named.append(entry)

        self._crosswalk: dict[str, list[str]] = defaultdict(list)
        for change in crosswalk:
            if change.effective <= snapshot.released_on:
                self._crosswalk[change.old_code].extend(change.new_codes)

        self._former_parents: dict[str, list[str]] = defaultdict(list)
        for former in sorted(former_parents, key=lambda f: f.until):
            parents = self._former_parents[former.code]
            if (
                former.until <= snapshot.released_on
                and former.parent_code not in parents
            ):
                parents.append(former.parent_code)

    @classmethod
    def open(cls, path: Path | str) -> ReferenceStore:
        """Load a database written by ``reference_build``."""
        connection = duckdb.connect(str(path), read_only=True)
        try:
            row = connection.execute(
                "SELECT version, released_on FROM psgc_snapshot WHERE id = 1"
            ).fetchone()
            if row is None:
                raise ValueError(f"{path} has no PSGC snapshot")
            entries = [
                PsgcEntry(
                    code=code, name=name, level=GeoLevel(level), parent_code=parent
                )
                for code, name, level, parent in connection.execute(
                    "SELECT code, name, level, parent_code FROM psgc_entries "
                    "ORDER BY code"
                ).fetchall()
            ]
            crosswalk = [
                PsgcCrosswalk(
                    old_code=old, new_codes=[new], change=change, effective=on
                )
                for old, new, change, on in connection.execute(
                    "SELECT old_code, new_code, change, effective FROM psgc_crosswalk "
                    "ORDER BY effective, new_code"
                ).fetchall()
            ]
            former_parents = [
                PsgcFormerParent(code=code, parent_code=parent, until=until)
                for code, parent, until in connection.execute(
                    "SELECT code, parent_code, until FROM psgc_former_parents"
                ).fetchall()
            ]
            # Aliases are stored normalized; normalizing again is a no-op.
            aliases = connection.execute(
                "SELECT code, normalized_alias FROM psgc_aliases ORDER BY code"
            ).fetchall()
        except BaseException:
            connection.close()
            raise
        return cls(
            PsgcSnapshot(version=row[0], released_on=row[1]),
            entries,
            aliases=aliases,
            crosswalk=crosswalk,
            former_parents=former_parents,
            connection=connection,
        )

    def snapshot(self) -> PsgcSnapshot:
        return self._snapshot

    def get(self, code: PsgcCode) -> PsgcEntry | None:
        return self._entries.get(code)

    def children(self, code: PsgcCode | None) -> list[PsgcEntry]:
        return list(self._children.get(code, []))

    def lookup(
        self,
        level: GeoLevel,
        normalized_name: str,
        parent_code: PsgcCode | None = None,
    ) -> list[PsgcEntry]:
        """Entries whose normalized name or alias is ``normalized_name``."""
        return [
            entry
            for entry in self._names.get((level, normalized_name), [])
            if parent_code is None or entry.parent_code == parent_code
        ]

    def resolve_crosswalk(self, code: PsgcCode) -> list[PsgcCode]:
        """Today's codes for a merged, split, renamed, or reclassified code."""
        return list(self._crosswalk.get(code, [code]))

    def former_parents(self, code: PsgcCode) -> list[PsgcCode]:
        """Parents ``code`` had before a transfer, oldest first."""
        return list(self._former_parents.get(code, []))

    def has_boundaries(self) -> bool:
        if self._connection is None:
            return False
        return bool(
            self._connection.execute(
                "SELECT count(*) FROM duckdb_tables() "
                "WHERE table_name = 'psgc_boundaries'"
            ).fetchone()[0]
        )

    def locate(
        self,
        points: Sequence[Point],
        *,
        within_m: float = NEARBY_METERS,
    ) -> dict[Point, Location]:
        """The barangay each ``(lat, lon)`` is in, else the nearest within ``within_m``."""
        unique = list(dict.fromkeys(points))
        if not unique or not self.has_boundaries():
            return {}
        connection = self._connection.cursor()
        try:
            connection.execute("INSTALL spatial; LOAD spatial")
            connection.execute(
                "CREATE TEMP TABLE psgc_projected AS "
                f"SELECT lat, lon, ST_Transform(ST_Point(lon, lat), 'EPSG:4326', "
                f"'{BOUNDARY_CRS}', always_xy := true) AS geom "
                "FROM (SELECT unnest(?::DOUBLE[]) AS lat, unnest(?::DOUBLE[]) AS lon)",
                [[lat for lat, _ in unique], [lon for _, lon in unique]],
            )
            connection.execute(
                "CREATE TEMP TABLE psgc_inside AS "
                "SELECT p.lat, p.lon, b.code FROM psgc_projected AS p "
                "JOIN psgc_boundaries AS b ON ST_Contains(b.geom, p.geom) "
                "QUALIFY row_number() OVER (PARTITION BY p.lat, p.lon ORDER BY b.code) = 1"
            )
            found: dict[Point, Location] = {
                (lat, lon): Location(code, 0.0)
                for lat, lon, code in connection.execute(
                    "SELECT lat, lon, code FROM psgc_inside"
                ).fetchall()
            }
            if len(found) < len(unique) and within_m > 0:
                nearby = connection.execute(
                    "SELECT p.lat, p.lon, b.code, ST_Distance(b.geom, p.geom) AS meters "
                    "FROM psgc_projected AS p "
                    "ANTI JOIN psgc_inside AS i ON p.lat = i.lat AND p.lon = i.lon "
                    "JOIN psgc_boundaries AS b ON ST_DWithin(b.geom, p.geom, ?) "
                    "QUALIFY row_number() OVER "
                    "(PARTITION BY p.lat, p.lon ORDER BY meters, b.code) = 1",
                    [float(within_m)],
                ).fetchall()
                for lat, lon, code, meters in nearby:
                    found[(lat, lon)] = Location(code, max(float(meters), 0.001))
            return found
        finally:
            connection.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["BOUNDARY_CRS", "Location", "ReferenceStore"]
