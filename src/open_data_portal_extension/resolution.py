"""Propose candidate places for each hint, then score each candidate by how much
of the mention its chain (the place, its ancestors and former parents) explains.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher

from .models.mention import Hint, Mention
from .models.psgc import GeoLevel, PsgcCode
from .models.tagging import MatchCandidate, MatchMethod
from .normalization import normalize_name
from .reference import Location, Point, ReferenceStore

_ORDER = list(GeoLevel)
"""coarsest to finest"""


class PathResolver:
    """Hints propose places; the chain that explains the most hints wins.

    Codes, exact names, and points are tried first. A name with no exact match
    falls back to fuzzy matching among the children of what the other hints
    found, so "Laoagg, Ilocos Norte" only searches Ilocos Norte.
    """

    def __init__(
        self,
        reference: ReferenceStore,
        *,
        located: Mapping[Point, Location] | None = None,
        fuzzy_threshold: float = 0.85,
        fuzzy_limit: int = 5,
        nearby_score: float = 0.85,
    ) -> None:
        """``located`` holds points already placed by ``ReferenceStore.locate``.

        A point inside a barangay scores 1.0. One just outside every barangay
        scores ``nearby_score``, so it needs an agreeing name to be accepted.
        """
        self._reference = reference
        self._located = located or {}
        self._fuzzy_threshold = fuzzy_threshold
        self._fuzzy_limit = fuzzy_limit
        self._nearby_score = nearby_score
        self._paths: dict[PsgcCode, frozenset[PsgcCode]] = {}

    def resolve(self, mention: Mention) -> list[MatchCandidate]:
        """Candidates at one level, best first."""
        hints = mention.hints
        if not hints:
            return []

        per_hint = [self._propose(hint) for hint in hints]
        anchors = list(dict.fromkeys(c.code for found in per_hint for c in found))
        for index, hint in enumerate(hints):
            if not per_hint[index] and hint.kind == "name":
                per_hint[index] = self._fuzzy(hint, anchors)

        wanted = mention.target_level
        targets: dict[PsgcCode, MatchCandidate] = {}
        for found in per_hint:
            for candidate in found:
                if wanted is not None and candidate.level is not wanted:
                    continue
                current = targets.get(candidate.code)
                if current is None or candidate.score > current.score:
                    targets[candidate.code] = candidate
        if not targets:
            return []

        scored = {
            code: self._explained(code, per_hint) / len(hints) for code in targets
        }
        best = max(scored.values())
        tied = [code for code, score in scored.items() if score >= best - 1e-9]

        # A bare "Bataan" names a province and barangays equally: prefer coarsest.
        level = min((targets[code].level for code in tied), key=_ORDER.index)

        chosen = [
            MatchCandidate(
                code=code,
                level=candidate.level,
                score=min(scored[code], 1.0),
                method=candidate.method,
            )
            for code, candidate in targets.items()
            if candidate.level is level
        ]
        chosen.sort(key=lambda candidate: candidate.score, reverse=True)
        return chosen

    def _propose(self, hint: Hint) -> list[MatchCandidate]:
        if hint.kind == "code":
            return self._code(hint)
        if hint.kind == "name":
            return self._exact(hint)
        return self._point(hint)

    def _code(self, hint: Hint) -> list[MatchCandidate]:
        found = []
        for code in self._reference.resolve_crosswalk(hint.text):
            entry = self._reference.get(code)
            if entry is not None:
                found.append(
                    MatchCandidate(
                        code=entry.code,
                        level=entry.level,
                        score=1.0,
                        method=MatchMethod.EXISTING_CODE,
                    )
                )
        return found

    def _exact(self, hint: Hint) -> list[MatchCandidate]:
        normalized = normalize_name(hint.text)
        if not normalized:
            return []
        return [
            MatchCandidate(
                code=entry.code,
                level=entry.level,
                score=1.0,
                method=MatchMethod.NAME_EXACT,
            )
            for level in _levels(hint)
            for entry in self._reference.lookup(level, normalized)
        ]

    def _fuzzy(self, hint: Hint, anchors: Sequence[PsgcCode]) -> list[MatchCandidate]:
        """Near-misses like "Laoagg", among regions and the anchors' children."""
        normalized = normalize_name(hint.text)
        if not normalized:
            return []
        pool = [self._reference.children(None)]
        pool.extend(self._reference.children(anchor) for anchor in anchors)
        wanted = set(_levels(hint))
        scored = []
        for entry in (e for group in pool for e in group):
            if entry.level not in wanted:
                continue
            ratio = SequenceMatcher(
                None, normalized, normalize_name(entry.name)
            ).ratio()
            if ratio >= self._fuzzy_threshold:
                scored.append(
                    MatchCandidate(
                        code=entry.code,
                        level=entry.level,
                        score=ratio,
                        method=MatchMethod.NAME_FUZZY,
                    )
                )
        scored.sort(key=lambda candidate: candidate.score, reverse=True)
        return scored[: self._fuzzy_limit]

    def _point(self, hint: Hint) -> list[MatchCandidate]:
        """The located barangay, or its ancestor at the hint's level."""
        if hint.level is None:
            return []
        lat, lon = (float(part) for part in hint.text.split(","))
        found = self._located.get((lat, lon))
        if found is None:
            return []
        entry = self._reference.get(found.code)
        while entry is not None and entry.level is not hint.level:
            if _ORDER.index(entry.level) < _ORDER.index(hint.level):
                return []
            entry = (
                self._reference.get(entry.parent_code) if entry.parent_code else None
            )
        if entry is None:
            return []
        return [
            MatchCandidate(
                code=entry.code,
                level=entry.level,
                score=self._nearby_score if found.outside_m > 0 else 1.0,
                method=MatchMethod.SPATIAL,
            )
        ]

    def _explained(
        self,
        code: PsgcCode,
        per_hint: Sequence[Sequence[MatchCandidate]],
    ) -> float:
        path = self._path(code)
        return sum(
            max((c.score for c in found if c.code in path), default=0.0)
            for found in per_hint
        )

    def _path(self, code: PsgcCode) -> frozenset[PsgcCode]:
        cached = self._paths.get(code)
        if cached is not None:
            return cached
        chain: set[PsgcCode] = set()
        pending = [code]
        while pending:
            current = pending.pop()
            entry = self._reference.get(current)
            if entry is None or entry.code in chain:
                continue
            chain.add(entry.code)
            if entry.parent_code:
                pending.append(entry.parent_code)
            pending.extend(self._reference.former_parents(entry.code))
        path = frozenset(chain or [code])
        self._paths[code] = path
        return path


def _levels(hint: Hint) -> list[GeoLevel]:
    return [hint.level] if hint.level is not None else list(GeoLevel)


__all__ = ["PathResolver"]
