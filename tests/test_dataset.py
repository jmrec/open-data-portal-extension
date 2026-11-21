from __future__ import annotations

from open_data_portal_extension.dataset import ColumnDetector
from open_data_portal_extension.models.psgc import GeoLevel


def test_detects_levels_from_headers():
    detector = ColumnDetector()
    profile = detector.profile(
        [
            {
                "id": "1",
                "Region": "Region I",
                "Province": "Ilocos Norte",
                "City/Municipality": "Laoag",
                "Barangay": "Barangay I",
            }
        ],
        dataset_key="d",
    )

    levels = {mapping.column: mapping.level for mapping in profile.mappings}
    assert levels == {
        "Region": GeoLevel.REGION,
        "Province": GeoLevel.PROVINCE,
        "City/Municipality": GeoLevel.CITY_MUNICIPALITY,
        "Barangay": GeoLevel.BARANGAY,
    }
    assert profile.reported_level is GeoLevel.BARANGAY
    assert len(profile.place_columns) == 4


def test_locality_and_town_are_city_columns():
    for header in ("locality", "Town", "City/Town"):
        profile = ColumnDetector().profile(
            [{"province": "Sarangani", header: "Maitum"}],
            dataset_key="d",
        )
        levels = {mapping.column: mapping.level for mapping in profile.mappings}
        assert levels[header] is GeoLevel.CITY_MUNICIPALITY
        assert profile.reported_level is GeoLevel.CITY_MUNICIPALITY


def test_code_columns_are_not_name_columns():
    profile = ColumnDetector().profile(
        [{"psgc_code": "0128010000", "id": "1"}],
        dataset_key="d",
    )
    assert profile.mappings == []
    assert profile.reported_level is None


def test_values_infer_a_city_column():
    profile = ColumnDetector().profile(
        [
            {"place": "City of Laoag"},
            {"place": "City of Batac"},
            {"place": "City of Vigan"},
        ],
        dataset_key="d",
    )

    mapping = profile.mappings[0]
    assert mapping.level is GeoLevel.CITY_MUNICIPALITY
    assert mapping.source == "values"
    assert mapping.confidence == 0.6


def test_one_latitude_and_one_longitude_are_coordinates():
    profile = ColumnDetector().profile(
        [{"name": "x", "Lat": "17.5", "lng": "120.4"}], dataset_key="d"
    )
    assert profile.coordinates == ("Lat", "lng")
    assert profile.place_columns == []

    two = ColumnDetector().profile(
        [{"lat": "1", "latitude": "1", "lon": "2"}], dataset_key="d"
    )
    assert two.coordinates is None
