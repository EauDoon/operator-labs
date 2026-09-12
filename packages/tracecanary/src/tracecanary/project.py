"""Explicit, portable local project manifests for synthetic investigations.

A project stores only user-chosen settings: the contract, synthetic input
references, baseline and candidate selections, coverage thresholds, and
batch configuration. Result evidence stays out of the manifest; reopening a
project never implies that a previous report describes inputs that have
since changed. Relative paths resolve against the project directory so a
self-contained directory stays portable, and every referenced input records
a SHA-256 fingerprint at save time so opening can report missing or
modified files honestly.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from tracecanary.canonical import InputError, canonical_json, load_json
from tracecanary.contract import DEFAULT_MAX_BATCH_FILES, DEFAULT_MAX_INPUT_BYTES, DEFAULT_MAX_NESTING
from tracecanary.inspection import _parse_minimum_ratio
from tracecanary.output import write_report

PROJECT_MANIFEST_VERSION = "tracecanary.project/v1"
PROJECT_MANIFEST_NAME = "tracecanary.project.json"
MAX_PROJECT_INPUTS = 64
MAX_DESCRIPTION_CHARS = 200
POPULATION_SCOPES = ("resource", "scope", "span", "event", "link")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*")


@dataclass(frozen=True)
class InputRef:
    path: str
    sha256: str


@dataclass(frozen=True)
class BatchConfig:
    path: str
    sha256: str
    recursive: bool
    include_paths: bool
    minimum_ratio: str | None


@dataclass(frozen=True)
class CoverageConfig:
    minimum_ratio: str | None
    population_scope: str | None
    population_minimum: int | None


@dataclass(frozen=True)
class ProjectManifest:
    project_id: str
    description: str
    contract: InputRef
    input: InputRef | None
    baseline: InputRef | None
    candidate: InputRef | None
    batch: BatchConfig | None
    coverage: CoverageConfig


@dataclass(frozen=True)
class LoadedProject:
    path: Path
    manifest: ProjectManifest
    resolved: dict[str, Path]
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def fingerprint_file(path: Path, *, max_bytes: int) -> str:
    """Hash a bounded synthetic input file without following links."""
    raw = path.read_bytes() if path.stat().st_size <= max_bytes else None
    if raw is None:
        raise InputError(f"project input exceeds the {max_bytes}-byte fingerprint budget: {path}")
    return hashlib.sha256(raw).hexdigest()


def fingerprint_tree(path: Path, *, max_files: int, max_bytes: int) -> str:
    """Deterministically hash a bounded folder of JSON synthetic exports."""
    files: list[tuple[str, str]] = []
    for item in sorted(path.iterdir(), key=lambda child: child.name):
        try:
            metadata = item.lstat()
        except OSError as exc:
            raise InputError(f"project input folder could not be read: {path}") from exc
        if not stat_module.S_ISREG(metadata.st_mode) or not item.name.lower().endswith(".json"):
            continue
        files.append((item.name, fingerprint_file(item, max_bytes=max_bytes)))
        if len(files) > max_files:
            raise InputError(f"project input folder exceeds the {max_files}-file fingerprint budget: {path}")
    if not files:
        raise InputError(f"project input folder contains no JSON files: {path}")
    digest = hashlib.sha256()
    for name, content_hash in files:
        digest.update(name.encode("utf-8"))
        digest.update(content_hash.encode("utf-8"))
    return digest.hexdigest()


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 64 or _IDENTIFIER.fullmatch(value) is None:
        raise InputError(f"{field} must be a stable identifier using letters, numbers, dot, underscore, colon, slash, or hyphen")
    return value


def _validate_relative_path(text: str, field: str) -> str:
    posix = PurePosixPath(text)
    if Path(text).is_absolute() or posix.is_absolute() or text.startswith("~"):
        raise InputError(f"{field} must be a relative project path: {text}")
    if "\\" in text or any(part == ".." for part in posix.parts) or not posix.parts:
        raise InputError(f"{field} must use forward slashes and stay inside the project: {text}")
    return text


def _parse_input_ref(value: Any, field: str) -> InputRef:
    if not isinstance(value, dict):
        raise InputError(f"{field} must be an object")
    unknown = value.keys() - {"path", "sha256"}
    missing = {"path", "sha256"} - value.keys()
    if unknown or missing:
        raise InputError(f"{field} has unsupported or missing fields: {', '.join(sorted(unknown | missing))}")
    path = _validate_relative_path(value["path"], f"{field}.path")
    digest = value["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise InputError(f"{field}.sha256 must be a 64-character lowercase SHA-256 digest")
    return InputRef(path=path, sha256=digest)


def _parse_batch(value: Any, field: str) -> BatchConfig:
    if not isinstance(value, dict):
        raise InputError(f"{field} must be an object")
    unknown = value.keys() - {"path", "sha256", "recursive", "include_paths", "minimum_ratio"}
    required = {"path", "sha256", "recursive", "include_paths"}
    missing = required - value.keys()
    if unknown or missing:
        raise InputError(f"{field} has unsupported or missing fields: {', '.join(sorted(unknown | missing))}")
    path = _validate_relative_path(value["path"], f"{field}.path")
    digest = value["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise InputError(f"{field}.sha256 must be a 64-character lowercase SHA-256 digest")
    for flag in ("recursive", "include_paths"):
        if type(value[flag]) is not bool:
            raise InputError(f"{field}.{flag} must be a boolean")
    minimum_ratio = value.get("minimum_ratio")
    if minimum_ratio is not None:
        minimum_ratio = str(minimum_ratio)
        _parse_minimum_ratio(minimum_ratio)
    return BatchConfig(path=path, sha256=digest, recursive=value["recursive"],
                       include_paths=value["include_paths"], minimum_ratio=minimum_ratio)


def _parse_coverage(value: Any) -> CoverageConfig:
    if not isinstance(value, dict):
        raise InputError("coverage must be an object")
    unknown = value.keys() - {"minimum_ratio", "population_scope", "population_minimum"}
    if unknown:
        raise InputError(f"coverage has unsupported fields: {', '.join(sorted(unknown))}")
    minimum_ratio = value.get("minimum_ratio")
    if minimum_ratio is not None:
        minimum_ratio = str(minimum_ratio)
        _parse_minimum_ratio(minimum_ratio)
    scope = value.get("population_scope")
    minimum = value.get("population_minimum")
    if scope is not None:
        scope = str(scope)
        if scope not in POPULATION_SCOPES:
            raise InputError("coverage.population_scope must be one of " + ", ".join(POPULATION_SCOPES))
        if type(minimum) is not int or not 1 <= minimum <= 1_000_000:
            raise InputError("coverage.population_minimum must be a whole number from 1 to 1000000")
    elif minimum is not None:
        raise InputError("coverage.population_minimum requires coverage.population_scope")
    return CoverageConfig(minimum_ratio=minimum_ratio, population_scope=scope, population_minimum=minimum)


def parse_manifest(value: Any) -> ProjectManifest:
    """Parse and validate a strict tracecanary project manifest."""
    if not isinstance(value, dict):
        raise InputError("project manifest must be an object")
    unknown = value.keys() - {
        "project_version", "project_id", "description", "contract", "input",
        "baseline", "candidate", "batch", "coverage",
    }
    missing = {"project_version", "project_id", "contract"} - value.keys()
    if unknown or missing:
        raise InputError(f"project manifest has unsupported or missing fields: {', '.join(sorted(unknown | missing))}")
    if value["project_version"] != PROJECT_MANIFEST_VERSION:
        raise InputError(f"unsupported project manifest version: {value['project_version']}")
    project_id = _identifier(value["project_id"], "project manifest.project_id")
    description = ""
    if "description" in value:
        if not isinstance(value["description"], str) or len(value["description"]) > 200:
            raise InputError("project manifest.description must be a string of at most 200 characters")
        description = value["description"]
    contract = _parse_input_ref(value["contract"], "contract")
    input_ref = _parse_input_ref(value["input"], "input") if "input" in value else None
    baseline = _parse_input_ref(value["baseline"], "baseline") if "baseline" in value else None
    candidate = _parse_input_ref(value["candidate"], "candidate") if "candidate" in value else None
    batch = _parse_batch(value["batch"], "batch") if "batch" in value else None
    coverage = _parse_coverage(value["coverage"]) if "coverage" in value else CoverageConfig(None, None, None)
    if "coverage" in value and coverage.minimum_ratio is None and coverage.population_scope is None:
        raise InputError("coverage must name at least one threshold")
    return ProjectManifest(
        project_id=project_id,
        description=description,
        contract=contract,
        input=input_ref,
        baseline=baseline,
        candidate=candidate,
        batch=batch,
        coverage=coverage,
    )


def load_project(path: str | Path, *, max_bytes: int = DEFAULT_MAX_INPUT_BYTES, max_depth: int = DEFAULT_MAX_NESTING, max_batch_files: int = DEFAULT_MAX_BATCH_FILES) -> LoadedProject:
    """Read, resolve, and status a project from its manifest file or directory."""
    location = Path(path)
    manifest_path = location / PROJECT_MANIFEST_NAME if location.is_dir() else location
    project_dir = manifest_path.parent
    manifest = parse_manifest(load_json(manifest_path, max_bytes=max_bytes, max_depth=max_depth))
    resolved: dict[str, Path] = {}
    problems: list[str] = []

    def resolve(ref: InputRef, label: str, *, folder: bool = False, max_files: int = max_batch_files) -> None:
        target = project_dir / ref.path
        try:
            metadata = target.lstat()
        except OSError:
            problems.append(f"{label}: missing input {ref.path}")
            return
        if folder:
            if not stat_module.S_ISDIR(metadata.st_mode):
                problems.append(f"{label}: {ref.path} is no longer a folder")
                return
            try:
                current = fingerprint_tree(target, max_files=max_files, max_bytes=max_bytes)
            except InputError as exc:
                problems.append(f"{label}: {exc}")
                return
        else:
            if not stat_module.S_ISREG(metadata.st_mode):
                problems.append(f"{label}: {ref.path} is no longer a regular file")
                return
            try:
                current = fingerprint_file(target, max_bytes=max_bytes)
            except InputError as exc:
                problems.append(f"{label}: {exc}")
                return
        if current != ref.sha256:
            problems.append(f"{label}: {ref.path} changed since the project was saved")
            return
        resolved[label] = target

    resolve(manifest.contract, "contract")
    if manifest.input is not None:
        resolve(manifest.input, "input")
    if manifest.baseline is not None:
        resolve(manifest.baseline, "baseline")
    if manifest.candidate is not None:
        resolve(manifest.candidate, "candidate")
    if manifest.batch is not None:
        resolve(InputRef(path=manifest.batch.path, sha256=manifest.batch.sha256), "batch directory", folder=True)
    return LoadedProject(path=manifest_path, manifest=manifest, resolved=resolved, problems=tuple(problems))


def manifest_document(manifest: ProjectManifest) -> dict[str, Any]:
    def ref_document(ref: InputRef) -> dict[str, Any]:
        return {"path": ref.path, "sha256": ref.sha256}

    document: dict[str, Any] = {
        "project_version": PROJECT_MANIFEST_VERSION,
        "project_id": manifest.project_id,
        "contract": ref_document(manifest.contract),
    }
    if manifest.description:
        document["description"] = manifest.description
    if manifest.input is not None:
        document["input"] = ref_document(manifest.input)
    if manifest.baseline is not None:
        document["baseline"] = ref_document(manifest.baseline)
    if manifest.candidate is not None:
        document["candidate"] = ref_document(manifest.candidate)
    if manifest.batch is not None:
        document["batch"] = {
            "path": manifest.batch.path,
            "sha256": manifest.batch.sha256,
            "recursive": manifest.batch.recursive,
            "include_paths": manifest.batch.include_paths,
            "minimum_ratio": manifest.batch.minimum_ratio,
        }
    if manifest.coverage.minimum_ratio is not None or manifest.coverage.population_scope is not None:
        document["coverage"] = {
            "minimum_ratio": manifest.coverage.minimum_ratio,
            "population_scope": manifest.coverage.population_scope,
            "population_minimum": manifest.coverage.population_minimum,
        }
    return document


def manifest_text(manifest: ProjectManifest) -> str:
    return canonical_json(manifest_document(manifest))


def make_input_ref(project_dir: Path, source: Path, *, folder: bool = False, max_files: int = DEFAULT_MAX_BATCH_FILES, max_bytes: int = DEFAULT_MAX_INPUT_BYTES) -> InputRef:
    resolved = Path(source).resolve()
    if folder:
        if not resolved.is_dir():
            raise InputError(f"project batch directory is not a folder: {source}")
        digest = fingerprint_tree(resolved, max_files=max_files, max_bytes=max_bytes)
    else:
        if not resolved.is_file():
            raise InputError(f"project input is not a readable file: {source}")
        digest = fingerprint_file(resolved, max_bytes=max_bytes)
    try:
        relative = resolved.relative_to(project_dir.resolve())
    except ValueError as exc:
        raise InputError(
            f"project inputs must live inside the project directory so the project stays portable: {source}"
        ) from exc
    if any(part == ".." for part in relative.parts):
        raise InputError(f"project input paths must not traverse upwards: {source}")
    return InputRef(path=relative.as_posix(), sha256=digest)


def _copy_project_input(project_dir: Path, source: Path, *, folder: bool = False) -> Path:
    """Copy one chosen synthetic input into the project, or use it in place."""
    resolved = Path(source).resolve()
    if resolved.is_dir() and not folder:
        raise InputError(f"project input must be a file, not a directory: {source}")
    if not resolved.is_file() and not resolved.is_dir():
        raise InputError(f"project input is not readable: {source}")
    try:
        resolved.relative_to(project_dir)
        return resolved
    except ValueError:
        pass
    inputs_dir = project_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    target = inputs_dir / resolved.name
    if target.exists():
        raise InputError(f"project input already exists: {target}")
    if folder:
        if not resolved.is_dir():
            raise InputError(f"project batch directory is not a folder: {source}")
        target.mkdir()
        copied = 0
        for item in sorted(resolved.iterdir(), key=lambda child: child.name):
            try:
                metadata = item.lstat()
            except OSError as exc:
                raise InputError(f"batch directory could not be read: {source}") from exc
            if not stat_module.S_ISREG(metadata.st_mode) or not item.name.lower().endswith(".json"):
                continue
            shutil.copyfile(item, target / item.name)
            copied += 1
            if copied > DEFAULT_MAX_BATCH_FILES:
                raise InputError(f"batch directory exceeds the {DEFAULT_MAX_BATCH_FILES}-file project budget: {source}")
        if not copied:
            raise InputError(f"batch directory contains no JSON files: {source}")
    else:
        if not resolved.is_file():
            raise InputError(f"project input is not a file: {source}")
        shutil.copyfile(resolved, target)
    return target


def build_manifest(
    project_dir: Path,
    *,
    project_id: str,
    description: str = "",
    contract: Path,
    input: Path | None = None,
    baseline: Path | None = None,
    candidate: Path | None = None,
    batch: Path | None = None,
    batch_recursive: bool = False,
    batch_include_paths: bool = False,
    batch_minimum_ratio: str | None = None,
    minimum_ratio: str | None = None,
    population_scope: str | None = None,
    population_minimum: int | None = None,
    max_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    max_batch_files: int = DEFAULT_MAX_BATCH_FILES,
) -> ProjectManifest:
    """Fingerprint the chosen inputs and assemble a validated manifest."""
    manifest = ProjectManifest(
        project_id=_identifier(project_id, "project_id"),
        description=description,
        contract=make_input_ref(project_dir, Path(contract)),
        input=make_input_ref(project_dir, Path(input)) if input is not None else None,
        baseline=make_input_ref(project_dir, Path(baseline)) if baseline is not None else None,
        candidate=make_input_ref(project_dir, Path(candidate)) if candidate is not None else None,
        batch=BatchConfig(
            path=make_input_ref(project_dir, Path(batch), folder=True).path,
            sha256=fingerprint_tree(Path(batch).resolve(), max_files=max_batch_files, max_bytes=max_bytes),
            recursive=batch_recursive,
            include_paths=batch_include_paths,
            minimum_ratio=batch_minimum_ratio,
        )
        if batch is not None else None,
        coverage=CoverageConfig(
            minimum_ratio=minimum_ratio,
            population_scope=population_scope,
            population_minimum=population_minimum,
        ),
    )
    return parse_manifest(manifest_document(manifest))


def write_project(manifest_path: Path, manifest: ProjectManifest) -> None:
    """Explicitly write a manifest; refuses to replace an existing project file."""
    target = Path(manifest_path)
    if target.is_dir():
        target = target / PROJECT_MANIFEST_NAME
    elif target.suffix != ".json":
        raise InputError("project manifest must be a .json file path or an existing directory")
    if target.exists():
        raise InputError(f"project manifest already exists: {target}")
    write_report(target, manifest_text(manifest))
