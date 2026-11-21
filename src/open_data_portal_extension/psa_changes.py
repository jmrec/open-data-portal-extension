"""Turn PSA's cumulative "Summary of Changes" workbook into aliases, crosswalk
entries, and former parents, so older datasets resolve against today's places.

Codes that still exist are never remapped: some moved away and back (Negros
Occidental in 2015, 2017, and 2024). Changes whose place cannot be found today
are skipped, not guessed.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .models.psgc import GeoLevel, PsgcCrosswalk, PsgcEntry, PsgcFormerParent
from .normalization import normalize_name

_MONTHS = {
    name: number
    for number, name in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
_HEADER_FIRST_CELL = "region/province/municipal/bgy. name"


@dataclass(frozen=True)
class Change:
    name: str
    """As named at the time, usually "<name>, <parent>"."""

    unit_type: str

    new_code: str | None
    old_name: str | None
    """For renames, the old name; for transfers, the old parent ("mother unit")."""

    old_code: str | None
    effective: date


@dataclass
class History:
    aliases: list[tuple[str, str]] = field(default_factory=list)

    crosswalk: list[PsgcCrosswalk] = field(default_factory=list)
    former_parents: list[PsgcFormerParent] = field(default_factory=list)


def read_changes(path: Path) -> list[Change]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        changes: list[Change] = []
        for sheet in workbook.worksheets:
            changes.extend(parse_rows(sheet.iter_rows(values_only=True)))
        return changes
    finally:
        workbook.close()


def parse_rows(rows: Iterable[Sequence[object]]) -> list[Change]:
    """Section headers ("April to June 2021") date the rows below them."""
    changes: list[Change] = []
    effective: date | None = None
    previous: Change | None = None
    for row in rows:
        cells = [_text(value) for value in list(row)[:5]]
        cells += [None] * (5 - len(cells))
        name, unit_type, new_code, old_name, old_code = cells
        if name is None:
            continue
        if not any(cells[1:]):
            effective = _section_date(name) or effective
            previous = None
            continue
        if name.casefold() == _HEADER_FIRST_CELL:
            continue
        if unit_type is None:
            if previous is None:
                continue
            unit_type = previous.unit_type
        if effective is None:
            continue

        if (
            previous is not None
            and _kind(unit_type) == "split"
            and previous.unit_type == unit_type
            and old_name is None
            and old_code is None
        ):
            old_name, old_code = previous.old_name, previous.old_code

        change = Change(
            name=name,
            unit_type=unit_type,
            new_code=_code(new_code),
            old_name=old_name,
            old_code=_code(old_code),
            effective=effective,
        )
        changes.append(change)
        previous = change
    return changes


def derive_history(
    changes: Sequence[Change],
    entries: Sequence[PsgcEntry],
    *,
    released_on: date,
) -> History:
    by_code = {entry.code: entry for entry in entries}
    by_name: dict[str, list[PsgcEntry]] = defaultdict(list)
    for entry in entries:
        by_name[normalize_name(entry.name)].append(entry)

    applicable = sorted(
        (change for change in changes if change.effective <= released_on),
        key=lambda change: change.effective,
    )

    moves: dict[str, list[tuple[date, str]]] = defaultdict(list)
    for change in applicable:
        if change.old_code and change.new_code and change.old_code != change.new_code:
            moves[change.old_code].append((change.effective, change.new_code))

    def current(code: str | None, seen: frozenset[str] = frozenset()) -> list[str]:
        if code is None or code in seen:
            return []
        if code in by_code:
            return [code]
        history = moves.get(code)
        if not history:
            return []
        latest = max(when for when, _ in history)
        found: list[str] = []
        for when, new_code in history:
            if when == latest:
                for target in current(new_code, seen | {code}):
                    if target not in found:
                        found.append(target)
        return found

    def place(change: Change) -> list[str]:
        # Some rows carry their parent's code, so keep only the level the type
        # names ("Transfer of city").
        found = current(change.new_code) or _find_by_name(change, by_name, by_code)
        level = _level_named(change.unit_type)
        if level is None:
            return found
        return [code for code in found if by_code[code].level is level]

    history = History()
    seen_aliases: set[tuple[str, str]] = set()

    def alias(code: str, text: str | None) -> None:
        if not text:
            return
        normalized = normalize_name(text)
        if not normalized or normalized == normalize_name(by_code[code].name):
            return
        if (code, normalized) not in seen_aliases:
            seen_aliases.add((code, normalized))
            history.aliases.append((code, text))

    last_moved: dict[str, Change] = {}
    for change in applicable:
        kind = _kind(change.unit_type)
        targets = place(change)

        if kind in ("renamed", "split"):
            for code in targets:
                alias(code, change.old_name)

        for code in targets:
            if by_code[code].level is not GeoLevel.BARANGAY:
                alias(code, _unit_name(change.name))

        if kind == "transferred" and change.old_code:
            for code in targets:
                parent = _former_parent(change.old_code, by_code[code], current)
                if parent is not None:
                    history.former_parents.append(
                        PsgcFormerParent(
                            code=code, parent_code=parent, until=change.effective
                        )
                    )

        if change.old_code and change.old_code not in by_code:
            last_moved[change.old_code] = change

    for old_code, change in last_moved.items():
        targets = current(old_code)
        if targets:
            history.crosswalk.append(
                PsgcCrosswalk(
                    old_code=old_code,
                    new_codes=targets,
                    change=_crosswalk_kind(_kind(change.unit_type)),
                    effective=change.effective,
                )
            )
    return history


def to_ten_digits(value: object) -> str | None:
    """Codes were 9 digits before 2018 (RR PP MM BBB); today's are 10 (RR PPP MM BBB)."""
    return _code(_text(value))


