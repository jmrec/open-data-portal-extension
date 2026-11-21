"""Turn a source row into a ``Mention``: the only step that depends on file layout."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .models.dataset import DatasetProfile
from .models.mention import Hint, Mention
from .models.psgc import GeoLevel
from .normalization import normalize_name

_CODE = re.compile(r"(?<!\d)(\d{10})(?!\d)")

Row = Mapping[str, object]


def extract_mention(profile: DatasetProfile, row: Row) -> Mention:
    hints: list[Hint] = []

    seen_levels: set[GeoLevel] = set()
    for mapping in profile.place_columns:
        level = mapping.level
        text = _text(row.get(mapping.column))
        if level is None or text is None or level in seen_levels:
            continue
        seen_levels.add(level)
        hints.append(Hint(kind="name", text=text, level=level))

    for column in profile.free_text_columns:
        text = _text(row.get(column))
        if text is None:
            continue
        for segment in text.split(","):
            if normalize_name(segment):
                hints.append(Hint(kind="name", text=segment.strip()))

    codes = dict.fromkeys(
        code for value in row.values() for code in _CODE.findall(str(value))
    )
    hints.extend(Hint(kind="code", text=code) for code in codes)

    coordinates = profile.coordinates
    lat, lon = (
        (_as_float(row.get(coordinates[0])), _as_float(row.get(coordinates[1])))
        if coordinates
        else (None, None)
    )
    if lat is not None and lon is not None:
        level = Mention(hints=tuple(hints)).target_level or GeoLevel.BARANGAY
        hints.append(Hint(kind="point", text=f"{lat},{lon}", level=level))

    return Mention(hints=tuple(hints))


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except ValueError:
        return None
