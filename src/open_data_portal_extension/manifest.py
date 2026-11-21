"""``manifest.toml``: the datasets to tag. Paths are relative to the manifest;
unknown keys are rejected so typos fail loudly.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models.psgc import GeoLevel
from .tabular import COLUMN_CHOICES

DEFAULT_MANIFEST = Path("manifest.toml")


class ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db: Path | None = None
    """Falls back to $PSGC_REFERENCE_DB, then the default."""


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baselines: Path = Path("evals/baselines")
    labels: Path = Path("evals/labels")


class DatasetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")

    source: str
    """A local file or an https URL."""

    output: Path | None = None
    """Defaults to ``data/output/<name>.csv``."""

    level: GeoLevel | None = None
    """Expected finest level; a coarser detection warns of a missed column."""

    columns: dict[str, str] = Field(default_factory=dict)

    eval: bool = False

    description: str | None = None
    attribution: str | None = None
    license: str | None = None
    url: str | None = None

    @field_validator("columns")
    @classmethod
    def _known_settings(cls, columns: dict[str, str]) -> dict[str, str]:
        bad = {
            name: value
            for name, value in columns.items()
            if value not in COLUMN_CHOICES
        }
        if bad:
            shown = ", ".join(f"{name} = {value!r}" for name, value in bad.items())
            raise ValueError(f"{shown}: use one of {', '.join(COLUMN_CHOICES)}")
        return columns

    @property
    def is_remote(self) -> bool:
        return self.source.startswith(("http://", "https://"))


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: ReferenceConfig = Field(default_factory=ReferenceConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)
    datasets: list[DatasetConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> Manifest:
        names = [dataset.name for dataset in self.datasets]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(f"dataset names must be unique: {', '.join(repeated)}")
        return self

    def select(self, names: list[str] | None = None) -> list[DatasetConfig]:
        if not names:
            return list(self.datasets)
        known = {dataset.name for dataset in self.datasets}
        unknown = [name for name in names if name not in known]
        if unknown:
            raise ValueError(
                f"not in the manifest: {', '.join(unknown)} "
                f"(known: {', '.join(sorted(known)) or 'none'})"
            )
        return [dataset for dataset in self.datasets if dataset.name in names]


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Manifest:
    with path.open("rb") as handle:
        manifest = Manifest.model_validate(tomllib.load(handle))

    root = path.resolve().parent
    if manifest.reference.db is not None:
        manifest.reference.db = _under(root, manifest.reference.db)
    manifest.eval.baselines = _under(root, manifest.eval.baselines)
    manifest.eval.labels = _under(root, manifest.eval.labels)
    for dataset in manifest.datasets:
        if not dataset.is_remote:
            dataset.source = str(_under(root, Path(dataset.source)))
        dataset.output = _under(
            root, dataset.output or Path("data/output") / f"{dataset.name}.csv"
        )
    return manifest


def _under(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path
