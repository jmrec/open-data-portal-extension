"""Add a second opinion from the ``barangay`` package to a labels file.

barangay needs Python 3.13, so it runs outside the project environment:

    uv run --no-project --python 3.13 --with barangay==2026.10.12.0 \\
        python evals/compare_barangay.py evals/labels/memberships.csv

Each row gets ``barangay_code`` and ``barangay_place`` from ``search_fuzzy``,
searched at the level of our proposed code. The summary counts how often it
agrees with us and, for checked rows, with the label. Rows where the two
disagree are the most useful to check by hand.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from barangay import search_fuzzy

_CITY_HOOKS = [
    "province",
    "highly_urbanized_city",
    "independent_component_city",
    "component_city",
    "municipality",
]
HOOKS = {
    "province": ["province"],
    "city_municipality": _CITY_HOOKS,
    "barangay": [*_CITY_HOOKS, "barangay"],
}
_META = {
    "expected_code",
    "checked",
    "proposed_code",
    "proposed_place",
    "proposed_status",
    "rows",
}


def level_of(code: str) -> str:
    """PSGC codes are RR PPP MM BBB: trailing zeros give the level."""
    if code.endswith("00000"):
        return "province"
    if code.endswith("000"):
        return "city_municipality"
    return "barangay"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("labels", type=Path)
    parser.add_argument(
        "--skip",
        default="region",
        help="Comma-separated place columns left out of the query (default: region).",
    )
    parser.add_argument("--threshold", type=float, default=60.0)
    args = parser.parse_args()

    with args.labels.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    skip = {name.strip().casefold() for name in args.skip.split(",")}
    query_columns = [
        c
        for c in fields
        if c not in _META and not c.startswith("barangay_") and c.casefold() not in skip
    ]

    agree = checked = checked_us = checked_them = 0
    for row in rows:
        query = ", ".join(row[c] for c in query_columns if row[c].strip())
        level = level_of(row["proposed_code"]) if row["proposed_code"] else "barangay"
        found = (
            search_fuzzy(
                query, match_hooks=HOOKS[level], threshold=args.threshold, limit=1
            )
            if query
            else []
        )
        top = found[0] if found else None
        row["barangay_code"] = top.psgc_id if top else ""
        parts = (top.name, top.municipality, top.province) if top else ()
        row["barangay_place"] = ", ".join(dict.fromkeys(p for p in parts if p))
        agree += row["barangay_code"] == row["proposed_code"]
        if row["checked"].strip():
            checked += 1
            checked_us += row["proposed_code"] == row["expected_code"]
            checked_them += row["barangay_code"] == row["expected_code"]

    for column in ("barangay_code", "barangay_place"):
        if column not in fields:
            fields.append(column)
    with args.labels.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{args.labels}: barangay agrees with our proposal on {agree}/{len(rows)}")
    if checked:
        print(
            f"Checked rows: ours correct {checked_us}/{checked}, "
            f"barangay correct {checked_them}/{checked}"
        )


if __name__ == "__main__":
    main()
