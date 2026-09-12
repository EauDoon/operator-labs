"""Explicit, portable local project manifests for saved investigations.

A project is a manifest plus explicitly referenced fictional inputs. The
manifest stores only user-chosen settings: scenario, routes, baseline, named
variant references, and saved experiment configurations. Result evidence is
deliberately excluded; reopening a project never implies that a previous
report describes inputs that have since changed.

Relative paths resolve against the project directory so a self-contained
directory stays valid when it moves. Every referenced input records a
SHA-256 fingerprint at save time; opening reports missing or modified
inputs instead of silently accepting them.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import stat as stat_module
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from pathlib import Path, PurePosixPath

from .analysis import deadline_target, resolution_quantiles
from .canonical import (
    InputError,
    atomic_write_text,
    decimal_text,
    parse_json_bytes,
    read_bounded_bytes,
    require_decimal,
    require_decimal_values,
    require_identifier,
    require_keys,
    require_object,
    require_string,
)
from .sensitivity import run_sensitivity
from .stress import run_stress_grid
from .transaction_sweep import run_transaction_grid, run_transaction_sweep

PROJECT_MANIFEST_VERSION = "corridor-lab.project/v1"
PROJECT_MANIFEST_NAME = "corridor-lab.project.json"
MAX_PROJECT_INPUTS = 64
MAX_VARIANTS = 32
MAX_EXPERIMENTS = 64
MAX_DESCRIPTION_CHARS = 200
MAX_FOLDER_FILES = 64
ANALYSES = ("sensitivity", "transaction-sweep", "transaction-grid", "stress-grid",
            "deadline-target", "resolution-quantiles")
VARIABLE_ANALYSES = ("sensitivity", "transaction-sweep", "transaction-grid", "stress-grid")


@dataclass(frozen=True)
class InputRef:
    """A user-chosen input stored as a portable relative path and fingerprint."""

    path: str
    sha256: str
    folder: bool


@dataclass(frozen=True)
class Experiment:
    """A saved, bounded analysis configuration with explicit values."""

    name: str
    analysis: str
    fields: dict[str, str]


@dataclass(frozen=True)
class ProjectManifest:
    project_id: str
    description: str
    scenario: InputRef
    routes: InputRef | None
    baseline: InputRef | None
    variants: dict[str, InputRef]
    experiments: tuple[Experiment, ...]


@dataclass(frozen=True)
class LoadedProject:
    """A parsed manifest with resolved paths and honest input statuses."""

    path: Path
    manifest: ProjectManifest
    resolved: dict[str, Path]
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def fingerprint_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fingerprint_file(path: Path) -> str:
    """Hash a bounded fictional input file without following links."""
    return fingerprint_bytes(read_bounded_bytes(path))


def _relative_ref_path(project_dir: Path, source: Path) -> str:
    try:
        relative = source.resolve().relative_to(project_dir.resolve())
    except ValueError as exc:
        raise InputError(
            f"project inputs must live inside the project directory so the project stays portable: {source}"
        ) from exc
    if any(part == ".." for part in relative.parts):
        raise InputError(f"project input paths must not traverse upwards: {source}")
    return relative.as_posix()


def fingerprint_tree(path: Path) -> str:
    """Deterministically hash a bounded folder of JSON route files."""
    files: list[tuple[str, str]] = []
    for item in sorted(path.iterdir(), key=lambda child: child.name):
        try:
            metadata = item.lstat()
        except OSError as exc:
            raise InputError(f"project input folder could not be read: {path}") from exc
        if not stat_module.S_ISREG(metadata.st_mode) or not item.name.lower().endswith(".json"):
            continue
        files.append((item.name, fingerprint_file(item)))
        if len(files) > MAX_FOLDER_FILES:
            raise InputError(f"project input folder exceeds the {MAX_FOLDER_FILES}-file fingerprint budget: {path}")
    if not files:
        raise InputError(f"project input folder contains no JSON route files: {path}")
    digest = hashlib.sha256()
    for name, content_hash in files:
        digest.update(name.encode("utf-8"))
        digest.update(content_hash.encode("utf-8"))
    return digest.hexdigest()


def make_input_ref(project_dir: Path, source: Path) -> InputRef:
    """Fingerprint one explicit input and store it as a portable relative path."""
    resolved = Path(source).resolve()
    if resolved.is_dir():
        digest = fingerprint_tree(resolved)
        folder = True
    elif resolved.is_file():
        digest = fingerprint_file(resolved)
        folder = False
    else:
        raise InputError(f"project input is not a readable file or folder: {source}")
    return InputRef(path=_relative_ref_path(project_dir, resolved), sha256=digest, folder=folder)


def _parse_input_ref(value: object, path: str) -> InputRef:
    ref = require_object(value, path)
    require_keys(ref, {"path", "sha256", "folder"}, set(), path)
    text = require_string(ref["path"], f"{path}.path")
    posix = PurePosixPath(text)
    if Path(text).is_absolute() or posix.is_absolute() or text.startswith("~"):
        raise InputError(f"{path}.path must be a relative project path: {text}")
    if "\\" in text or any(part == ".." for part in posix.parts) or not posix.parts:
        raise InputError(f"{path}.path must use forward slashes and stay inside the project: {text}")
    digest = require_string(ref["sha256"], f"{path}.sha256")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise InputError(f"{path}.sha256 must be a 64-character lowercase SHA-256 digest")
    if type(ref["folder"]) is not bool:
        raise InputError(f"{path}.folder must be a boolean")
    return InputRef(path=text, sha256=digest, folder=ref["folder"])


def _parse_experiment(value: object, index: int) -> Experiment:
    path = f"experiments[{index}]"
    item = require_object(value, path)
    require_keys(item, {"name", "analysis", "fields"}, set(), path)
    name = require_identifier(item["name"], f"{path}.name")
    analysis = require_identifier(item["analysis"], f"{path}.analysis")
    if analysis not in ANALYSES:
        raise InputError(f"{path}.analysis must be one of {', '.join(ANALYSES)}")
    fields = require_object(item["fields"], f"{path}.fields")
    if analysis in VARIABLE_ANALYSES:
        if analysis in ("transaction-grid", "stress-grid"):
            required = {"parameter_a", "values_a", "parameter_b", "values_b"}
        else:
            required = {"parameter", "values"}
    elif analysis == "deadline-target":
        required = {"probability"}
    else:
        required = {"probabilities"}
    require_keys(fields, required, set(), f"{path}.fields")
    parsed: dict[str, str] = {}
    for field in required:
        text = require_string(fields[field], f"{path}.fields.{field}")
        if field.startswith("values") or field == "probabilities":
            chunks = [chunk.strip() for chunk in text.split(",")]
            if not all(chunks):
                raise InputError(f"{path}.fields.{field} must be comma-separated decimals")
            values = require_decimal_values(chunks, f"{path}.fields.{field}")
            parsed[field] = ",".join(decimal_text(value) for value in values)
        elif field == "probability":
            require_decimal(text, f"{path}.fields.{field}")
            parsed[field] = text
        else:
            parsed[field] = text
    return Experiment(name=name, analysis=analysis, fields=parsed)


def parse_manifest(value: object) -> ProjectManifest:
    """Parse and validate a strict corridor-lab project manifest."""
    manifest = require_object(value, "project manifest")
    require_keys(
        manifest,
        {"project_version", "project_id", "scenario", "experiments"},
        {"description", "routes", "baseline", "variants"},
        "project manifest",
    )
    if manifest["project_version"] != PROJECT_MANIFEST_VERSION:
        raise InputError(f"unsupported project manifest version: {manifest['project_version']}")
    project_id = require_identifier(manifest["project_id"], "project manifest.project_id")
    description = ""
    if "description" in manifest:
        description = require_string(manifest["description"], "project manifest.description")
        if len(description) > MAX_DESCRIPTION_CHARS:
            raise InputError(f"project manifest.description must be at most {MAX_DESCRIPTION_CHARS} characters")
    scenario = _parse_input_ref(manifest["scenario"], "scenario")
    routes = _parse_input_ref(manifest["routes"], "routes") if "routes" in manifest else None
    baseline = _parse_input_ref(manifest["baseline"], "baseline") if "baseline" in manifest else None
    variants: dict[str, InputRef] = {}
    if "variants" in manifest:
        variant_value = require_object(manifest["variants"], "variants")
        if len(variant_value) > MAX_VARIANTS:
            raise InputError(f"variants exceed the {MAX_VARIANTS}-variant budget")
        for name, ref in variant_value.items():
            variants[require_identifier(name, "variants name")] = _parse_input_ref(ref, f"variants[{name}]")
    experiment_values = require_object(manifest, "project manifest").get("experiments")
    if not isinstance(experiment_values, list):
        raise InputError("project manifest.experiments must be a list")
    if len(experiment_values) > MAX_EXPERIMENTS:
        raise InputError(f"experiments exceed the {MAX_EXPERIMENTS}-experiment budget")
    experiments = tuple(_parse_experiment(item, index) for index, item in enumerate(experiment_values))
    names = [experiment.name for experiment in experiments]
    if len(names) != len(set(names)):
        raise InputError("experiment names must be unique")
    return ProjectManifest(
        project_id=project_id,
        description=description,
        scenario=scenario,
        routes=routes,
        baseline=baseline,
        variants=variants,
        experiments=experiments,
    )


def load_project(path: str | Path) -> LoadedProject:
    """Read, resolve, and status a project from its manifest file or directory."""
    location = Path(path)
    manifest_path = location / PROJECT_MANIFEST_NAME if location.is_dir() else location
    project_dir = manifest_path.parent
    value = parse_json_bytes(read_bounded_bytes(manifest_path))
    manifest = parse_manifest(value)
    resolved: dict[str, Path] = {}
    problems: list[str] = []

    def resolve(ref: InputRef, label: str) -> None:
        target = project_dir / ref.path
        try:
            metadata = target.lstat()
        except OSError:
            problems.append(f"{label}: missing input {ref.path}")
            return
        if ref.folder:
            if not stat_module.S_ISDIR(metadata.st_mode):
                problems.append(f"{label}: {ref.path} is no longer a folder")
                return
            try:
                current = fingerprint_tree(target)
            except InputError as exc:
                problems.append(f"{label}: {exc}")
                return
        else:
            if not stat_module.S_ISREG(metadata.st_mode):
                problems.append(f"{label}: {ref.path} is no longer a regular file")
                return
            current = fingerprint_file(target)
        if current != ref.sha256:
            problems.append(f"{label}: {ref.path} changed since the project was saved")
            return
        resolved[label] = target

    resolve(manifest.scenario, "scenario")
    if manifest.routes is not None:
        resolve(manifest.routes, "routes")
    if manifest.baseline is not None:
        resolve(manifest.baseline, "baseline")
    for name, ref in manifest.variants.items():
        resolve(ref, f"variant {name}")
    return LoadedProject(path=manifest_path, manifest=manifest, resolved=resolved, problems=tuple(problems))


def _copy_regular_file(source: Path, target: Path) -> None:
    if target.exists():
        raise InputError(f"project input already exists: {target}")
    shutil.copyfile(source, target)


def _copy_route_folder(source: Path, target: Path) -> None:
    if target.exists():
        raise InputError(f"project input folder already exists: {target}")
    target.mkdir(parents=True)
    copied = 0
    for item in sorted(source.iterdir(), key=lambda child: child.name):
        try:
            metadata = item.lstat()
        except OSError as exc:
            raise InputError(f"route folder could not be read: {source}") from exc
        if not stat_module.S_ISREG(metadata.st_mode) or not item.name.lower().endswith(".json"):
            continue
        _copy_regular_file(item, target / item.name)
        copied += 1
        if copied > MAX_FOLDER_FILES:
            raise InputError(f"route folder exceeds the {MAX_FOLDER_FILES}-file project budget: {source}")
    if not copied:
        raise InputError(f"route folder contains no JSON route files: {source}")


def prepare_project_directory(
    directory: Path,
    scenario: Path,
    routes: Path | None = None,
    baseline: Path | None = None,
    variants: dict[str, Path] | None = None,
) -> dict[str, Path]:
    """Make the chosen inputs self-contained inside the project directory.

    Inputs already inside the directory are used in place; inputs outside are
    explicitly copied into ``inputs/``. Nothing is copied silently: every
    collision or unreadable source raises before the manifest is written.
    """
    project_dir = Path(directory).resolve()
    if not project_dir.is_dir():
        raise InputError(f"project directory must exist: {directory}")

    def place(source: Path | None) -> Path | None:
        if source is None:
            return None
        resolved = Path(source).resolve()
        if resolved == project_dir or not (resolved.is_file() or resolved.is_dir()):
            raise InputError(f"project input is not a readable file or folder: {source}")
        try:
            resolved.relative_to(project_dir)
            return resolved
        except ValueError:
            pass
        inputs_dir = project_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        target = inputs_dir / resolved.name
        if resolved.is_dir():
            _copy_route_folder(resolved, target)
        else:
            _copy_regular_file(resolved, target)
        return target

    placed: dict[str, Path] = {}
    placed_scenario = place(scenario)
    if placed_scenario is None or not placed_scenario.is_file():
        raise InputError(f"project scenario must be a file: {scenario}")
    placed["scenario"] = placed_scenario
    placed_routes = place(routes)
    if placed_routes is not None:
        placed["routes"] = placed_routes
    placed_baseline = place(baseline)
    if placed_baseline is not None:
        placed["baseline"] = placed_baseline
    for name, source in sorted((variants or {}).items()):
        placed_variant = place(source)
        if placed_variant is None:
            raise InputError(f"variant {name} input is not readable: {source}")
        placed[f"variant {name}"] = placed_variant
    if len(placed) > MAX_PROJECT_INPUTS:
        raise InputError(f"project exceeds the {MAX_PROJECT_INPUTS}-input budget")
    return placed


def manifest_document(manifest: ProjectManifest) -> dict[str, object]:
    def ref_document(ref: InputRef) -> dict[str, object]:
        return {"path": ref.path, "sha256": ref.sha256, "folder": ref.folder}

    document: dict[str, object] = {
        "project_version": PROJECT_MANIFEST_VERSION,
        "project_id": manifest.project_id,
        "scenario": ref_document(manifest.scenario),
        "experiments": [
            {"name": experiment.name, "analysis": experiment.analysis, "fields": dict(experiment.fields)}
            for experiment in manifest.experiments
        ],
    }
    if manifest.description:
        document["description"] = manifest.description
    if manifest.routes is not None:
        document["routes"] = ref_document(manifest.routes)
    if manifest.baseline is not None:
        document["baseline"] = ref_document(manifest.baseline)
    if manifest.variants:
        document["variants"] = {name: ref_document(ref) for name, ref in manifest.variants.items()}
    return document


def manifest_text(manifest: ProjectManifest) -> str:
    return json.dumps(manifest_document(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_manifest(
    project_dir: Path,
    *,
    project_id: str,
    description: str = "",
    scenario: Path,
    routes: Path | None = None,
    baseline: Path | None = None,
    variants: dict[str, Path] | None = None,
    experiments: tuple[Experiment, ...] = (),
) -> ProjectManifest:
    """Fingerprint the chosen inputs and assemble a validated manifest."""
    if len(variants or {}) > MAX_VARIANTS:
        raise InputError(f"variants exceed the {MAX_VARIANTS}-variant budget")
    if len(experiments) > MAX_EXPERIMENTS:
        raise InputError(f"experiments exceed the {MAX_EXPERIMENTS}-experiment budget")
    refs: dict[str, Path] = {}
    if scenario is not None:
        refs["scenario"] = scenario
    if routes is not None:
        refs["routes"] = routes
    if baseline is not None:
        refs["baseline"] = baseline
    if len(refs) + len(variants or {}) > MAX_PROJECT_INPUTS:
        raise InputError(f"project exceeds the {MAX_PROJECT_INPUTS}-input budget")
    manifest = ProjectManifest(
        project_id=require_identifier(project_id, "project_id"),
        description=description,
        scenario=make_input_ref(project_dir, Path(scenario)),
        routes=make_input_ref(project_dir, Path(routes)) if routes is not None else None,
        baseline=make_input_ref(project_dir, Path(baseline)) if baseline is not None else None,
        variants={name: make_input_ref(project_dir, path) for name, path in sorted((variants or {}).items())},
        experiments=tuple(experiments),
    )
    return manifest


def write_project(manifest_path: Path, manifest: ProjectManifest) -> None:
    """Explicitly write a manifest; refuses to replace an existing project file."""
    target = Path(manifest_path)
    if target.is_dir():
        target = target / PROJECT_MANIFEST_NAME
    elif target.suffix != ".json":
        raise InputError("project manifest must be a .json file path or an existing directory")
    if target.exists():
        raise InputError(f"project manifest already exists: {target}")
    atomic_write_text(target, manifest_text(manifest))


def parse_experiment_argument(text: str) -> Experiment:
    """Parse ``NAME:ANALYSIS:KEY=VALUE;KEY=VALUE`` with strict field validation."""
    parts = text.split(":", 2)
    if len(parts) != 3 or not parts[2].strip():
        raise InputError("experiment must be NAME:ANALYSIS:KEY=VALUE with fields separated by semicolons")
    name, analysis, fields_text = parts
    fields: dict[str, str] = {}
    for chunk in fields_text.split(";"):
        key, separator, value = chunk.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise InputError(f"experiment field must be KEY=VALUE: {chunk}")
        if key.strip() in fields:
            raise InputError(f"experiment field repeated: {key.strip()}")
        fields[key.strip()] = value.strip()
    return _parse_experiment({"name": name, "analysis": analysis, "fields": fields}, 0)


def validate_experiment(name: str, analysis: str, fields: dict[str, str]) -> Experiment:
    """Validate one experiment configuration before it enters a project draft."""
    return _parse_experiment({"name": name, "analysis": analysis, "fields": dict(fields)}, 0)


def execute_experiment(experiment: Experiment, scenario) -> dict[str, object]:
    """Run one saved experiment through the ordinary library analyses."""
    analysis = experiment.analysis

    def values(field: str) -> list[Decimal]:
        return [Decimal(chunk.strip()) for chunk in experiment.fields[field].split(",") if chunk.strip()]

    if analysis == "sensitivity":
        return run_sensitivity(scenario, experiment.fields["parameter"], values("values"))
    if analysis == "transaction-sweep":
        return run_transaction_sweep(scenario, experiment.fields["parameter"], values("values"))
    if analysis == "transaction-grid":
        return run_transaction_grid(scenario, experiment.fields["parameter_a"], values("values_a"),
                                    experiment.fields["parameter_b"], values("values_b"))
    if analysis == "stress-grid":
        return run_stress_grid(scenario, experiment.fields["parameter_a"], values("values_a"),
                               experiment.fields["parameter_b"], values("values_b"))
    if analysis == "deadline-target":
        return deadline_target(scenario, experiment.fields["probability"])
    if analysis == "resolution-quantiles":
        return resolution_quantiles(scenario, values("probabilities"))
    raise InputError(f"unsupported experiment analysis: {analysis}")


def experiment_from_cli(
    name: str,
    analysis: str,
    *,
    parameter: str | None = None,
    values: str | None = None,
    parameter_a: str | None = None,
    values_a: str | None = None,
    parameter_b: str | None = None,
    values_b: str | None = None,
    probability: str | None = None,
    probabilities: str | None = None,
) -> Experiment:
    """Assemble and validate one experiment from explicit CLI fields."""
    if analysis not in ANALYSES:
        raise InputError(f"experiment analysis must be one of {', '.join(ANALYSES)}")
    if analysis in VARIABLE_ANALYSES:
        if analysis in ("transaction-grid", "stress-grid"):
            fields = {"parameter_a": parameter_a, "values_a": values_a, "parameter_b": parameter_b, "values_b": values_b}
        else:
            fields = {"parameter": parameter, "values": values}
    elif analysis == "deadline-target":
        fields = {"probability": probability}
    else:
        fields = {"probabilities": probabilities}
    missing = [field for field, value in fields.items() if value is None]
    if missing:
        raise InputError(f"experiment {analysis} requires {', '.join(missing)}")
    # Reuse the manifest parser as the single validator for experiment fields.
    parsed = _parse_experiment({"name": name, "analysis": analysis, "fields": {key: value for key, value in fields.items()}}, 0)
    return parsed
