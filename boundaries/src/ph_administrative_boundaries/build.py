"""Run each dataset's steps in order, skipping any step whose inputs are unchanged."""

import codecs
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import structlog

from ph_administrative_boundaries.ingest import LocalDataIngestor, sha256_file
from ph_administrative_boundaries.manifest import PLACEHOLDER, YamlManifest
from ph_administrative_boundaries.types import Artifact, DatasetSpec, Step

log = structlog.get_logger()


class ToolError(RuntimeError):
    pass


class StepError(RuntimeError):
    pass


class Runner(Protocol):
    def run(self, argv: list[str], *, stream: bool = False) -> str: ...


class SubprocessRunner:
    """Run a tool, either capturing its output or logging it line by line."""

    def run(self, argv: list[str], *, stream: bool = False) -> str:
        if stream:
            return self._stream(argv)
        try:
            result = subprocess.run(argv, check=False, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise ToolError(f"{argv[0]} is not installed or not on PATH") from exc
        if result.returncode != 0:
            raise ToolError(
                f"{argv[0]} exited with {result.returncode}: {result.stderr.strip()}"
            )
        return result.stdout or result.stderr

    def _stream(self, argv: list[str]) -> str:
        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        except FileNotFoundError as exc:
            raise ToolError(f"{argv[0]} is not installed or not on PATH") from exc
        assert proc.stdout is not None
        tool = Path(argv[0]).name
        tail: deque[str] = deque(maxlen=20)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""

        def emit(raw: str) -> None:
            line = raw.rsplit("\r", 1)[-1].rstrip()
            if line:
                tail.append(line)
                log.info("tool_output", tool=tool, line=line)

        with proc.stdout as out:
            for chunk in iter(lambda: os.read(out.fileno(), 4096), b""):
                pending += decoder.decode(chunk)
                *lines, pending = pending.split("\n")
                for line in lines:
                    emit(line)
            emit(pending + decoder.decode(b"", final=True))
        returncode = proc.wait()
        if returncode != 0:
            last = tail[-1] if tail else ""
            raise ToolError(f"{tool} exited with {returncode}: {last}")
        return "\n".join(tail)


def render(run: str, paths: Mapping[str, Path]) -> list[str]:
    """Split a step into argv, replacing each `{name}` token by token.

    `paths` maps every name the step uses, including "out", to a path.
    Splitting first keeps a path with spaces in one argument.
    """

    def substitute(match: re.Match[str]) -> str:
        return str(paths[match.group(1)])

    return [PLACEHOLDER.sub(substitute, token) for token in shlex.split(run)]


def fingerprint(*parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class JsonCache:
    path: Path
    entries: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path.exists():
            self.entries = json.loads(self.path.read_text() or "{}")

    def is_fresh(self, key: str, out: Path) -> bool:
        recorded = self.entries.get(key)
        if recorded is None or not out.exists():
            return False
        return recorded == sha256_file(out)

    def record(self, key: str, out: Path) -> None:
        self.entries[key] = sha256_file(out)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_suffix(".tmp")
        partial.write_text(json.dumps(self.entries, indent=2, sort_keys=True))
        partial.replace(self.path)


@dataclass
class BuildPipeline:
    manifest: YamlManifest
    ingestor: LocalDataIngestor
    runner: Runner
    cache: JsonCache
    workspace: Path
    output_dir: Path
    keep_intermediates: bool = False
    stream: bool = False

    def build(self, name: str) -> list[Artifact]:
        started = time.monotonic()
        spec = self.manifest.get(name)
        with structlog.contextvars.bound_contextvars(dataset=spec.name):
            log.info("build_started", steps=len(spec.steps))
            sources = self.ingestor.ingest(spec)
            final = self._run_steps(spec, sources)
            log.info(
                "build_finished",
                out=str(final.path),
                sha256=final.sha256,
                duration_s=round(time.monotonic() - started, 2),
            )
        # Merged glob copies are scratch space; declared files are never removed.
        if not self.keep_intermediates:
            for key, artifact in sources.items():
                if artifact.path != spec.sources[key]:
                    artifact.path.unlink(missing_ok=True)
        return [final]

    def _run_steps(self, spec: DatasetSpec, sources: dict[str, Artifact]) -> Artifact:
        names: dict[str, Artifact] = dict(sources)
        # `{in}` is the sole source for the first step, then the previous output.
        # Validation rejects `{in}` on the first step when there are several sources.
        current = next(iter(sources.values()))
        for index, step in enumerate(spec.steps, start=1):
            reads = set(PLACEHOLDER.findall(step.run)) - {"out"}
            inputs: dict[str, Artifact] = {
                name: names[name] for name in reads if name != "in"
            }
            if "in" in reads:
                inputs["in"] = current
            current = self._run_step(spec, index, step, inputs)
            if step.id is not None:
                names[step.id] = current
        return current

    def _run_step(
        self,
        spec: DatasetSpec,
        index: int,
        step: Step,
        inputs: dict[str, Artifact],
    ) -> Artifact:
        dest = self._destination(spec, index, step)
        key = fingerprint(
            "step",
            spec.name,
            index,
            step.run,
            step.out,
            sorted((name, art.sha256) for name, art in inputs.items()),
            self._tool_version(step),
        )
        context = {"step": index, "step_id": step.id}
        with structlog.contextvars.bound_contextvars(**context):
            if self.cache.is_fresh(key, dest):
                log.info("step_cached", out=str(dest))
            else:
                self._execute(spec, index, step, inputs, dest, key)
        return Artifact(dest, sha256_file(dest))

    def _execute(
        self,
        spec: DatasetSpec,
        index: int,
        step: Step,
        inputs: dict[str, Artifact],
        dest: Path,
        key: str,
    ) -> None:
        started = time.monotonic()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)
        paths = {name: art.path for name, art in inputs.items()}
        paths["out"] = dest
        argv = render(step.run, paths)
        log.info(
            "step_started",
            steps=len(spec.steps),
            tool=argv[0],
            command=shlex.join(argv),
        )
        self.runner.run(argv, stream=self.stream)
        if not dest.is_file():
            raise StepError(f"'{spec.name}' step {index} wrote no file to {dest}")
        self.cache.record(key, dest)
        log.info(
            "step_finished",
            out=str(dest),
            size_bytes=dest.stat().st_size,
            duration_s=round(time.monotonic() - started, 2),
        )

    def _destination(self, spec: DatasetSpec, index: int, step: Step) -> Path:
        if index == len(spec.steps):
            return self.output_dir / (step.out or "")
        default = f"{step.id}.geojson" if step.id else f"step{index}.geojson"
        return self.workspace / "steps" / spec.name / (step.out or default)

    def _tool_version(self, step: Step) -> str:
        """Best-effort version of the step's tool, part of its cache key.

        Tools that have no `--version` still work; they just don't invalidate
        the cache when upgraded.
        """
        tool = shlex.split(step.run)[0]
        try:
            return self.runner.run([tool, "--version"]).strip()
        except ToolError:
            return "unknown"
