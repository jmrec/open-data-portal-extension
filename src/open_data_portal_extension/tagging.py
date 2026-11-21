"""Tag a row with a PSGC code, or mark it for review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .mentions import extract_mention
from .models.dataset import DatasetProfile
from .models.mention import Mention
from .models.tagging import MatchCandidate, PlaceTag, TagStatus
from .reference import Location, Point, ReferenceStore
from .resolution import PathResolver

Row = Mapping[str, object]


class TaggingPipeline:
    """Accepts the best candidate when it scores ``accept_threshold`` or more and
    no other is within ``ambiguity_margin``. Everything else needs review.
    """

    def __init__(
        self,
        reference: ReferenceStore,
        *,
        located: Mapping[Point, Location] | None = None,
        accept_threshold: float = 0.9,
        ambiguity_margin: float = 0.05,
    ) -> None:
        self.reference = reference
        self.accept_threshold = accept_threshold
        self.ambiguity_margin = ambiguity_margin
        self._resolver = PathResolver(reference, located=located)
        self._cache: dict[tuple, list[MatchCandidate]] = {}

    def tag_row(
        self,
        profile: DatasetProfile,
        row: Row,
        *,
        row_id: str,
    ) -> PlaceTag | None:
        """``None`` when the row says nothing about where it is."""
        mention = extract_mention(profile, row)
        if not mention.hints:
            return None

        candidates = self._cache.get(mention.key)
        if candidates is None:
            candidates = self._resolver.resolve(mention)
            self._cache[mention.key] = candidates
        return self.decide(profile.dataset_key, row_id, mention, candidates)

    def decide(
        self,
        dataset_key: str,
        row_id: str,
        mention: Mention,
        candidates: Sequence[MatchCandidate],
    ) -> PlaceTag:
        ordered = sorted(candidates, key=lambda c: c.score, reverse=True)
        fields = {
            "dataset_key": dataset_key,
            "row_id": row_id,
            "psgc_version": self.reference.snapshot().version,
        }
        if not ordered:
            return PlaceTag(
                **fields,
                level=mention.target_level,
                status=TagStatus.NEEDS_REVIEW,
                confidence=0.0,
            )

        best = ordered[0]
        ambiguous = any(
            best.score - other.score < self.ambiguity_margin for other in ordered[1:]
        )
        accepted = best.score >= self.accept_threshold and not ambiguous
        return PlaceTag(
            **fields,
            level=best.level,
            code=best.code if accepted else None,
            status=TagStatus.AUTO if accepted else TagStatus.NEEDS_REVIEW,
            method=best.method,
            confidence=best.score,
            candidates=ordered,
        )


__all__ = ["TaggingPipeline"]
