from __future__ import annotations

from datetime import date

from open_data_portal_extension.models.psgc import (
    GeoLevel,
    PsgcCrosswalk,
    PsgcEntry,
    PsgcSnapshot,
)

SNAPSHOT = PsgcSnapshot(version="2023-10-24", released_on=date(2023, 10, 24))
OLD_SNAPSHOT = PsgcSnapshot(version="2020-01-01", released_on=date(2020, 1, 1))

REGION_I = "0100000000"
REGION_II = "0200000000"
ILOCOS_NORTE = "0128000000"
ILOCOS_SUR = "0129000000"
LAOAG = "0128010000"
BATAC = "0128050000"
SAN_ISIDRO_NORTE = "0128060000"
VIGAN = "0129010000"
SAN_ISIDRO_SUR = "0129020000"
BARANGAY_I = "0129010010"
BARANGAY_SAN_ISIDRO = "0129010020"
OLD_LAOAG = "0128019000"


def make_entries() -> list[PsgcEntry]:
    return [
        PsgcEntry(
            code=REGION_I, name="Region I (Ilocos Region)", level=GeoLevel.REGION
        ),
        PsgcEntry(
            code=REGION_II, name="Region II (Cagayan Valley)", level=GeoLevel.REGION
        ),
        PsgcEntry(
            code=ILOCOS_NORTE,
            name="Province of Ilocos Norte",
            level=GeoLevel.PROVINCE,
            parent_code=REGION_I,
        ),
        PsgcEntry(
            code=ILOCOS_SUR,
            name="Province of Ilocos Sur",
            level=GeoLevel.PROVINCE,
            parent_code=REGION_I,
        ),
        PsgcEntry(
            code=LAOAG,
            name="City of Laoag",
            level=GeoLevel.CITY_MUNICIPALITY,
            parent_code=ILOCOS_NORTE,
        ),
        PsgcEntry(
            code=BATAC,
            name="City of Batac",
            level=GeoLevel.CITY_MUNICIPALITY,
            parent_code=ILOCOS_NORTE,
        ),
        PsgcEntry(
            code=SAN_ISIDRO_NORTE,
            name="San Isidro",
            level=GeoLevel.CITY_MUNICIPALITY,
            parent_code=ILOCOS_NORTE,
        ),
        PsgcEntry(
            code=VIGAN,
            name="City of Vigan",
            level=GeoLevel.CITY_MUNICIPALITY,
            parent_code=ILOCOS_SUR,
        ),
        PsgcEntry(
            code=SAN_ISIDRO_SUR,
            name="San Isidro",
            level=GeoLevel.CITY_MUNICIPALITY,
            parent_code=ILOCOS_SUR,
        ),
        PsgcEntry(
            code=BARANGAY_I,
            name="Barangay I (Pob.)",
            level=GeoLevel.BARANGAY,
            parent_code=VIGAN,
        ),
        PsgcEntry(
            code=BARANGAY_SAN_ISIDRO,
            name="Barangay San Isidro",
            level=GeoLevel.BARANGAY,
            parent_code=VIGAN,
        ),
    ]


def make_crosswalk() -> list[PsgcCrosswalk]:
    return [
        PsgcCrosswalk(
            old_code=OLD_LAOAG,
            new_codes=[LAOAG],
            change="merged",
            effective=date(2020, 1, 1),
        )
    ]
