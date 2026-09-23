"""Parsing and validation for the Test Suite Definition JSON.

Format reference: test-suite-package.md (mirrors the format Register's
`testing.views._serialize_test_suite` produces).
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_EXPORT_SCHEMA_VERSION = 1
TEST_SUITE_DEFINITION_FILENAME = "test-suite-definition.json"


class SuiteFormatError(ValueError):
    """A Test Suite JSON file doesn't match the expected envelope shape."""


@dataclass(frozen=True)
class Design:
    id: int
    sku: str
    name: str
    hw_version: str


@dataclass(frozen=True)
class TestSuiteMeta:
    version: int
    status: str
    notes: str | None
    created_dt: str


@dataclass(frozen=True)
class TestStep:
    order: int
    step_type: str
    name: str
    abort_on_fail: bool
    config_schema_version: int | None
    config: dict
    # issue #123: whether this step is printed on testomatic-ui's Test Docket when it passes -
    # always executed/recorded regardless, and a failing step is always printed regardless too.
    # Defaults True so a Test Suite Package exported before this field existed still parses as
    # "print every step", matching what it actually did at the time.
    include_on_docket: bool = True
    # register#127: operator-facing guidance for when this step fails - a free-text note plus
    # zero or more image filenames, resolved relative to `package_dir` (see `TestSuiteFile`
    # below) same as a firmware step's `firmware_file`/`images`. Both default to "nothing to
    # show" so a Test Suite Package exported before this field existed still parses cleanly -
    # neither is executed on, only read by a caller (e.g. testomatic-ui) off a failed
    # StepOutcome to show the operator.
    diagnostic_note: str | None = None
    diagnostic_images: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ManualCheck:
    order: int
    text: str


@dataclass(frozen=True)
class TestSuiteFile:
    export_schema_version: int
    design: Design
    test_suite: TestSuiteMeta
    test_steps: list[TestStep]
    manual_checks: list[ManualCheck]
    package_dir: Path | None = None


def load_suite(path: str | Path) -> TestSuiteFile:
    """Load and validate a Test Suite Definition from `path`.

    `path` may point directly at a Test Suite Definition JSON file, or at a Test Suite Package
    ZIP archive (see test-suite-package.md) — the package's wrapped test-suite-definition.json is
    located and parsed automatically. Either way, the returned `TestSuiteFile.package_dir` is the
    directory other files a step references (e.g. a firmware step's `firmware_file`) resolve
    relative to — see `_extract_package()`/`steps/firmware.py`.
    """
    path = Path(path)
    if path.suffix == ".zip":
        text, package_dir = _extract_package(path)
    else:
        text, package_dir = path.read_text(), path.parent
    return parse_suite(json.loads(text), package_dir=package_dir)


def _extract_package(path: Path) -> tuple[str, Path]:
    """Extracts every file from a Test Suite Package ZIP alongside `path`, producing
    `path.parent/<top-level-folder>/...` — the same self-contained folder the ZIP already wraps
    everything in (see test-suite-package.md). Returns the definition JSON's text plus that
    folder, which other config fields (e.g. a firmware step's `firmware_file`) resolve relative
    to. The top-level folder's name is read from the archive itself rather than assumed from
    `path`'s own name, matching how the definition file is located below.

    Re-extracting on every load is deliberate: it's what keeps files on disk in sync if the same
    `path` is ever loaded again after the package it points at has changed underneath it.
    """
    with zipfile.ZipFile(path) as archive:
        definition_entry = _find_definition_entry(archive, path)
        archive.extractall(path.parent)
        text = archive.read(definition_entry).decode("utf-8")

    package_dir = path.parent / Path(definition_entry).parent
    return text, package_dir


def _find_definition_entry(archive: zipfile.ZipFile, path: Path) -> str:
    """Finds test-suite-definition.json's entry name inside a Test Suite Package ZIP.

    Located by filename suffix rather than a hardcoded path, since the definition sits inside a
    top-level folder named after the package (e.g. `abc-hw1-0-test-suite-v3/test-suite-
    definition.json`), not at the archive root.
    """
    matches = [name for name in archive.namelist() if name.endswith(TEST_SUITE_DEFINITION_FILENAME)]
    if not matches:
        raise SuiteFormatError(f"No {TEST_SUITE_DEFINITION_FILENAME} found in Test Suite Package {path}")
    if len(matches) > 1:
        raise SuiteFormatError(
            f"Multiple {TEST_SUITE_DEFINITION_FILENAME} entries found in Test Suite Package "
            f"{path}: {matches}"
        )
    return matches[0]


def parse_suite(data: dict, package_dir: Path | None = None) -> TestSuiteFile:
    """Parse and validate a Test Suite JSON export already loaded as a dict."""
    export_schema_version = _require(data, "export_schema_version")
    if export_schema_version != SUPPORTED_EXPORT_SCHEMA_VERSION:
        raise SuiteFormatError(
            f"Unsupported export_schema_version {export_schema_version!r}; "
            f"this runner supports {SUPPORTED_EXPORT_SCHEMA_VERSION}"
        )

    test_steps = sorted(
        (_parse_test_step(step) for step in _require(data, "test_steps")),
        key=lambda step: step.order,
    )
    manual_checks = sorted(
        (_parse_manual_check(check) for check in _require(data, "manual_checks")),
        key=lambda check: check.order,
    )

    return TestSuiteFile(
        export_schema_version=export_schema_version,
        design=_parse_design(_require(data, "design")),
        test_suite=_parse_test_suite_meta(_require(data, "test_suite")),
        test_steps=test_steps,
        manual_checks=manual_checks,
        package_dir=package_dir,
    )


def _require(data: dict, key: str):
    try:
        return data[key]
    except KeyError as exc:
        raise SuiteFormatError(f"Missing required key: {key}") from exc


def _parse_design(data: dict) -> Design:
    return Design(
        id=_require(data, "id"),
        sku=_require(data, "sku"),
        name=_require(data, "name"),
        hw_version=_require(data, "hw_version"),
    )


def _parse_test_suite_meta(data: dict) -> TestSuiteMeta:
    return TestSuiteMeta(
        version=_require(data, "version"),
        status=_require(data, "status"),
        notes=data.get("notes"),
        created_dt=_require(data, "created_dt"),
    )


def _parse_test_step(data: dict) -> TestStep:
    config = _require(data, "config")
    config_schema_version = data.get("config_schema_version")
    inner_version = config.get("schema_version")
    if (
        config_schema_version is not None
        and inner_version is not None
        and config_schema_version != inner_version
    ):
        raise SuiteFormatError(
            f"Step {data.get('name')!r}: config_schema_version "
            f"({config_schema_version}) does not match config['schema_version'] "
            f"({inner_version})"
        )

    diagnostic = data.get("diagnostic") or {}

    return TestStep(
        order=_require(data, "order"),
        step_type=_require(data, "step_type"),
        name=_require(data, "name"),
        abort_on_fail=data.get("abort_on_fail", False),
        config_schema_version=config_schema_version,
        config=config,
        include_on_docket=data.get("include_on_docket", True),
        diagnostic_note=diagnostic.get("note"),
        diagnostic_images=diagnostic.get("images", []),
    )


def _parse_manual_check(data: dict) -> ManualCheck:
    return ManualCheck(order=_require(data, "order"), text=_require(data, "text"))
