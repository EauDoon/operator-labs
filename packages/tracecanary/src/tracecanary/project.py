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
import os
import re
import shutil
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from tracecanary.canonical import InputError, canonical_json, load_json
from tracecanary.contract import DEFAULT_MAX_BATCH_FILES, DEFAULT_MAX_INPUT_BYTES, DEFAULT_MAX_NESTING
from tracecanary.inspection import _parse_minimum_ratio, population_gate_configured
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
    """Hash a bounded synthetic input file without trusting a stale size.

    ``stat`` then ``read_bytes`` hashed the whole file when the file grew
    after the size check, so the fingerprint budget could be skipped.
    """
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise InputError(f"project input exceeds the {max_bytes}-byte fingerprint budget: {path}")
    return hashlib.sha256(raw).hexdigest()


def _json_export(item: Path, root: Path) -> bool:
    """Same file rule as a batch: regular file, case-insensitive ``.json`` suffix, inside ``root``."""
    if not item.name.lower().endswith(".json"):
        return False
    try:
        metadata = item.lstat()
    except OSError as exc:
        raise InputError(f"project input folder could not be read: {root}") from exc
    if not stat_module.S_ISREG(metadata.st_mode):
        return False
    try:
        resolved = item.resolve()
    except OSError as exc:
        raise InputError(f"project input folder could not be read: {root}") from exc
    return resolved.is_relative_to(root.resolve())


def fingerprint_tree(path: Path, *, max_files: int, max_bytes: int, recursive: bool = False) -> str:
    """Deterministically hash a bounded folder of JSON synthetic exports.

    ``recursive`` selects the same nested files ``batch --recursive`` reads.
    A flat directory keeps the previous name-ordered hash, so a saved project
    whose batch has no subdirectories still matches.
    """
    files: list[tuple[str, str]] = []
    if recursive:
        discovered = [item for item in path.rglob("*") if _json_export(item, path)]
        discovered.sort(key=lambda item: item.relative_to(path).as_posix())
        entries = [(item.relative_to(path).as_posix(), item) for item in discovered]
    else:
        entries = []
        for item in sorted(path.iterdir(), key=lambda child: child.name):
            try:
                metadata = item.lstat()
            except OSError as exc:
                raise InputError(f"project input folder could not be read: {path}") from exc
            if not stat_module.S_ISREG(metadata.st_mode) or not item.name.lower().endswith(".json"):
                continue
            entries.append((item.name, item))
    for name, item in entries:
        files.append((name, fingerprint_file(item, max_bytes=max_bytes)))
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


def containment_problem(project_dir: Path, ref_path: str) -> str | None:
    """Explain why a manifest path would leave the project, or return None.

    ``project create`` refuses inputs outside the project directory, and a
    loaded project holds the same line. On Windows a drive-relative path
    such as ``C:outside/contract.json`` replaces the project directory when
    joined, so it resolves against the working directory instead. A
    junction or a symlinked directory inside the project can also lead out
    of it. Neither input is fingerprinted or resolved.
    """
    if os.name == "nt":
        windows = PureWindowsPath(ref_path)
        if windows.drive or windows.root:
            return "is not a portable relative project path"
    try:
        (project_dir / ref_path).resolve().relative_to(project_dir.resolve())
    except (OSError, RuntimeError, ValueError):
        return "resolves outside the project directory"
    return None


def load_project(path: str | Path, *, max_bytes: int = DEFAULT_MAX_INPUT_BYTES, max_depth: int = DEFAULT_MAX_NESTING, max_batch_files: int = DEFAULT_MAX_BATCH_FILES) -> LoadedProject:
    """Read, resolve, and status a project from its manifest file or directory."""
    manifest_path = _manifest_location(path)
    manifest = parse_manifest(load_json(manifest_path, max_bytes=max_bytes, max_depth=max_depth))
    resolved, problems = _resolve_inputs(manifest_path.parent, manifest, max_bytes=max_bytes,
                                         max_batch_files=max_batch_files)
    return LoadedProject(path=manifest_path, manifest=manifest, resolved=resolved, problems=problems)


def _manifest_location(path: str | Path) -> Path:
    location = Path(path)
    return location / PROJECT_MANIFEST_NAME if location.is_dir() else location


