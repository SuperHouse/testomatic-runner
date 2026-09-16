"""Tests for suite.py against the sample export and hand-built envelopes."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from testomatic.suite import SuiteFormatError, load_suite, parse_suite

FIXTURE = Path(__file__).parent.parent / "aqs-hw41-test-suite-v1" / "test-suite-definition.json"
ZIP_FIXTURE = Path(__file__).parent.parent / "aqs-hw41-test-suite-v1.zip"


def _envelope(**overrides) -> dict:
    envelope = {
        "export_schema_version": 1,
        "design": {"id": 1, "sku": "X", "name": "X Board", "hw_version": "1.0"},
        "test_suite": {"version": 1, "status": "DRAFT", "notes": None, "created_dt": "now"},
        "test_steps": [],
        "manual_checks": [],
    }
    envelope.update(overrides)
    return envelope


def test_loads_sample_suite_fixture():
    suite = load_suite(FIXTURE)

    assert suite.export_schema_version == 1
    assert suite.design.sku == "AQS"
    assert suite.design.hw_version == "4.1"
    assert suite.test_suite.status == "DRAFT"

    assert len(suite.test_steps) == 1
    step = suite.test_steps[0]
    assert step.step_type == "BEEP"
    assert step.config == {"duration_ms": 100, "count": 3, "schema_version": 1}

    assert len(suite.manual_checks) == 1
    assert suite.manual_checks[0].text == "Check me please"

    # A bare Test Suite Definition JSON file (not inside a package) resolves relative to its own
    # parent directory -- see suite.py's load_suite().
    assert suite.package_dir == FIXTURE.parent


def test_loads_sample_suite_from_zip_package():
    """load_suite() also accepts a Test Suite Package .zip directly, locating the wrapped
    test-suite-definition.json inside its same-named top-level folder."""
    suite = load_suite(ZIP_FIXTURE)

    assert suite.design.sku == "AQS"
    assert suite.design.hw_version == "4.1"
    assert len(suite.test_steps) == 1
    assert suite.test_steps[0].step_type == "BEEP"
    assert suite.package_dir == ZIP_FIXTURE.parent / "aqs-hw41-test-suite-v1"


def test_loading_a_zip_package_extracts_referenced_files_alongside_it(tmp_path):
    """A firmware step's executor (see steps/firmware.py) resolves firmware_file relative to
    package_dir, so load_suite() must actually extract the package's other files to disk, not
    just read the JSON out of the ZIP in memory."""
    package = tmp_path / "abc-hw1-0-test-suite-v3.zip"
    envelope = _envelope(
        test_steps=[{
            "order": 1, "step_type": "UPLOAD_FIRMWARE_AVRDUDE", "name": "Program", "abort_on_fail": True,
            "config_schema_version": 1,
            "config": {
                "schema_version": 1, "port": "/dev/ttyUSB0", "programmer_type": "arduino",
                "mcu": "atmega328p", "firmware_file": "main.hex",
            },
        }],
    )
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("abc-hw1-0-test-suite-v3/test-suite-definition.json", json.dumps(envelope))
        archive.writestr("abc-hw1-0-test-suite-v3/main.hex", ":00000001FF")

    suite = load_suite(package)

    assert suite.package_dir == tmp_path / "abc-hw1-0-test-suite-v3"
    extracted_firmware = suite.package_dir / "main.hex"
    assert extracted_firmware.is_file()
    assert extracted_firmware.read_text() == ":00000001FF"
    assert suite.test_steps[0].config["firmware_file"] == "main.hex"


def test_rejects_zip_package_without_a_definition_file(tmp_path):
    empty_package = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty_package, "w") as archive:
        archive.writestr("empty/readme.txt", "nothing here")

    with pytest.raises(SuiteFormatError):
        load_suite(empty_package)


def test_rejects_zip_package_with_multiple_definition_files(tmp_path):
    ambiguous_package = tmp_path / "ambiguous.zip"
    with zipfile.ZipFile(ambiguous_package, "w") as archive:
        archive.writestr("a/test-suite-definition.json", "{}")
        archive.writestr("b/test-suite-definition.json", "{}")

    with pytest.raises(SuiteFormatError):
        load_suite(ambiguous_package)


def test_rejects_unsupported_export_schema_version():
    with pytest.raises(SuiteFormatError):
        parse_suite(_envelope(export_schema_version=99))


def test_rejects_missing_required_key():
    envelope = _envelope()
    del envelope["design"]

    with pytest.raises(SuiteFormatError):
        parse_suite(envelope)


def test_sorts_steps_and_manual_checks_by_order():
    step_a = {
        "order": 1, "step_type": "DELAY", "name": "a", "abort_on_fail": False,
        "config_schema_version": 1, "config": {"schema_version": 1, "delay_ms": 1},
    }
    step_b = {
        "order": 2, "step_type": "DELAY", "name": "b", "abort_on_fail": False,
        "config_schema_version": 1, "config": {"schema_version": 1, "delay_ms": 1},
    }
    suite = parse_suite(_envelope(
        test_steps=[step_b, step_a],
        manual_checks=[{"order": 2, "text": "second"}, {"order": 1, "text": "first"}],
    ))

    assert [step.name for step in suite.test_steps] == ["a", "b"]
    assert [check.text for check in suite.manual_checks] == ["first", "second"]


def test_rejects_config_schema_version_mismatch():
    step = {
        "order": 1, "step_type": "DELAY", "name": "a", "abort_on_fail": False,
        "config_schema_version": 2, "config": {"schema_version": 1, "delay_ms": 1},
    }

    with pytest.raises(SuiteFormatError):
        parse_suite(_envelope(test_steps=[step]))


def test_include_on_docket_defaults_true_when_absent():
    """A Test Suite Package exported before issue #123 added this field has no
    include_on_docket key at all - it must still parse as "print every step", matching what it
    actually did at the time."""
    step = {
        "order": 1, "step_type": "DELAY", "name": "a", "abort_on_fail": False,
        "config_schema_version": 1, "config": {"schema_version": 1, "delay_ms": 1},
    }
    suite = parse_suite(_envelope(test_steps=[step]))

    assert suite.test_steps[0].include_on_docket is True


def test_include_on_docket_round_trips_when_present():
    step = {
        "order": 1, "step_type": "DELAY", "name": "a", "abort_on_fail": False,
        "config_schema_version": 1, "config": {"schema_version": 1, "delay_ms": 1},
        "include_on_docket": False,
    }
    suite = parse_suite(_envelope(test_steps=[step]))

    assert suite.test_steps[0].include_on_docket is False


def test_optional_notes_defaults_to_none():
    envelope = _envelope()
    del envelope["test_suite"]["notes"]

    suite = parse_suite(envelope)

    assert suite.test_suite.notes is None
