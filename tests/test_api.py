from fastapi.testclient import TestClient

from open_data_portal_extension.api import main
from open_data_portal_extension.api.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    # No PSGC_REFERENCE_DB: the demo set, and /health says so.
    assert response.json() == {"status": "ok", "psgc_version": "2023-10-24"}


def test_tag_endpoint_returns_an_automatic_match() -> None:
    response = client.post(
        "/tag",
        json={
            "dataset_key": "demo",
            "row_id": "1",
            "row": {"City/Municipality": "Laoag"},
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == "0128010000"
    assert response.json()["status"] == "auto"


def test_tag_endpoint_returns_review_for_unknown_name() -> None:
    response = client.post(
        "/tag",
        json={
            "dataset_key": "demo",
            "row_id": "1",
            "row": {"City/Municipality": "Unknown"},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"
    assert response.json()["code"] is None


def test_a_missing_reference_database_is_an_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PSGC_REFERENCE_DB", str(tmp_path / "missing.duckdb"))
    main._pipeline.cache_clear()
    try:
        response = client.post(
            "/tag",
            json={"dataset_key": "d", "row_id": "1", "row": {"City": "Laoag"}},
        )
    finally:
        main._pipeline.cache_clear()
    assert response.status_code == 503
    assert "does not exist" in response.json()["detail"]