def _code(text: str | None) -> str | None:
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        digits = "0" + digits
    if len(digits) == 9:
        return digits[:2] + "0" + digits[2:]
    if len(digits) == 10:
        return digits
    return None


def _former_parent(old_code: str, entry: PsgcEntry, current) -> str | None:
    prefixes = {
        GeoLevel.PROVINCE: [old_code[:2] + "0" * 8],
        GeoLevel.CITY_MUNICIPALITY: [old_code[:5] + "0" * 5, old_code[:2] + "0" * 8],
        GeoLevel.SUB_MUNICIPALITY: [old_code[:7] + "000"],
        GeoLevel.BARANGAY: [old_code[:7] + "000", old_code[:5] + "0" * 5],
    }.get(entry.level, [])
    for prefix in prefixes:
        if prefix == old_code:
            continue
        found = current(prefix)
        if len(found) == 1 and found[0] not in (entry.code, entry.parent_code):
            return found[0]
    return None


def _find_by_name(
    change: Change,
    by_name: dict[str, list[PsgcEntry]],
    by_code: dict[str, PsgcEntry],
) -> list[str]:
    _, _, parent = change.name.partition(",")
    matches = by_name.get(normalize_name(_unit_name(change.name)), [])
    level = _level_named(change.unit_type)
    if level is not None:
        matches = [entry for entry in matches if entry.level is level]
    if parent.strip() and len(matches) > 1:
        wanted = normalize_name(parent.split(",")[0])
        matches = [
            entry
            for entry in matches
            if entry.parent_code in by_code
            and normalize_name(by_code[entry.parent_code].name) == wanted
        ]
    return [matches[0].code] if len(matches) == 1 else []


_LEVEL_WORDS = {
    "barangay": GeoLevel.BARANGAY,
    "municipality": GeoLevel.CITY_MUNICIPALITY,
    "city": GeoLevel.CITY_MUNICIPALITY,
    "province": GeoLevel.PROVINCE,
    "region": GeoLevel.REGION,
}


def _level_named(unit_type: str) -> GeoLevel | None:
    """The first level named: "Transferred municipality and its barangay" is a municipality."""
    text = unit_type.casefold()
    found = [(text.find(word), level) for word, level in _LEVEL_WORDS.items()]
    found = [(index, level) for index, level in found if index >= 0]
    return min(found, key=lambda pair: pair[0])[1] if found else None


def _unit_name(name: str) -> str:
    return name.split(",")[0].split("[")[0].strip()


def _kind(unit_type: str) -> str:
    text = unit_type.casefold()
    if any(word in text for word in ("division", "splitting", "fragmentation")):
        return "split"
    if "merg" in text:
        return "merged"
    if "name" in text or "renam" in text:
        return "renamed"
    if "transfer" in text or "change of code" in text:
        return "transferred"
    return "other"


def _crosswalk_kind(kind: str) -> str:
    return (
        kind
        if kind in ("split", "merged", "renamed", "transferred")
        else "reclassified"
    )


def _section_date(text: str) -> date | None:
    lowered = text.casefold()
    if not re.search("|".join(_MONTHS), lowered):
        return None
    month = re.search("|".join(_MONTHS), lowered)
    year = re.search(r"\b(19|20)\d{2}\b", lowered)
    if year is None:
        return None
    return date(int(year.group()), _MONTHS[month.group()] if month else 1, 1)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None
