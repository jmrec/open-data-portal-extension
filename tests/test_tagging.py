from __future__ import annotations

from datetime import date

from open_data_portal_extension.dataset import ColumnDetector
from open_data_portal_extension.mentions import extract_mention
from open_data_portal_extension.models.mention import Hint
from open_data_portal_extension.models.psgc import GeoLevel, PsgcEntry, PsgcSnapshot
from open_data_portal_extension.models.tagging import (
    MatchCandidate,
    MatchMethod,
    PlaceTag,
    TagStatus,
)
from open_data_portal_extension.reference import ReferenceStore
from open_data_portal_extension.resolution import PathResolver
from open_data_portal_extension.tagging import TaggingPipeline
from tests.catalog import (
    LAOAG,
    OLD_LAOAG,
    SAN_ISIDRO_NORTE,
    SAN_ISIDRO_SUR,
    VIGAN,
)


def _profile(rows):
    return ColumnDetector().profile(rows, dataset_key="d")


def _tag_all(pipeline, rows):
    profile = _profile(rows)
    return [pipeline.tag_row(profile, row, row_id=str(i)) for i, row in enumerate(rows)]


def _resolve(reference, row):
    mention = extract_mention(_profile([row]), row)
    return PathResolver(reference).resolve(mention)


def test_mention_reads_columns_codes_and_free_text():
    rows = [
        {
            "Province": "Ilocos Norte",
            "City": "Laoag",
            "Location": "Poblacion, Laoag",
            "psgc": LAOAG,
        }
    ]
    mention = extract_mention(_profile(rows), rows[0])
    assert mention.hints == (
        Hint(kind="name", text="Ilocos Norte", level=GeoLevel.PROVINCE),
        Hint(kind="name", text="Laoag", level=GeoLevel.CITY_MUNICIPALITY),
        Hint(kind="name", text="Poblacion"),
        Hint(kind="name", text="Laoag"),
        Hint(kind="code", text=LAOAG),
    )
    assert mention.target_level is None


def test_resolver_matches_within_parent(reference):
    candidates = _resolve(reference, {"Province": "Ilocos Norte", "City": "San Isidro"})
    assert candidates[0].code == SAN_ISIDRO_NORTE
    assert candidates[0].method is MatchMethod.NAME_EXACT
    assert candidates[0].score == 1.0

    # The other San Isidro is only half explained by this row.
    assert candidates[1].code == SAN_ISIDRO_SUR
    assert candidates[1].score == 0.5


def test_resolver_falls_back_to_fuzzy_inside_the_parent(reference):
    candidates = _resolve(reference, {"Province": "Ilocos Norte", "City": "Laoagg"})
    assert candidates[0].code == LAOAG
    assert candidates[0].method is MatchMethod.NAME_FUZZY


def test_resolver_follows_the_crosswalk_for_old_codes(reference):
    candidates = _resolve(reference, {"psgc_code": OLD_LAOAG})
    assert [c.code for c in candidates] == [LAOAG]
    assert candidates[0].method is MatchMethod.EXISTING_CODE


def test_a_code_that_disagrees_with_the_names_scores_lower(reference):
    row = {"Province": "Ilocos Norte", "City": "Laoag", "psgc_code": VIGAN}
    candidates = _resolve(reference, row)
    assert candidates[0].code == LAOAG
    assert candidates[0].score < 1.0


def _bataan_reference():
    """Two places named Bataan, as in the real data, plus Bagac and Saysain."""
    snapshot = PsgcSnapshot(version="t", released_on=date(2026, 1, 1))
    entries = [
        ("0300000000", "Region III (Central Luzon)", "region", None),
        ("0400000000", "Region IV-A (CALABARZON)", "region", None),
        ("0300800000", "Bataan", "province", "0300000000"),
        ("0401000000", "Batangas", "province", "0400000000"),
        ("0300802000", "Bagac", "city_municipality", "0300800000"),
        ("0401023000", "San Juan", "city_municipality", "0401000000"),
        ("0300802014", "Saysain", "barangay", "0300802000"),
        ("0401023004", "Bataan", "barangay", "0401023000"),
    ]
    return ReferenceStore(
        snapshot,
        [
            PsgcEntry(code=c, name=n, level=GeoLevel(lv), parent_code=p)
            for c, n, lv, p in entries
        ],
    )


