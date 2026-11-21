from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

PsgcCode = Annotated[str, StringConstraints(pattern=r"^\d{10}$")]
"""PSGC codes are 10 digits. Keep them as strings to preserve leading zeros."""


class GeoLevel(StrEnum):
    REGION = "region"
    PROVINCE = "province"
    CITY_MUNICIPALITY = "city_municipality"
    SUB_MUNICIPALITY = "sub_municipality"
    BARANGAY = "barangay"


class PsgcEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: PsgcCode
    name: str
    level: GeoLevel
    parent_code: PsgcCode | None = None


class PsgcSnapshot(BaseModel):
    """The reference release a tag was produced against."""

    version: str

    released_on: date


class PsgcCrosswalk(BaseModel):
    old_code: PsgcCode
    new_codes: list[PsgcCode]
    change: Literal["merged", "split", "renamed", "reclassified", "transferred"]
    effective: date


class PsgcFormerParent(BaseModel):
    """A parent before a transfer (Region VI for Negros Occidental), which older
    datasets still name."""

    model_config = ConfigDict(frozen=True)

    code: PsgcCode
    parent_code: PsgcCode
    until: date
