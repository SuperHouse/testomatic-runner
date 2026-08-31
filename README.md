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
python -m testomatic run path/to/suite-hw1-test-suite-v1.zip
```

`run` accepts either a Test Suite Package `.zip` or a bare `test-suite-definition.json` file.

`import testomatic_io` (and therefore `python -m testomatic run`) only works on real Raspberry Pi
hardware — `testomatic-io` is installed via the `pi` extra rather than as a core dependency, since
one of its dependencies (`gpiod`) has a native extension that only builds on Linux. See
[TEST_RUNNER_PLAN.md](TEST_RUNNER_PLAN.md) for what's implemented, what's stubbed, and what's
still unverified on real hardware.

## Repo layout

- `testomatic/suite.py` — parses/validates a Test Suite Definition (JSON) into dataclasses.
- `testomatic/steps/` — one executor module per `step_type`, registered in `steps/registry.py`.
- `testomatic/runner.py` — `TestRunner.run(suite)` executes `test_steps` in order, and
  `format_report()` renders the result plus the suite's `manual_checks`.
- `testomatic/cli.py` / `__main__.py` — `python -m testomatic run <suite.zip|suite.json>`.
- `tests/conftest.py` — fake `Chassis`/`Power`/`Beeper`/`Iomod` doubles standing in for real
  `testomatic-io` hardware.
- `test-suite-package.md` — reference documentation for the Test Suite Package (ZIP) layout and
  the `test-suite-definition.json` format `suite.py` parses.
- `aqs-hw41-test-suite-v1.zip` — a real sample Test Suite Package, used as a test fixture.
- `TEST_RUNNER_PLAN.md` — the staged implementation plan and phase checklist.
