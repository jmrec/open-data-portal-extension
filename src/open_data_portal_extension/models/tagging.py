from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_serializer, model_validator

from .psgc import GeoLevel, PsgcCode


class MatchMethod(StrEnum):
    EXISTING_CODE = "existing_code"
    NAME_EXACT = "name_exact"
    NAME_FUZZY = "name_fuzzy"
    SPATIAL = "spatial"


SCORE_DECIMALS = 3


class TagStatus(StrEnum):
    AUTO = "auto"
    """Accepted above the confidence threshold"""

    NEEDS_REVIEW = "needs_review"
    """Below threshold or ambiguous"""


class MatchCandidate(BaseModel):
    code: PsgcCode
    level: GeoLevel
    score: float = Field(ge=0, le=1)
    method: MatchMethod

    @field_serializer("score")
    def _round_score(self, value: float) -> float:
        return round(value, SCORE_DECIMALS)


class PlaceTag(BaseModel):
    """The PSGC tag for one source record, at the level the dataset reports."""

    dataset_key: str
    row_id: str
    level: GeoLevel | None
    """None when nothing matched and the level is unknown"""

    code: PsgcCode | None = None
    status: TagStatus
    method: MatchMethod | None = None
    confidence: float = Field(ge=0, le=1)
    candidates: list[MatchCandidate] = Field(default_factory=list)
    psgc_version: str

    @field_serializer("confidence")
    def _round_confidence(self, value: float) -> float:
        return round(value, SCORE_DECIMALS)

    @model_validator(mode="after")
    def code_matches_status(self) -> PlaceTag:
        if self.status is TagStatus.AUTO and self.code is None:
            raise ValueError(f"status {self.status} requires a PSGC code")
        if self.status is TagStatus.NEEDS_REVIEW and self.code is not None:
            raise ValueError("needs_review tags should hold candidates, not a code")
        return self
