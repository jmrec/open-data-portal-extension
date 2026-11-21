import os
import threading
from datetime import date
from functools import lru_cache
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..dataset import ColumnDetector
from ..models.psgc import GeoLevel, PsgcEntry, PsgcSnapshot
from ..models.tagging import PlaceTag
from ..reference import ReferenceStore
from ..tagging import TaggingPipeline

app = FastAPI()


class TagRequest(BaseModel):
    dataset_key: str = Field(min_length=1)
    row_id: str = Field(min_length=1)
    row: dict[str, str]


def _demo_reference() -> ReferenceStore:
    region = "0100000000"
    province = "0128000000"
    return ReferenceStore(
        PsgcSnapshot(version="2023-10-24", released_on=date(2023, 10, 24)),
        [
            PsgcEntry(
                code=region,
                name="Region I (Ilocos Region)",
                level=GeoLevel.REGION,
            ),
            PsgcEntry(
                code=province,
                name="Province of Ilocos Norte",
                level=GeoLevel.PROVINCE,
                parent_code=region,
            ),
            PsgcEntry(
                code="0128010000",
                name="City of Laoag",
                level=GeoLevel.CITY_MUNICIPALITY,
                parent_code=province,
            ),
            PsgcEntry(
                code="0128050000",
                name="City of Batac",
                level=GeoLevel.CITY_MUNICIPALITY,
                parent_code=province,
            ),
        ],
    )


@lru_cache
def _pipeline() -> TaggingPipeline:
    """Tags against the database in PSGC_REFERENCE_DB, or a four-place demo set
    when it is unset. A path that does not exist is an error, not the demo."""
    path = os.environ.get("PSGC_REFERENCE_DB")
    if not path:
        return TaggingPipeline(_demo_reference())
    if not os.path.exists(path):
        raise HTTPException(
            status_code=503,
            detail=f"PSGC_REFERENCE_DB is {path}, which does not exist. "
            "Run `just build-reference` first.",
        )
    return TaggingPipeline(ReferenceStore.open(path))


_lock = threading.Lock()


@app.get("/")
def read_root() -> dict[str, str]:
    return {"Hello": "World"}


@app.get("/health")
def health() -> dict[str, str]:
    """``psgc_version`` says which reference is loaded, so the demo set shows."""
    return {"status": "ok", "psgc_version": _pipeline().reference.snapshot().version}


@app.post("/tag", response_model=PlaceTag)
def tag_row(
    request: Annotated[TagRequest, "A source row to match against the demo PSGC data"],
) -> PlaceTag:
    pipeline = _pipeline()
    profile = ColumnDetector().profile([request.row], dataset_key=request.dataset_key)
    with _lock:
        tag = pipeline.tag_row(
            profile,
            request.row,
            row_id=request.row_id,
        )
    if tag is None:
        raise HTTPException(
            status_code=422,
            detail="The row does not contain a recognized place column or PSGC code.",
        )
    return tag