def _resolve_inputs(
    project_dir: Path,
    manifest: ProjectManifest,
    *,
    max_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    max_batch_files: int = DEFAULT_MAX_BATCH_FILES,
) -> tuple[dict[str, Path], tuple[str, ...]]:
    """Fingerprint every manifest input; return the verified paths and every problem."""
    resolved: dict[str, Path] = {}
    problems: list[str] = []

    def resolve(ref: InputRef, label: str, *, folder: bool = False, max_files: int = max_batch_files, recursive: bool = False) -> None:
        problem = containment_problem(project_dir, ref.path)
        if problem is not None:
            problems.append(f"{label}: {ref.path} {problem}")
            return
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
                current = fingerprint_tree(target, max_files=max_files, max_bytes=max_bytes, recursive=recursive)
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
        resolve(InputRef(path=manifest.batch.path, sha256=manifest.batch.sha256), "batch directory", folder=True, recursive=manifest.batch.recursive)
    return resolved, tuple(problems)


REFRESH_LABELS = ("contract", "input", "baseline", "candidate", "batch")


@dataclass(frozen=True)
class RefreshOutcome:
    """One named input of a refresh. Digests stay out of everything printed."""

    label: str
    path: str
    changed: bool


@dataclass(frozen=True)
class RefreshResult:
    """What ``refresh_project`` found; the manifest is written only when ``problems`` is empty."""

    manifest_path: Path
    outcomes: tuple[RefreshOutcome, ...]
    problems: tuple[str, ...]
    warnings: tuple[str, ...]
    written: bool


def _refresh_targets(manifest: ProjectManifest, labels: list[str] | tuple[str, ...]) -> list[tuple[str, str, str]]:
    """Map refresh labels to (label, path, saved digest), refusing unknown or undeclared ones."""
    if not labels:
        raise InputError("project refresh needs at least one --input label")
    targets: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for raw in labels:
        label = raw.strip()
        if label in seen:
            raise InputError(f"refresh input label repeated: {label}")
        seen.add(label)
        if label not in REFRESH_LABELS:
            raise InputError(f"unknown refresh input label: {label} (use {', '.join(REFRESH_LABELS)})")
        ref = manifest.batch if label == "batch" else getattr(manifest, label)
        if ref is None:
            raise InputError(f"{label}: the project manifest declares no such input")
        targets.append((label, ref.path, ref.sha256))
    # The contract is validated first, so the other inputs are checked
    # against the contract that will be saved.
    targets.sort(key=lambda item: item[0] != "contract")
    return targets