def test_free_text_picks_the_chain_that_explains_every_word():
    reference = _bataan_reference()
    pipeline = TaggingPipeline(reference)
    rows = [
        {"Location": "Saysain, Bagac, Bataan"},
        {"Location": "Bagac, Bataan"},
        {"Location": "Bataan"},
        {"Location": "Unknown Village, Bataan"},
    ]
    assert _profile(rows).free_text_columns == ["Location"]

    tags = _tag_all(pipeline, rows)

    # The barangay named Bataan in Region IV-A explains one word of three.
    assert (tags[0].status, tags[0].code) == (TagStatus.AUTO, "0300802014")
    assert (tags[1].status, tags[1].code) == (TagStatus.AUTO, "0300802000")

    # A bare "Bataan" is the province, the coarsest place with that name.
    assert (tags[2].status, tags[2].code) == (TagStatus.AUTO, "0300800000")

    # Half the words match nothing, so a person should look.
    assert tags[3].status is TagStatus.NEEDS_REVIEW
    assert tags[3].confidence == 0.5


def test_identical_mentions_are_resolved_once(reference):
    pipeline = TaggingPipeline(reference)
    calls = []
    original = pipeline._resolver.resolve
    pipeline._resolver.resolve = lambda mention: (
        calls.append(mention) or original(mention)
    )
    rows = [{"City": "Laoag"}] * 3 + [{"City": "Batac"}]
    _tag_all(pipeline, rows)
    assert len(calls) == 2


def test_pipeline_auto_accepts_a_unique_exact_match(reference):
    profile = ColumnDetector().profile(
        [{"Province": "Ilocos Norte", "City/Municipality": "Laoag"}],
        dataset_key="d",
    )

    tag = TaggingPipeline(reference).tag_row(
        profile,
        {"Province": "Ilocos Norte", "City/Municipality": "Laoag"},
        row_id="1",
    )

    assert tag is not None
    assert tag.status is TagStatus.AUTO
    assert tag.code == LAOAG
    assert tag.method is MatchMethod.NAME_EXACT
    assert tag.confidence == 1.0


def test_pipeline_sends_ambiguous_names_to_review(reference):
    profile = ColumnDetector().profile(
        [{"City": "San Isidro"}],
        dataset_key="d",
    )

    tag = TaggingPipeline(reference).tag_row(
        profile,
        {"City": "San Isidro"},
        row_id="1",
    )

    assert tag is not None
    assert tag.status is TagStatus.NEEDS_REVIEW
    assert tag.code is None
    assert {candidate.code for candidate in tag.candidates} == {
        SAN_ISIDRO_NORTE,
        SAN_ISIDRO_SUR,
    }


def test_pipeline_uses_existing_codes_without_name_columns(reference):
    profile = ColumnDetector().profile(
        [{"psgc_code": VIGAN}],
        dataset_key="d",
    )

    tag = TaggingPipeline(reference).tag_row(profile, {"psgc_code": VIGAN}, row_id="1")

    assert tag is not None
    assert tag.level is GeoLevel.CITY_MUNICIPALITY
    assert tag.status is TagStatus.AUTO
    assert tag.code == VIGAN
    assert tag.method is MatchMethod.EXISTING_CODE


def test_pipeline_skips_rows_without_place_columns(reference):
    profile = ColumnDetector().profile([{"id": "1"}], dataset_key="d")

    assert TaggingPipeline(reference).tag_row(profile, {"id": "1"}, row_id="1") is None


def test_scores_are_rounded_only_in_output():
    tag = PlaceTag(
        dataset_key="d",
        row_id="1",
        level=GeoLevel.CITY_MUNICIPALITY,
        code=LAOAG,
        status=TagStatus.AUTO,
        confidence=0.9545454545454546,
        candidates=[
            MatchCandidate(
                code=LAOAG,
                level=GeoLevel.CITY_MUNICIPALITY,
                score=0.9545454545454546,
                method=MatchMethod.NAME_FUZZY,
            )
        ],
        psgc_version="t",
    )
    assert tag.confidence == 0.9545454545454546
    dumped = tag.model_dump(mode="json")
    assert dumped["confidence"] == 0.955
    assert dumped["candidates"][0]["score"] == 0.955
