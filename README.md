# testomatic-runner

The test runner for the [Testomatic](https://testomatic.io/) PCB test jig system: it parses a
Test Suite Package produced by Register and executes its Test Steps in order against real
hardware, via the [`testomatic-io`](https://github.com/SuperHouse/testomatic-io) hardware
abstraction layer.

## Overview

Testomatic's test pipeline has four parts, each in its own repo:

1. **Register** — a Test Suite is authored/versioned there, against a PCB `Design`.
2. **[`testomatic-ui`](https://github.com/SuperHouse/testomatic-ui)** — the on-device touchscreen
   UI. Downloads and caches Test Suite Packages from Register so a device isn't dependent on
   Register being reachable to run a suite it already has.
3. **This repo (`testomatic-runner`)** — receives a Test Suite Package (a ZIP containing
   `test-suite-definition.json`, documented in [test-suite-package.md](test-suite-package.md)),
   parses it with `testomatic.suite.load_suite()`, and executes each Test Step in order with
   `testomatic.runner.TestRunner`.
4. **[`testomatic-io`](https://github.com/SuperHouse/testomatic-io)** — carries out each step's
   hardware action (drive a power rail, read an IOMOD pin, beep, etc.) through its `Chassis`/
   `TestModule` API.

The physical chassis, PCB, and Test Module hardware this runner drives live in the sibling
[`Testomatic`](https://github.com/SuperHouse/Testomatic) repo.

## Usage

```bash
pip install -e ".[dev]"   # unit tests, no hardware required
pytest

# On a Raspberry Pi wired to a Testomatic chassis:
pip install -e ".[pi]"    # pulls in testomatic-io
testomatic run path/to/suite-hw1-test-suite-v1.zip
```

`import testomatic_io` (and therefore running a suite for real) only works on real Raspberry Pi
hardware — `testomatic-io` is installed via the `pi` extra rather than as a core dependency, since
one of its dependencies (`gpiod`) has a native extension that only builds on Linux. See
[TEST_RUNNER_PLAN.md](TEST_RUNNER_PLAN.md) for what's implemented, what's stubbed, and what's
still unverified on real hardware.

### CLI

`pip install -e ".[pi]"` registers a `testomatic` console script (`python -m testomatic` works
identically, per `__main__.py`). It's the same `load_suite()` → `TestRunner.run()` →
`format_report()` path `testomatic-ui` drives in-process — this is that path exposed standalone,
with no Django project or Register connection required.

```
testomatic run <suite.zip|suite.json>
    [--avrdude-path PATH]
    [--esptool-path PATH]
    [--openocd-path PATH]
    [--stm32cubeprogrammer-path PATH]
```

- `suite_path` — a downloaded Test Suite Package `.zip`, or a bare `test-suite-definition.json`
  (see [test-suite-package.md](test-suite-package.md)) for a suite you're editing/testing by hand.
- The four `--*-path` options override the executable an `UPLOAD_FIRMWARE_*` step shells out to.
  Each defaults to the bare tool name on `$PATH` (`avrdude`, `esptool.py`, `openocd`,
  `STM32_Programmer_CLI`) when omitted — pass a path only if that tool isn't on `$PATH` or you
  need a specific one. These are the only device-specific settings the runner takes; everything
  else (serial port, adapter serial, rail assignments, etc.) comes from the suite itself.
- Prints the run report (and any `manual_checks`) to stdout via `format_report()`, and exits `0` if
  the suite passed, `1` otherwise — scriptable in a shell loop or CI-style harness.

Example with an overridden esptool location:

```bash
testomatic run suite-hw1-test-suite-v1.zip --esptool-path /opt/homebrew/bin/esptool.py
```

## Repo layout

- `testomatic/suite.py` — parses/validates a Test Suite Definition (JSON) into dataclasses.
- `testomatic/steps/` — one executor module per `step_type`, registered in `steps/registry.py`.
- `testomatic/runner.py` — `TestRunner.run(suite)` executes `test_steps` in order, and
  `format_report()` renders the result plus the suite's `manual_checks`.
- `testomatic/cli.py` / `__main__.py` — the `testomatic` console script (see [CLI](#cli) above).
- `tests/conftest.py` — fake `Chassis`/`Power`/`Beeper`/`Iomod` doubles standing in for real
  `testomatic-io` hardware.
- `test-suite-package.md` — reference documentation for the Test Suite Package (ZIP) layout and
  the `test-suite-definition.json` format `suite.py` parses.
- `aqs-hw41-test-suite-v1.zip` — a real sample Test Suite Package, used as a test fixture.
- `TEST_RUNNER_PLAN.md` — the staged implementation plan and phase checklist.
