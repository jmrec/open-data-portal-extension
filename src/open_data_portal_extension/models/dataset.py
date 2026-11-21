from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .psgc import GeoLevel

ColumnKind = Literal["place", "free_text", "latitude", "longitude"]


class ColumnMapping(BaseModel):
    column: str
    kind: ColumnKind = "place"
    """``free_text`` holds a whole place string, such as "Saysain, Bagac, Bataan"."""

    level: GeoLevel | None = None
    """Set for ``place`` columns only."""

    confidence: float = Field(ge=0, le=1)
    source: Literal["header", "values", "manual"]


class DatasetProfile(BaseModel):
    """What we know about a dataset's columns."""

    dataset_key: str
    row_count: int = Field(ge=0)
    columns: list[str]
    mappings: list[ColumnMapping] = Field(default_factory=list)

    @property
    def place_columns(self) -> list[ColumnMapping]:
        return [m for m in self.mappings if m.kind == "place"]

    @property
    def free_text_columns(self) -> list[str]:
        return [m.column for m in self.mappings if m.kind == "free_text"]

    @property
    def coordinates(self) -> tuple[str, str] | None:
        """The ``(latitude, longitude)`` columns, when both are set."""
        lat = next((m.column for m in self.mappings if m.kind == "latitude"), None)
        lon = next((m.column for m in self.mappings if m.kind == "longitude"), None)
        return (lat, lon) if lat and lon else None

    @property
    def reported_level(self) -> GeoLevel | None:
        levels = [m.level for m in self.place_columns if m.level is not None]
        if not levels:
            return None
        order = list(GeoLevel)  # region is coarsest, barangay finest
        return max(levels, key=order.index)