def refresh_project(path: str | Path, labels: list[str] | tuple[str, ...]) -> RefreshResult:
    """Explicitly accept deliberately edited inputs after validating them.

    Each named input must be declared, present with its saved kind, resolve
    inside the project directory, and pass its validator: the contract must
    load; an input or candidate must be a structurally valid bounded OTLP
    export (candidates may leak by design, so their findings do not block);
    a baseline must satisfy the contract, as ``promote-baseline`` requires;
    a batch folder must enumerate within its bounds with the saved
    recursive setting (its exports may fail by design). The manifest is
    replaced atomically only when every named input passes and the project
    would then load with no problems; otherwise it is left byte-identical
    and every blocking problem is returned. Inputs are never rewritten, and
    unnamed inputs are never touched.
    """
    from tracecanary.checker import check_trace
    from tracecanary.contract import ContractError, load_contract
    from tracecanary.otlp import OtlpError, validate_trace

    manifest_path = _manifest_location(path)
    manifest = parse_manifest(load_json(manifest_path, max_bytes=DEFAULT_MAX_INPUT_BYTES, max_depth=DEFAULT_MAX_NESTING))
    project_dir = manifest_path.parent
    targets = _refresh_targets(manifest, labels)
    problems: list[str] = []
    outcomes: list[RefreshOutcome] = []
    digests: dict[str, str] = {}
    contract = None
    contract_error = ""
    if "contract" not in {label for label, _, _ in targets}:
        try:
            contract = load_contract(project_dir / manifest.contract.path)
        except (ContractError, InputError, OSError, ValueError) as exc:
            contract_error = str(exc)

    for label, ref_path, saved in targets:
        problem = containment_problem(project_dir, ref_path)
        if problem is not None:
            problems.append(f"{label}: {ref_path} {problem}")
            continue
        target = project_dir / ref_path
        try:
            metadata = target.lstat()
        except OSError:
            problems.append(f"{label}: missing input {ref_path}")
            continue
        try:
            if label == "batch":
                if not stat_module.S_ISDIR(metadata.st_mode):
                    problems.append(f"{label}: {ref_path} is no longer a folder")
                    continue
                digest = fingerprint_tree(target, max_files=DEFAULT_MAX_BATCH_FILES, max_bytes=DEFAULT_MAX_INPUT_BYTES,
                                          recursive=manifest.batch.recursive)
            else:
                if not stat_module.S_ISREG(metadata.st_mode):
                    problems.append(f"{label}: {ref_path} is no longer a regular file")
                    continue
                digest = fingerprint_file(target, max_bytes=DEFAULT_MAX_INPUT_BYTES)
                if label == "contract":
                    contract = load_contract(target)
                elif contract is None:
                    problems.append(f"{label}: {ref_path} cannot be validated because the contract does not load"
                                    + (f" ({contract_error})" if contract_error else ""))
                    continue
                else:
                    payload = load_json(target, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
                    validate_trace(payload)
                    if label == "baseline" and check_trace(contract, payload, mode="check")["status"] != "pass":
                        problems.append(f"{label}: {ref_path} does not satisfy the contract; "
                                        "a baseline must pass before it is accepted")
                        continue
        except (ContractError, InputError, OtlpError, OSError, ValueError) as exc:
            if label == "contract":
                contract_error = str(exc)
            problems.append(f"{label}: {ref_path} does not validate: {exc}")
            continue
        digests[label] = digest
        outcomes.append(RefreshOutcome(label, ref_path, digest != saved))

    document = manifest_document(manifest)
    for label, digest in digests.items():
        document[label]["sha256"] = digest
    refreshed = parse_manifest(document)
    _, remaining = _resolve_inputs(project_dir, refreshed)
    # Named inputs that failed above already carry a more precise problem.
    failed = {"batch directory" if label == "batch" else label for label, _, _ in targets if label not in digests}
    problems.extend(problem for problem in remaining
                    if not any(problem.startswith(f"{label}: ") for label in failed))

    warnings: list[str] = []
    if not problems and "contract" in digests and refreshed.baseline is not None and "baseline" not in digests:
        try:
            baseline_payload = load_json(project_dir / refreshed.baseline.path, max_bytes=contract.max_input_bytes,
                                         max_depth=contract.max_nesting)
            validate_trace(baseline_payload)
            satisfied = check_trace(contract, baseline_payload, mode="check")["status"] == "pass"
        except (InputError, OtlpError, OSError, ValueError):
            satisfied = False
        if not satisfied:
            warnings.append(f"baseline: {refreshed.baseline.path} no longer satisfies the refreshed contract; "
                            "campaigns will report the baseline phase unresolved until a passing baseline is promoted")

    written = False
    if not problems and any(outcome.changed for outcome in outcomes):
        write_report(manifest_path, manifest_text(refreshed))
        written = True
    return RefreshResult(manifest_path=manifest_path, outcomes=tuple(outcomes), problems=tuple(problems),
                         warnings=tuple(warnings), written=written)


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


def make_input_ref(project_dir: Path, source: Path, *, folder: bool = False, max_files: int = DEFAULT_MAX_BATCH_FILES, max_bytes: int = DEFAULT_MAX_INPUT_BYTES, recursive: bool = False) -> InputRef:
    resolved = Path(source).resolve()
    if folder:
        if not resolved.is_dir():
            raise InputError(f"project batch directory is not a folder: {source}")
        digest = fingerprint_tree(resolved, max_files=max_files, max_bytes=max_bytes, recursive=recursive)
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


def _read_bounded(path: Path, max_bytes: int = DEFAULT_MAX_INPUT_BYTES) -> bytes | None:
    """Read at most one byte past the budget; ``None`` means the file is over it."""
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    return None if len(raw) > max_bytes else raw


def _holds_identical_copy(target: Path, source: Path) -> bool:
    """True when ``target`` is a regular file, not a link, with exactly ``source``'s bytes."""
    try:
        if not stat_module.S_ISREG(target.lstat().st_mode):
            return False
        existing = _read_bounded(target)
        incoming = _read_bounded(source)
    except OSError:
        return False
    return existing is not None and existing == incoming


def validate_project_settings(
    *,
    project_id: str,
    description: str = "",
    minimum_ratio: str | None = None,
    batch_minimum_ratio: str | None = None,
    population_scope: str | None = None,
    population_minimum: int | None = None,
) -> None:
    """Check every setting that needs no input file, before anything is copied."""
    _identifier(project_id, "project_id")
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_CHARS:
        raise InputError(f"project description must be a string of at most {MAX_DESCRIPTION_CHARS} characters")
    for ratio in (minimum_ratio, batch_minimum_ratio):
        if ratio is not None:
            _parse_minimum_ratio(ratio)
    if population_gate_configured(population_scope, population_minimum):
        if population_scope not in POPULATION_SCOPES:
            raise InputError("coverage.population_scope must be one of " + ", ".join(POPULATION_SCOPES))
        if type(population_minimum) is not int or not 1 <= population_minimum <= 1_000_000:
            raise InputError("coverage.population_minimum must be a whole number from 1 to 1000000")


def remove_created_paths(created: list[Path]) -> None:
    """Undo a failed project save: remove exactly the paths it created, newest first.

    Files are unlinked and folders removed only when empty, so nothing that
    existed before the save, or that something else added since, is touched.
    """
    for path in reversed(created):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
        except OSError:
            continue
    created.clear()


def _make_directories(directory: Path, created: list[Path]) -> None:
    missing: list[Path] = []
    current = directory
    while not current.exists():
        missing.append(current)
        current = current.parent
    for item in reversed(missing):
        item.mkdir()
        created.append(item)


def _copy_project_input(
    project_dir: Path,
    source: Path,
    *,
    folder: bool = False,
    recursive: bool = False,
    created: list[Path] | None = None,
) -> Path:
    """Copy one chosen synthetic input into the project, or use it in place.

    A file whose byte-identical copy the project already holds under the
    same name reuses that copy, which is the normal flow when promoting the
    candidate saved by ``project create --candidate``. A different file with
    the same name is still refused, and folders are never reused. Every file
    and folder this call creates is appended to ``created`` so a failed save
    can remove exactly those; reused copies are never recorded.
    """
    record: list[Path] = [] if created is None else created
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
    _make_directories(inputs_dir, record)
    target = inputs_dir / resolved.name
    if target.exists():
        if not folder and resolved.is_file() and _holds_identical_copy(target, resolved):
            return target
        raise InputError(f"project input already exists: {target}")
    if folder:
        if not resolved.is_dir():
            raise InputError(f"project batch directory is not a folder: {source}")
        target.mkdir()
        record.append(target)
        copied = 0
        if recursive:
            selected = [item for item in resolved.rglob("*") if _json_export(item, resolved)]
            selected.sort(key=lambda item: item.relative_to(resolved).as_posix())
            sources = [(item, item.relative_to(resolved)) for item in selected]
        else:
            sources = []
            for item in sorted(resolved.iterdir(), key=lambda child: child.name):
                try:
                    metadata = item.lstat()
                except OSError as exc:
                    raise InputError(f"batch directory could not be read: {source}") from exc
                if not stat_module.S_ISREG(metadata.st_mode) or not item.name.lower().endswith(".json"):
                    continue
                sources.append((item, Path(item.name)))
        for item, relative in sources:
            destination = target / relative
            _make_directories(destination.parent, record)
            record.append(destination)
            shutil.copyfile(item, destination)
            copied += 1
            if copied > DEFAULT_MAX_BATCH_FILES:
                raise InputError(f"batch directory exceeds the {DEFAULT_MAX_BATCH_FILES}-file project budget: {source}")
        if not copied:
            raise InputError(f"batch directory contains no JSON files: {source}")
    else:
        if not resolved.is_file():
            raise InputError(f"project input is not a file: {source}")
        record.append(target)
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
    population_gate_configured(population_scope, population_minimum)
    batch_ref = make_input_ref(project_dir, Path(batch), folder=True,
                               max_files=max_batch_files, max_bytes=max_bytes, recursive=batch_recursive) if batch is not None else None
    manifest = ProjectManifest(
        project_id=_identifier(project_id, "project_id"),
        description=description,
        contract=make_input_ref(project_dir, Path(contract), max_bytes=max_bytes),
        input=make_input_ref(project_dir, Path(input), max_bytes=max_bytes) if input is not None else None,
        baseline=make_input_ref(project_dir, Path(baseline), max_bytes=max_bytes) if baseline is not None else None,
        candidate=make_input_ref(project_dir, Path(candidate), max_bytes=max_bytes) if candidate is not None else None,
        batch=BatchConfig(
            path=batch_ref.path,
            sha256=batch_ref.sha256,
            recursive=batch_recursive,
            include_paths=batch_include_paths,
            minimum_ratio=batch_minimum_ratio,
        )
        if batch_ref is not None else None,
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
