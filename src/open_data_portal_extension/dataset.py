"""Column detection: which columns name places, and at what level."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .models.dataset import ColumnMapping, DatasetProfile
from .models.psgc import GeoLevel
from .normalization import normalize_header

_CODE_LIKE_HEADER = re.compile(r"\bpsgc\b|\bcode\b|\bgeocode\b")


def is_code_column(header: str) -> bool:
    return bool(_CODE_LIKE_HEADER.search(normalize_header(header)))


_HEADER_LEVELS = {
    "region": GeoLevel.REGION,
    "region name": GeoLevel.REGION,
    "reg": GeoLevel.REGION,
    "province": GeoLevel.PROVINCE,
    "province name": GeoLevel.PROVINCE,
    "prov": GeoLevel.PROVINCE,
    "city": GeoLevel.CITY_MUNICIPALITY,
    "city name": GeoLevel.CITY_MUNICIPALITY,
    "municipality": GeoLevel.CITY_MUNICIPALITY,
    "municipality name": GeoLevel.CITY_MUNICIPALITY,
    "city municipality": GeoLevel.CITY_MUNICIPALITY,
    "city or municipality": GeoLevel.CITY_MUNICIPALITY,
    "city mun": GeoLevel.CITY_MUNICIPALITY,
    "mun": GeoLevel.CITY_MUNICIPALITY,
    "locality": GeoLevel.CITY_MUNICIPALITY,
    "town": GeoLevel.CITY_MUNICIPALITY,
    "city town": GeoLevel.CITY_MUNICIPALITY,
    "barangay": GeoLevel.BARANGAY,
    "barangay name": GeoLevel.BARANGAY,
    "brgy": GeoLevel.BARANGAY,
    "brgy name": GeoLevel.BARANGAY,
    "bgy": GeoLevel.BARANGAY,
}

_FREE_TEXT_HEADERS = {"location", "address", "place", "site", "place name"}

_LAT_HEADERS = {"latitude", "lat"}
_LON_HEADERS = {"longitude", "lon", "lng", "long"}

_CITY_PREFIXES = ("city of", "municipality of")
_MAX_SAMPLE = 50


class ColumnDetector:
    def profile(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        dataset_key: str,
    ) -> DatasetProfile:
        """Detect from a sample of rows; ``row_count`` is the sample's size."""
        columns = list(rows[0]) if rows else []
        mappings = []
        for column in columns:
            sample = [
                str(row[column])
                for row in rows[:_MAX_SAMPLE]
                if row.get(column) not in (None, "")
            ]
            mapping = (
                self._from_header(column)
                or self._from_values(column, sample)
                or self._as_free_text(column)
            )
            if mapping is not None:
                mappings.append(mapping)
        mappings += _coordinates(columns)

        return DatasetProfile(
            dataset_key=dataset_key,
            row_count=len(rows),
            columns=columns,
            mappings=mappings,
        )

    def _from_header(self, column: str) -> ColumnMapping | None:
        header = normalize_header(column)
        if _CODE_LIKE_HEADER.search(header):
            return None

        level = _HEADER_LEVELS.get(header)
        if level is not None:
            return ColumnMapping(
                column=column,
                level=level,
                confidence=0.9,
                source="header",
            )

        if "barangay" in header or "brgy" in header or "bgy" in header:
            level = GeoLevel.BARANGAY
        elif "city" in header or "municipality" in header or "mun" in header:
            level = GeoLevel.CITY_MUNICIPALITY
        elif "province" in header or "prov" in header:
            level = GeoLevel.PROVINCE
        elif "region" in header or re.search(r"\breg\b", header):
            level = GeoLevel.REGION
        else:
            return None

        return ColumnMapping(
            column=column,
            level=level,
            confidence=0.8,
            source="header",
        )

    def _as_free_text(self, column: str) -> ColumnMapping | None:
        """Last resort: a "Location" or "Address" column holds a whole place string."""
        if normalize_header(column) not in _FREE_TEXT_HEADERS:
            return None
        return ColumnMapping(
            column=column,
            kind="free_text",
            confidence=0.7,
            source="header",
        )

    def _from_values(
        self,
        column: str,
        sample: Sequence[str],
    ) -> ColumnMapping | None:
        values = [value.strip().casefold() for value in sample if value.strip()]
        if not values:
            return None

        def share(predicate) -> float:
            return sum(1 for value in values if predicate(value)) / len(values)

        if share(lambda value: value.startswith(_CITY_PREFIXES)) >= 0.6:
            level = GeoLevel.CITY_MUNICIPALITY
        elif share(lambda value: value.startswith("province of")) >= 0.6:
            level = GeoLevel.PROVINCE
        elif share(lambda value: value.startswith(("barangay", "brgy", "bgy"))) >= 0.6:
            level = GeoLevel.BARANGAY
        elif share(lambda value: value.startswith("region")) >= 0.6:
            level = GeoLevel.REGION
        else:
            return None

        return ColumnMapping(
            column=column,
            level=level,
            confidence=0.6,
            source="values",
        )


def _coordinates(columns: Sequence[str]) -> list[ColumnMapping]:
    """A ``latitude``/``longitude`` pair, when exactly one of each is found."""
    lats = [c for c in columns if normalize_header(c) in _LAT_HEADERS]
    lons = [c for c in columns if normalize_header(c) in _LON_HEADERS]
    if len(lats) != 1 or len(lons) != 1:
        return []
    return [
        ColumnMapping(column=lats[0], kind="latitude", confidence=0.9, source="header"),
        ColumnMapping(
            column=lons[0], kind="longitude", confidence=0.9, source="header"
        ),
    ]


__all__ = ["ColumnDetector", "is_code_column"]
