"""Normalization applied to both datasets and the reference, so "SAN ISIDRO CITY"
matches "City of San Isidro" and "Sto. Niño" matches "Santo Nino".
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_PARENTHETICAL = re.compile(r"\([^)]*\)")

_ABBREVIATIONS = {
    "sto": "santo",
    "sta": "santa",
    "brgy": "",
    "bgy": "",
    "pob": "poblacion",
    "gen": "general",
}

_LEADING = {
    "city",
    "municipality",
    "province",
    "barangay",
    "region",
    "of",
}

_TRAILING = {
    "city",
    "municipality",
    "province",
    "barangay",
    "philippines",
    "pilipinas",
}

_ROMAN = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
    "xi": "11",
    "xii": "12",
    "xiii": "13",
    "xiv": "14",
    "xv": "15",
    "xvi": "16",
    "xvii": "17",
    "xviii": "18",
    "xix": "19",
    "xx": "20",
}


def normalize_header(value: str) -> str:
    """Normalize a column header so ``City/Municipality`` and ``city_municipality`` agree."""

    text = value.casefold().replace("/", " ")
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def normalize_name(value: str) -> str:

    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = _PARENTHETICAL.sub(" ", text)
    text = _NON_ALNUM.sub(" ", text)

    tokens = [_ABBREVIATIONS.get(token, token) for token in text.split()]
    tokens = [token for token in tokens if token]
    tokens = [_ROMAN.get(token, token) for token in tokens]

    while tokens and tokens[0] in _LEADING:
        tokens.pop(0)
    while tokens and tokens[-1] in _TRAILING:
        tokens.pop()

    return " ".join(tokens)
