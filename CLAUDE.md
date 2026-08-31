# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`testomatic-runner` is the test-runner software for the
[Testomatic](https://testomatic.io/) PCB test jig system. It's a `testomatic` Python package that
parses a Test Suite Package delivered by Register and executes its Test Steps in order against
real hardware, via `testomatic-io`.

## Terminology

The Testomatic repo's `README.md` **Terminology** section is the controlled vocabulary for this
project (Chassis, Design, Device, Test Module, Test Item, Test Step, Manual Check, Test Suite,
Test Run, Test Result, Register, Test Runner, **Test Suite Definition**, **Test Suite Package**).
Use those terms as defined there rather than looser language like "export."

- **Test Suite Definition** — a JSON document containing a Test Suite's Test Steps and Manual
  Checks. Deliberately not "Test Suite Export": it is delivered as `test-suite-definition.json`
  inside a Test Suite Package (see below), not as a stand-alone download — a future goal is this
  runner discovering and fetching Test Suite Definitions from a Register API instead.
- **Test Suite Package** — a Test Suite Definition plus the additional artifacts it references
  and needs to run (e.g. firmware binaries for `UPLOAD_FIRMWARE`). Register delivers this as a ZIP
  archive (filename pattern `{sku}-hw{hw_version}-test-suite-v{version}.zip`, its contents all
  inside one top-level folder of that same name, holding `test-suite-definition.json` plus any
  referenced files — so extracting it can never scatter loose files into whatever directory it
  lands in) — see `test-suite-package.md` for the format.

## Ecosystem — three sibling repos, each with its own CLAUDE.md

This runner is one part of a three-repo system. Read the other two repos' `CLAUDE.md` files
directly when working on anything that crosses a boundary — don't rely on summaries here going
stale:

- **This repo (`testomatic-runner`)** — parses a Test Suite Package and executes its Test Steps.
- **`testomatic-io`** (`~/Dropbox/src/testomatic-io`) — the Python hardware abstraction layer this
  runner drives the chassis through. Its `Chassis`/`TestModule` facade classes (`chassis.iomod`,
  `chassis.power`, `chassis.button`, `chassis.beeper`, etc.) map onto the GPIO/I2C wiring
  documented in the `Testomatic` repo's `PinAllocation.md` — e.g. `chassis.power.rail_5v()`
  against `IO27`, `chassis.button` against `IO20`. It only imports on real Raspberry Pi hardware
  (Adafruit Blinka does platform detection at import time), which is why it's installed here via
  the `pi` extra rather than as a core dependency.
- **`Testomatic`** (`~/Dropbox/src/Testomatic`) — the physical chassis/PCB/Test Module hardware
  design (Fusion 360, EAGLE/KiCAD, DXF, STL) this runner and `testomatic-io` drive. Also holds
  `PinAllocation.md` and the colour-sensor hardware (`ColourSensor/`) that the deferred
  `LED_SPECTRAL_READING` step type will eventually use.
- **Register** (`/Users/jon/Dropbox/src/register-macbook`, Django app under `pyproj/`) — the
  central production/test database. Its `testing` app defines `TestSuite`/`TestStep`/
  `ManualCheck` models, staff-edited per PCB `Design`, and currently serves a Test Suite Package
  (a ZIP containing `test-suite-definition.json`) for download, in the format documented in
  `test-suite-package.md` (that file, and the sample fixture `aqs-hw41-test-suite-v1.zip`, both
  originate from Register's `docs/api/test-suite-export.md` and
  `testing.views.test_suite_download`/`_serialize_test_suite` — keep this repo's copy in sync if
  that format changes on the Register side). Register's `testing.TestStep.STEP_TYPE_CHOICES` is
  the authoritative list of step types; it currently has placeholder choice sets
  (`POWER_RAIL_CHOICES`, `IOMOD_CHOICES`) explicitly pending fuller integration with this project.

**The intended pipeline:** a Test Suite is authored/versioned in Register against a `Design` →
conveyed to this repo as a Test Suite Package (today: ZIP download containing
`test-suite-definition.json`; a future goal is this runner discovering and fetching a Test Suite
Definition directly from a Register API) → this repo parses it and executes each `TestStep` in
order → each step's hardware action (drive a rail, read an IOMOD pin, read the colour sensor,
etc.) is carried out via `testomatic-io`'s `Chassis`/`TestModule` API. The staged implementation
plan, including what's done vs. still pending real-hardware verification, lives in
`TEST_RUNNER_PLAN.md` — check it (and its phase checklist) before starting runner work.

## Package layout

- `testomatic/suite.py` — parses/validates a Test Suite Definition (JSON) into dataclasses
  (`load_suite(path)` → `TestSuiteFile`); `path` may be a Test Suite Package `.zip` (its wrapped
  `test-suite-definition.json` is located by filename suffix, since it sits inside a top-level
  folder named after the package) or a bare Test Suite Definition JSON file directly — see
  `test-suite-package.md` below for the format.
