"""Load `manifest.yml` into `DatasetSpec`s, validating every step."""

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ph_administrative_boundaries.types import DatasetSpec, Step

NAME = re.compile(r"[A-Za-z_]\w*")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
RESERVED = frozenset({"in", "out"})


class ManifestError(ValueError):
    pass


@dataclass
class YamlManifest:
    datasets: dict[str, DatasetSpec] = field(default_factory=dict)

    def load(self, path: Path) -> "YamlManifest":
        manifest_path = Path(path)
        config = yaml.safe_load(manifest_path.read_text()) or {}
        blocks = config.get("datasets") or {}
        if not isinstance(blocks, dict):
            raise ManifestError(f"{manifest_path}: 'datasets' must be a mapping")
        self.datasets = {
            name: _dataset(name, block, manifest_path.parent)
            for name, block in blocks.items()
        }
        _check_unique_outputs(self.datasets)
        return self

    def get(self, name: str) -> DatasetSpec:
        try:
            return self.datasets[name]
        except KeyError:
            known = ", ".join(sorted(self.datasets)) or "none"
            raise ManifestError(f"unknown dataset '{name}' (known: {known})") from None


def _dataset(name: str, block: Any, root: Path) -> DatasetSpec:
    if not isinstance(block, dict):
        raise ManifestError(f"dataset '{name}' must be a mapping")
    if "source" not in block:
        raise ManifestError(f"dataset '{name}' is missing 'source'")
    sources = _sources(name, block["source"], root / "data")
    return DatasetSpec(
        name=name,
        attribution=str(block.get("attribution", "")),
        sources=sources,
        steps=_steps(name, block.get("steps"), sources),
    )


def _sources(name: str, block: Any, data_root: Path) -> dict[str, Path]:
    if isinstance(block, str):
        entries: dict[Any, Any] = {"source": block}
    elif isinstance(block, dict) and block:
        entries = block
    else:
        raise ManifestError(
            f"dataset '{name}': 'source' must be a path or a mapping of names to paths"
        )
    resolved: dict[str, Path] = {}
    for key, value in entries.items():
        if not isinstance(key, str) or not NAME.fullmatch(key) or key in RESERVED:
            raise ManifestError(
                f"dataset '{name}': source name {key!r} must be a plain identifier, "
                "not 'in' or 'out'"
            )
        if not isinstance(value, str) or not value:
            raise ManifestError(f"dataset '{name}': source '{key}' must be a path")
        resolved[key] = _resolve_source(data_root, value)
    return resolved


def _resolve_source(data_root: Path, source: str) -> Path:
    declared = Path(source)
    if declared.is_absolute():
        return declared
    # Sources are read from `<manifest dir>/data` unless the declared path already
    # resolves from the manifest directory (e.g. `data/raw/boundaries.geojson`).
    unscoped = data_root.parent / declared
    return unscoped if unscoped.exists() else data_root / declared


def _steps(name: str, block: Any, sources: dict[str, Path]) -> tuple[Step, ...]:
    if not isinstance(block, list) or not block:
        raise ManifestError(f"dataset '{name}' needs a non-empty 'steps' list")
    readable = set(sources)  # names a step may read: sources, then earlier step ids
    ids: set[str] = set()
    written: dict[str, int] = {}  # intermediate file name -> step number
    steps: list[Step] = []
    for number, item in enumerate(block, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("run"), str):
            raise ManifestError(f"dataset '{name}': step {number} needs a 'run' string")
        run = item["run"].strip()
        try:
            tokens = shlex.split(run)
        except ValueError as exc:
            raise ManifestError(
                f"dataset '{name}': step {number} is malformed: {exc}"
            ) from None
        if not tokens:
            raise ManifestError(f"dataset '{name}': step {number} is empty")

        refs = set(PLACEHOLDER.findall(run))
        if "out" not in refs:
            raise ManifestError(f"dataset '{name}': step {number} must use {{out}}")
        reads = refs - {"out"}
        if not reads:
            raise ManifestError(
                f"dataset '{name}': step {number} must read {{in}} or a named input"
            )
        for ref in sorted(reads):
            if ref == "in":
                if number == 1 and len(sources) > 1:
                    raise ManifestError(
                        f"dataset '{name}': step 1 uses {{in}} but the dataset has "
                        f"several sources; name one of: {', '.join(sorted(sources))}"
                    )
            elif ref not in readable:
                raise ManifestError(
                    f"dataset '{name}': step {number} uses unknown name '{{{ref}}}'"
                )

        step_id = item.get("id")
        if step_id is not None:
            if (
                not isinstance(step_id, str)
                or not NAME.fullmatch(step_id)
                or step_id in RESERVED
                or step_id in sources
            ):
                raise ManifestError(
                    f"dataset '{name}': step {number} 'id' must be a plain identifier "
                    "that is not 'in', 'out' or a source name"
                )
            if step_id in ids:
                raise ManifestError(
                    f"dataset '{name}': step id '{step_id}' is used twice"
                )

        out = item.get("out")
        last = number == len(block)
        if out is None and last:
            raise ManifestError(
                f"dataset '{name}': the last step must set 'out' (the final file name)"
            )
        if out is not None and (not isinstance(out, str) or not out or "/" in out):
            raise ManifestError(
                f"dataset '{name}': step {number} 'out' must be a plain file name"
            )
        if not last:
            file_name = out or (
                f"{step_id}.geojson" if step_id else f"step{number}.geojson"
            )
            if file_name in written:
                raise ManifestError(
                    f"dataset '{name}': steps {written[file_name]} and {number} "
                    f"both write '{file_name}'"
                )
            written[file_name] = number

        steps.append(Step(run=run, out=out, id=step_id))
        if step_id is not None:
            ids.add(step_id)
            readable.add(step_id)
    return tuple(steps)


def _check_unique_outputs(datasets: dict[str, DatasetSpec]) -> None:
    owners: dict[str, str] = {}
    for spec in datasets.values():
        final = spec.steps[-1].out
        if final is None:
            raise ManifestError(f"dataset '{spec.name}' has no final output name")
        if final in owners:
            raise ManifestError(
                f"datasets '{owners[final]}' and '{spec.name}' both write '{final}'"
            )
        owners[final] = spec.name
