from __future__ import annotations

from datetime import date

from openpyxl import Workbook

from open_data_portal_extension.models.mention import Hint, Mention
from open_data_portal_extension.models.psgc import (
    GeoLevel,
    PsgcEntry,
    PsgcFormerParent,
    PsgcSnapshot,
)
from open_data_portal_extension.psa_changes import (
    derive_history,
    parse_rows,
    read_changes,
    to_ten_digits,
)
from open_data_portal_extension.reference import ReferenceStore
from open_data_portal_extension.resolution import PathResolver

HEADER = (
    "Region/Province/Municipal/Bgy. Name",
    "Unit Type",
    "New Code",
    "Mother Unit/Old Name",
    "Old Code",
)

R6, R7, NIR, R11 = "0600000000", "0700000000", "1800000000", "1100000000"
NEG_OCC, BACOLOD = "1804500000", "1830200000"
DAVAO_SUR, DAVAO_OCC, MALITA = "1102400000", "1108600000", "1108603000"
DAVAO_DE_ORO = "1108200000"


def entries() -> list[PsgcEntry]:
    def entry(code, name, level, parent=None):
        return PsgcEntry(code=code, name=name, level=level, parent_code=parent)

    return [
        entry(R6, "Region VI (Western Visayas)", GeoLevel.REGION),
        entry(R7, "Region VII (Central Visayas)", GeoLevel.REGION),
        entry(NIR, "Negros Island Region (NIR)", GeoLevel.REGION),
        entry(R11, "Region XI (Davao Region)", GeoLevel.REGION),
        entry(NEG_OCC, "Negros Occidental", GeoLevel.PROVINCE, NIR),
        entry(DAVAO_SUR, "Davao del Sur", GeoLevel.PROVINCE, R11),
        entry(DAVAO_OCC, "Davao Occidental", GeoLevel.PROVINCE, R11),
        entry(DAVAO_DE_ORO, "Davao de Oro", GeoLevel.PROVINCE, R11),
        entry(BACOLOD, "City of Bacolod", GeoLevel.CITY_MUNICIPALITY, NEG_OCC),
        entry(MALITA, "Malita", GeoLevel.CITY_MUNICIPALITY, DAVAO_OCC),
    ]


ROWS = [
    ("SUMMARY OF CHANGES MADE IN THE PSGC SINCE 2001",),
    ("January - March 2013 Updates",),
    HEADER,
    ("Davao Occidental, Region XI", "New province", "118600000", None, None),
    (
        "Municipality of Malita, Davao Occidental",
        "Transferred municipality",
        "118603000",
        "Davao del Sur",
        "112409000",
    ),
    ("July to September 2019",),
    (
        "Davao de Oro, Region XI",
        "Renaming",
        "118200000",
        "Compostela Valley",
        "118200000",
    ),
    ("May to June 2024",),
    (
        "Negros Occidental, Negros Island Region (NIR)",
        "Transferred province",
        NEG_OCC,
        "Region VI (Western Visayas)",
        "0604500000",
    ),
    # A row that gives the parent's code instead of its own must not make the
    # province inherit a city's history.
    (
        "City of Bacolod, Negros Island Region (NIR)",
        "Transferred city",
        NEG_OCC,
        "Region VII (Central Visayas)",
        "0730200000",
    ),
]


def test_codes_are_converted_to_ten_digits():
    assert to_ten_digits("118600000") == "1108600000"
    assert to_ten_digits(12801000) == "0102801000"  # stored as a number
    assert to_ten_digits("1906600000") == "1906600000"
    assert to_ten_digits(None) is None
    assert to_ten_digits("n/a") is None


def test_section_headers_date_the_rows_below():
    changes = parse_rows(ROWS)
    assert [change.effective for change in changes] == [
        date(2013, 1, 1),
        date(2013, 1, 1),
        date(2019, 7, 1),
        date(2024, 5, 1),
        date(2024, 5, 1),
    ]
    assert changes[1].old_code == "1102409000"


def test_second_half_of_a_division_inherits_the_old_name():
    changes = parse_rows(
        [
            ("July to September 2022",),
            (
                "Maguindanao del Norte, BARMM",
                "Division of province",
                "1908700000",
                "Maguindanao",
                "1903800000",
            ),
            ("Maguindanao del Sur, BARMM", "Division of province", "1908800000"),
        ]
    )
    assert [change.old_name for change in changes] == ["Maguindanao", "Maguindanao"]
    assert {change.old_code for change in changes} == {"1903800000"}


def test_history_has_old_names_codes_and_parents():
    history = derive_history(parse_rows(ROWS), entries(), released_on=date(2026, 1, 1))

    assert (DAVAO_DE_ORO, "Compostela Valley") in history.aliases
    assert {(former.code, former.parent_code) for former in history.former_parents} == {
        (MALITA, DAVAO_SUR),
        (NEG_OCC, R6),
    }
    crosswalk = {change.old_code: change.new_codes for change in history.crosswalk}
    assert crosswalk["1102409000"] == [MALITA]
    assert crosswalk["0604500000"] == [NEG_OCC]


def test_changes_after_the_release_are_ignored():
    history = derive_history(parse_rows(ROWS), entries(), released_on=date(2015, 1, 1))
    assert (DAVAO_DE_ORO, "Compostela Valley") not in history.aliases
    assert {former.code for former in history.former_parents} == {MALITA}


def test_read_changes_reads_every_sheet(tmp_path):
    workbook = Workbook()
    workbook.active.title = "2001-present"
    for row in ROWS:
        workbook.active.append(list(row))
    workbook.create_sheet("1977-2000").append(["August 1976 - July 1977 Updates"])
    path = tmp_path / "changes.xlsx"
    workbook.save(path)

    assert len(read_changes(path)) == 5


def test_resolver_accepts_a_former_parent():
    snapshot = PsgcSnapshot(version="test", released_on=date(2026, 1, 1))
    reference = ReferenceStore(
        snapshot,
        entries(),
        former_parents=[
            PsgcFormerParent(code=NEG_OCC, parent_code=R6, until=date(2024, 5, 1))
        ],
    )
    mention = Mention(
        hints=(
            Hint(kind="name", text="Region VI", level=GeoLevel.REGION),
            Hint(kind="name", text="Negros Occidental", level=GeoLevel.PROVINCE),
            Hint(kind="name", text="Bacolod City", level=GeoLevel.CITY_MUNICIPALITY),
        )
    )
    candidates = PathResolver(reference).resolve(mention)
    assert candidates[0].code == BACOLOD
    assert candidates[0].score == 1.0