- `testomatic/steps/` — one executor module per `step_type` (`delay.py`, `beep.py`,
  `power.py`, `iomod.py`, `python_step.py`, `operator_intervention.py`, plus the deferred stubs
  `firmware.py`/`led_spectral.py` — see `TEST_RUNNER_PLAN.md`'s "Deferred work"). Each executor is
  a plain `(config, context) -> StepResult` function registered against its `step_type` string in
  `registry.STEP_EXECUTORS` via `@register_step(...)` (`registry.py`) — dict-of-functions dispatch,
  not a class hierarchy, since (unlike `testomatic-io`'s IOMOD chip drivers) there's no runtime
  probing involved: the `step_type` is already known from the parsed JSON.
- `testomatic/runner.py` — `TestRunner.run(suite)` executes `test_steps` in order via the
  registry, stops and turns off all three power rails immediately if an `abort_on_fail` step fails
  (the one case where the runner touches rails on its own initiative — see `TEST_RUNNER_PLAN.md`),
  and returns a `RunReport`; `format_report()` renders it plus the suite's `manual_checks`.
- `testomatic/cli.py` / `__main__.py` — `python -m testomatic run <suite.zip|suite.json>`
  entry point; accepts either a Test Suite Package ZIP or a bare Test Suite Definition JSON file,
  since it just forwards its argument to `suite.load_suite()`. Only importable/runnable on real
  Raspberry Pi hardware (imports `testomatic_io` at call time) — confirmed working on a real
  chassis for `BEEP`/`READ_RAIL_VOLTAGE`; see `TEST_RUNNER_PLAN.md` for what's still unverified.
- `tests/conftest.py` — `FakeChassis`/`FakePower`/`FakeBeeper`/`FakeIomod` doubles (as pytest
  fixtures `chassis`/`test_module`/`context`) standing in for real `testomatic-io` hardware, since
  step executors only ever duck-type against whatever `chassis` object they're given.
- `test-suite-package.md` — reference documentation (copied from the Register project) describing
  the Test Suite Package (ZIP) layout and the `test-suite-definition.json` format `suite.py`
  parses.
- `aqs-hw41-test-suite-v1.zip` — a real sample Test Suite Package in that format, used as a test
  fixture.
- `TEST_RUNNER_PLAN.md` — the staged implementation plan: what's done, what's stubbed pending
  design decisions, and the phase checklist. Keep it updated as phases land.

## Working here

```bash
pip install -e ".[dev]"
pytest
```
- To run a single test: `pytest tests/test_steps.py::test_beep_alternates_beep_and_silence`
- `testomatic-io` is on PyPI but lives in the `pi` extra (`pip install -e ".[pi]"`), not core
  dependencies: it pulls in `gpiod`, whose native extension only builds on Linux — a core
  dependency broke `pip install -e ".[dev]"` outright on macOS. Install the `pi` extra on the
  Raspberry Pi itself to actually run `cli.py`; see `TEST_RUNNER_PLAN.md` for detail.

### The Test Suite Definition format (`test-suite-package.md`)

This is the key contract for any test-runner code added here. A Test Suite Definition is one JSON
object with four top-level keys: `design`, `test_suite`, `test_steps` (array, execution order),
and `manual_checks` (array). Each `test_steps` entry has a fixed outer shape
(`order`, `step_type`, `name`, `abort_on_fail`, `config_schema_version`, `config`) with a
`step_type`-specific `config` payload. Known step types: `DELAY`, `UPLOAD_FIRMWARE`, `BEEP`,
`READ_RAIL_VOLTAGE`, `READ_RAIL_CURRENT`, `CONTROL_POWER_RAIL`, `PYTHON`, `IOMOD_ANALOG_READ`,
`IOMOD_DIGITAL_READ`, `IOMOD_DIGITAL_WRITE`, `IOMOD_ANALOG_WRITE`, `LED_SPECTRAL_READING`,
`OPERATOR_INTERVENTION`. Optional `config` fields are omitted rather than null when unset — a
consumer must apply its own default, not expect `null`/empty. `export_schema_version` versions
the envelope shape; each step's `config_schema_version` independently versions that step type's
own config shape — don't conflate the two when adding parsing logic.

## Hardware I/O reference

Raspberry Pi GPIO assignments on the Testomatic main board are documented in the `Testomatic`
repo's `PinAllocation.md` — relevant when writing control code here:

- I2C bus 0 (IO0/IO1): HAT EEPROM, on the Testomatic main board
- I2C bus 1 (IO2/IO3): general-purpose, for Test Module peripherals
- SPI: CE0/CE1 = IO8/IO7, MISO/MOSI/SCK = IO9/IO10/IO11
- IO18: tester reset (active low)
- IO20: external button / footswitch input (active low)
- IO23: piezo buzzer (active high)
- IO24/IO25: available on the tester breakout, usable as extra SPI CE lines
- 7 GPIO blocks of 8 pins each (IOMOD A–G) are exposed via I2C I/O-expander modules
  (AD5593R-based), each pin independently configurable as digital in/out or 12-bit ADC/DAC
