"""Export the PSGC parents the web app needs to walk up from a barangay.

PSGC codes are all 10 digits, so a code's level and parents can't be read
from its length. A barangay's city is usually its first seven digits padded
with zeros, but a highly urbanized city's province is not in its code (City
of Baguio is 1430300000, in Benguet, 1401100000), and Manila's barangays sit
under sub-municipalities. This writes the two lookups that cover both, and
checks every current barangay against the rules web/src/lib/psgc.ts applies.

    uv run python scripts/export_psgc_hierarchy.py data/psgc-v1.0.1.duckdb \
        web/src/data/psgc-hierarchy.json
"""

import json
import sys
from pathlib import Path

import duckdb


def main(reference: Path, out: Path) -> None:
    con = duckdb.connect(str(reference), read_only=True)
    current = "valid_to IS NULL"

    def pairs(level: str) -> dict[str, str]:
        rows = con.execute(
            f"SELECT code, parent_code FROM psgc_entries "
            f"WHERE level = ? AND {current} ORDER BY code",
            [level],
        ).fetchall()
        return dict(rows)

    province_of_city = pairs("city_municipality")
    city_of_sub_municipality = pairs("sub_municipality")
    provinces = {
        code
        for (code,) in con.execute(
            f"SELECT code FROM psgc_entries WHERE level = 'province' AND {current}"
        ).fetchall()
    }

    bad = [p for p in province_of_city.values() if p not in provinces]
    if bad:
        sys.exit(f"cities whose parent is not a province: {sorted(set(bad))[:5]}")

    barangays = con.execute(
        f"SELECT code, parent_code FROM psgc_entries "
        f"WHERE level = 'barangay' AND {current}"
    ).fetchall()
    for code, parent in barangays:
        if code.endswith("000"):
            sys.exit(f"barangay {code} ends in 000, so it reads as a city")
        prefix = code[:7] + "000"
        city = city_of_sub_municipality.get(prefix, prefix)
        expected = city_of_sub_municipality.get(parent, parent)
        if city != expected or city not in province_of_city:
            sys.exit(f"barangay {code}: derived city {city}, expected {expected}")

    out.write_text(
        json.dumps(
            {
                "provinceOfCity": province_of_city,
                "cityOfSubMunicipality": city_of_sub_municipality,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    print(
        f"{out}: {len(province_of_city)} cities, "
        f"{len(city_of_sub_municipality)} sub-municipalities, "
        f"checked {len(barangays)} barangays"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
