from __future__ import annotations

from open_data_portal_extension.normalization import normalize_header, normalize_name


def test_normalize_name_unifies_place_spellings():
    assert normalize_name("City of San Isidro") == "san isidro"
    assert normalize_name("SAN ISIDRO CITY") == "san isidro"
    assert normalize_name("Sto. Niño") == "santo nino"
    assert normalize_name("Brgy. San Isidro") == "san isidro"
    assert normalize_name("Region I (Ilocos Region)") == "1"
    assert normalize_name("Barangay I (Pob.)") == "1"
    assert normalize_name("   ") == ""


def test_normalize_header_keeps_place_words():
    assert normalize_header("City/Municipality") == "city municipality"
    assert normalize_header("PSGC_Code") == "psgc code"
    assert normalize_header("city_municipality") == "city municipality"


def test_country_name_is_dropped():
    assert normalize_name("Bataan Philippines") == "bataan"
    assert normalize_name("Philippines") == ""
