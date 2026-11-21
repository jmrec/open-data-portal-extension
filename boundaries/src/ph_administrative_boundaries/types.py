"""Plain data describing what a dataset build produces."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Step:
    """One external command.

    `run` must use `{out}` and read at least one input: `{in}` (the previous
    step's output, or the sole source for the first step), a source name, or
    the `id` of an earlier step. `out` names the file; `id` names this step's
    output for later steps.
    """

    run: str
    out: str | None = None
    id: str | None = None


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    attribution: str
    sources: dict[str, Path]
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Artifact:
    path: Path
    sha256: str
