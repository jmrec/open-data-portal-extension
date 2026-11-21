"""Score tagged places against hand-checked labels.

A labels file (``evals/labels/<name>.csv``) holds one distinct place per row:
the dataset's place columns, then ``expected_code`` (blank when the row names no
taggable place) and ``checked`` (who verified it). Rows without ``checked`` are
not scored. ``proposed_*`` and ``barangay_*`` columns are there to help whoever
checks; scoring ignores them.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from pathlib import Path

from .reference import ReferenceStore
from .tabular import Place

EXPECTED, CHECKED = "expected_code", "checked"
PROPOSED = ("proposed_code", "proposed_place", "proposed_status", "rows")
_META = {EXPECTED, CHECKED, *PROPOSED}


def _is_meta(column: str) -> bool:
    return column in _META or column.startswith("barangay_")


@dataclass
class Score:
    checked: int = 0
    auto: int = 0
    auto_correct: int = 0
    review: int = 0
    unmatched: int = 0
    """Checked labels whose place no longer appears, e.g. after a detection change."""

    wrong: list[tuple[dict[str, str], str | None, str | None]] = field(
        default_factory=list
    )
    """``(place, expected, tagged)`` for each wrong automatic tag."""

    @property
    def auto_precision(self) -> float | None:
        return self.auto_correct / self.auto if self.auto else None

    @property
    def correct_rate(self) -> float | None:
        """Share of checked places tagged automatically and correctly."""
        matched = self.checked - self.unmatched
        return self.auto_correct / matched if matched else None

    def summary(self) -> dict:
        def rounded(value: float | None) -> float | None:
            return None if value is None else round(value, 4)

        return {
            "checked": self.checked,
            "auto_precision": rounded(self.auto_precision),
            "correct_rate": rounded(self.correct_rate),
            "wrong": len(self.wrong),
        }


def _key(values: dict[str, object], columns: list[str]) -> tuple[str, ...]:
    return tuple("" if values.get(c) is None else str(values[c]) for c in columns)


def read_labels(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """The labels file's place columns and rows."""
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = [c for c in reader.fieldnames or [] if not _is_meta(c)]
        return columns, list(reader)


def score(places: list[Place], path: Path) -> Score | None:
    """Score ``places`` against the checked rows in ``path``; ``None`` if none."""
    columns, rows = read_labels(path)
    checked = [row for row in rows if row.get(CHECKED, "").strip()]
    if not checked:
        return None
    by_key = {_key(place.values, columns): place for place in places}
    result = Score(checked=len(checked))
    for row in checked:
        place = by_key.get(_key(row, columns))
        if place is None:
            result.unmatched += 1
            continue
        expected = row.get(EXPECTED, "").strip() or None
        if place.status == "auto":
            result.auto += 1
            if place.code == expected:
                result.auto_correct += 1
            else:
                values = {c: row[c] for c in columns}
                result.wrong.append((values, expected, place.code))
        else:
            result.review += 1
    return result


def sample(
    places: list[Place],
    path: Path,
    reference: ReferenceStore,
    *,
    size: int,
    seed: str,
) -> int:
    """Append ``size`` unlabeled places to ``path``, chosen uniformly at random.

    Uniform over distinct places, not rows, so rare spellings get checked too.
    ``expected_code`` starts as the proposal: correct it, then fill ``checked``.
    """
    taggable = [place for place in places if place.status != "no_place"]
    columns, rows = read_labels(path)
    if not columns and taggable:
        columns = list(taggable[0].values)
    seen = {_key(row, columns) for row in rows}
    fresh = [p for p in taggable if _key(p.values, columns) not in seen]
    chosen = random.Random(seed).sample(fresh, min(size, len(fresh)))

    extra = [c for c in (rows[0] if rows else {}) if c.startswith("barangay_")]
    header = [*columns, EXPECTED, CHECKED, *PROPOSED, *extra]
    for place in chosen:
        top = place.code or place.best_code
        rows.append(
            {
                **{c: _text(place.values.get(c)) for c in columns},
                EXPECTED: top or "",
                CHECKED: "",
                "proposed_code": top or "",
                "proposed_place": describe(reference, top) if top else "",
                "proposed_status": place.status,
                "rows": str(place.rows),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(chosen)


def describe(reference: ReferenceStore, code: str) -> str:
    """ "Danglas, Abra, Cordillera Administrative Region" for a code."""
    names = []
    entry = reference.get(code)
    while entry is not None:
        names.append(entry.name)
        entry = reference.get(entry.parent_code) if entry.parent_code else None
    return ", ".join(names)


def _text(value: object) -> str:
    return "" if value is None else str(value)
