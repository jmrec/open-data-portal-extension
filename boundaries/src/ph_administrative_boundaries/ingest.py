import hashlib
import json
from dataclasses import dataclass
from glob import glob, has_magic
from pathlib import Path
from typing import Any

from ph_administrative_boundaries.types import Artifact, DatasetSpec

_CHUNK_SIZE = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class LocalDataIngestor:
    workspace: Path = Path(".cache/build")

    def ingest(self, spec: DatasetSpec) -> dict[str, Artifact]:
        """One artifact per named source, in declaration order."""
        return {
            key: self._ingest_one(spec, key, path) for key, path in spec.sources.items()
        }

    def merged_path(self, spec: DatasetSpec, key: str) -> Path:
        return self.workspace / "raw" / spec.name / f"{key}.geojson"

    def _ingest_one(self, spec: DatasetSpec, key: str, path: Path) -> Artifact:
        if has_magic(str(path)):
            matches = [Path(p) for p in glob(str(path))]
            if not matches:
                raise FileNotFoundError(
                    f"dataset '{spec.name}' source '{key}' matched no files: {path}"
                )
            merged = self.merged_path(spec, key)
            merged.parent.mkdir(parents=True, exist_ok=True)
            merged.write_text(json.dumps(_combine(sorted(matches))))
            return Artifact(path=merged, sha256=sha256_file(merged))
        if not path.is_file():
            raise FileNotFoundError(
                f"dataset '{spec.name}' source '{key}' is missing: {path}"
            )
        return Artifact(path=path, sha256=sha256_file(path))


def _combine(sources: list[Path]) -> dict[str, Any]:
    features: list[Any] = []
    for source in sources:
        features.extend(json.loads(source.read_text())["features"])
    return {"type": "FeatureCollection", "features": features}
