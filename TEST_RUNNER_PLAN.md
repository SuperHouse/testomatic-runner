# Test Runner — Implementation Plan

Status: Phases 1, 2, 4 and 5 implemented and unit-tested (against fake hardware, see Testing
below). Phase 3's code is written and unit-tested the same way; `cli.py` has now been run against
a real chassis and confirmed working for `BEEP` and `READ_RAIL_VOLTAGE`, but the rest of Phase 3
(`CONTROL_POWER_RAIL`, `READ_RAIL_CURRENT`, both `IOMOD_*` step types) is **still unverified on
real hardware** — and so is all of Phase 5 (`UPLOAD_FIRMWARE_*`): the tool command lines are a
first-pass best effort against each tool's own documented CLI, not yet run against a real
programmer/DUT. Phase 6 remains a deferred stub. Staged implementation — check off phases as
they land.

## Scope for v1

Parse a Test Suite Definition (the `test-suite-definition.json` inside a Test Suite Package —
format documented in [test-suite-package.md](test-suite-package.md)) and execute its `test_steps`
in order against real hardware via `testomatic-io` (`~/Dropbox/src/testomatic-io`), respecting
`abort_on_fail`, and print a pass/fail report. `manual_checks` are surfaced to the operator, not
executed. The colour-sensor step is stubbed for now (see below) — everything else, including
firmware upload as of Phase 5, maps onto either `testomatic-io`'s existing API or a subprocess
call to an external upload tool.

`suite.py`'s `load_suite()` accepts either a Test Suite Package `.zip` or a bare Test Suite
Definition JSON file — dispatched on the path's extension. For a `.zip`, it locates
`test-suite-definition.json` by filename suffix (it sits inside a top-level folder named after the
package, not at the archive root — see `test-suite-package.md`) rather than assuming a fixed path,
so it doesn't care whether the wrapping folder name matches the archive's own name; it then
extracts the whole archive alongside the ZIP (`path.parent/<top-level-folder>/...`, re-extracted
on every load so it stays in sync if the same path is loaded again after the underlying package
changes) and returns that folder as `TestSuiteFile.package_dir`. `cli.py`'s `run` command accepts
either form the same way, since it just forwards its argument to `load_suite()`. `package_dir` is
what `TestRunner.run()` copies onto `ExecutionContext.package_dir` before executing any steps —
see Phase 5 below for how the `UPLOAD_FIRMWARE_*` executors resolve `firmware_file`/`images` from
it.

## Package layout

Lives in its own repo (`testomatic-runner`, sibling to `testomatic-io`), using the same flat
(non-`src/`) package layout `testomatic-io` uses:

```
testomatic-runner/
  pyproject.toml          # [build-system] + dev extra (pytest) — done. testomatic-io is a `pi`
                           # extra, not a core dependency, see pyproject.toml changes below
  testomatic/
    suite.py              # dataclasses + parsing/validation for the JSON envelope — done
    steps/
      base.py             # StepResult + ExecutionContext dataclasses — done
      registry.py          # STEP_EXECUTORS: dict[str, StepExecutor] + @register_step — done
      delay.py, beep.py, power.py, iomod.py, python_step.py, operator_intervention.py  # done
      firmware.py           # 4 UPLOAD_FIRMWARE_* executors, one per tool — done, unverified on real hardware
      led_spectral.py       # stub for now — see Deferred work below — done
    runner.py              # TestRunner: iterate steps, call executor, honour abort_on_fail, build report — done
    cli.py                 # entry point, `python -m testomatic run suite.zip|suite.json` — done,
                             # confirmed working on real hardware for BEEP/READ_RAIL_VOLTAGE
    __main__.py             # `python -m testomatic` dispatch — done
  tests/
    conftest.py             # FakePower/FakeBeeper/FakeIomod/FakeChassis fixtures — done
    test_suite_parsing.py  # exercises aqs-hw41-test-suite-v1/test-suite-definition.json as a fixture — done
    test_steps.py           # one test module per executor, against the fake hardware — done
    test_runner.py          # abort-on-fail/soft-fail/unknown-step-type orchestration — done
```

`steps/registry.py` mirrors the driver-registry pattern `testomatic-io` already uses for IOMOD
chips (`DRIVERS` + `probe()` in `testomatic_io/iomod/drivers/__init__.py`), adapted for dispatch
by a known key (`step_type`) rather than runtime probing — so it's a dict of plain functions
(`STEP_EXECUTORS: dict[str, StepExecutor]`), not a class hierarchy. The original idea of a
`StepExecutor` ABC was dropped since there's no per-executor state or polymorphic instantiation
to justify a class — every executor is a stateless `(config, context) -> StepResult` function.
`operator.py` was renamed `operator_intervention.py` to avoid shadowing the stdlib `operator`
module.

## Step type → `testomatic-io` mapping

| `step_type` | Executor calls |
|---|---|
| `DELAY` | `time.sleep(delay_ms / 1000)` |
| `BEEP` | see BEEP timing below — not a plain repeated `beep()` call |
| `CONTROL_POWER_RAIL` | dispatch `rail` (`3.3V`/`5V`/`12V`) → `chassis.power.rail_3v3/5v/12v(action == 'ON')` |
| `READ_RAIL_VOLTAGE` | `chassis.power.read_<rail>().voltage`, check `min_v`/`max_v` |
| `READ_RAIL_CURRENT` | `chassis.power.read_<rail>().current`, check `min_ma`/`max_ma` |
| `IOMOD_DIGITAL_READ` / `_WRITE` | `chassis.iomod.digital_read/write(iomod, pin, ...)` |
| `IOMOD_ANALOG_READ` / `_WRITE` | `chassis.iomod.analog_read/write(iomod, pin, ...)` |
| `OPERATOR_INTERVENTION` | print `message`, block on operator confirmation (CLI `input()` for v1) |
| `PYTHON` | `exec()` the code string with `chassis`/`test_module` bound in its namespace |
| `UPLOAD_FIRMWARE_AVRDUDE` | `subprocess.Popen(["avrdude", "-c", programmer_type, "-p", mcu, "-P", port, ..., "-U", f"flash:w:{firmware_file}:i"])` |
| `UPLOAD_FIRMWARE_ESPTOOL` | `subprocess.Popen(["esptool.py", "--chip", chip, "--port", port, ..., "write-flash", addr1, file1, addr2, file2, ...])` |
| `UPLOAD_FIRMWARE_OPENOCD` | `subprocess.Popen(["openocd", "-f", interface_config, "-f", target_config, ..., "-c", f"program {firmware_file} ... verify reset exit"])` |
| `UPLOAD_FIRMWARE_STM32CUBEPROGRAMMER` | `subprocess.Popen(["STM32_Programmer_CLI", "-c", f"port={connection_interface} ...", "-w", firmware_file, ..., "-v", "-rst"])` |
| `LED_SPECTRAL_READING` | stub for now — prints `"LED test"` and returns a pass. See Deferred work below |

### BEEP timing

`BEEP` inserts a silent gap of `duration_ms` between each beep, not just `count` back-to-back
beeps — e.g. `duration_ms=100, count=3` is beep 100ms, silence 100ms, beep 100ms, silence 100ms,
beep 100ms (silence only *between* beeps, none trailing after the last one). Implementation:
alternate `chassis.beeper.beep(duration_ms / 1000)` and `time.sleep(duration_ms / 1000)` for
`count` beeps, skipping the trailing sleep after the last one.

### Power rail control is Test-Suite-only, with one safety exception

The runner must never turn a power rail on/off itself outside of an explicit `CONTROL_POWER_RAIL`
step — rail state is entirely the Test Suite's responsibility, and step ordering already encodes
whatever preconditions a `READ_RAIL_VOLTAGE`/`READ_RAIL_CURRENT` step needs (e.g. an earlier
`CONTROL_POWER_RAIL` step having turned that rail on) — the runner doesn't need to enforce that
itself.

**Exception:** on an abort-on-fail (a step with `abort_on_fail: true` fails), the runner must immediately
turn off all three rails — `chassis.power.rail_3v3(False)`, `rail_5v(False)`, `rail_12v(False)` —
before stopping, regardless of what the runner believes their current state to be and regardless
of what step is executing. This is a safety measure (protecting the DUT/chassis on abort), not
part of normal step execution, so it belongs in `runner.py`'s abort-on-fail handling, not in
`power.py`'s `CONTROL_POWER_RAIL` executor.

## Deferred work (stubbed for v1)

1. **`LED_SPECTRAL_READING`** needs the VEML3328SL colour sensor (`ColourSensor/` in the sibling
   `Testomatic` repo),
   reached through an I2C address plus an optional mux channel/address. `testomatic-io`'s
   `Chassis` facade has no colour-sensor subsystem yet — only `iomod`, `power`, `interrupts`,
   `button`, `beeper`, `hat_eeprom`. A driver for this sensor already exists elsewhere and will be
   wired in later, either as a `chassis.colour_sensor` subsystem in `testomatic-io` (consistent
   with how it wraps INA260/EEPROM via `i2c_probe.py`) or directly in this executor — not decided
   yet. **For now**, `steps/led_spectral.py` is a stub that just prints `"LED test"` and returns a
   pass `StepResult`, so suites containing this step type can still run end-to-end.

## `UPLOAD_FIRMWARE_*` (Phase 5 — implemented, unverified on real hardware)

Register split the single `UPLOAD_FIRMWARE` step type into four tool-specific ones
(`UPLOAD_FIRMWARE_AVRDUDE`/`_ESPTOOL`/`_OPENOCD`/`_STM32CUBEPROGRAMMER`) and now attaches the
actual firmware bytes to the step (`TestStepAsset`, bundled into the Test Suite Package — see
test-suite-package.md), which unblocked the two things that kept this deferred before: file
association and tool dispatch. `steps/firmware.py` now has one executor per tool, each shelling
out via `subprocess.Popen()` — see the step type → command mapping above.

- **File resolution**: `firmware_file`/`images[].file` are resolved against
  `context.package_dir`, which `TestRunner.run()` copies from `suite.package_dir` at the start of
  every run — see `suite.py`'s `load_suite()`/`_extract_package()` above. A step whose file is
  missing (not yet attached in Register, or missing from the package) fails cleanly with a
  message naming the problem, rather than crashing.
- **Tool executable paths** are configurable per `ExecutionContext`
  (`avrdude_path`/`esptool_path`/`openocd_path`/`stm32cubeprogrammer_path`), set via
  `TestRunner(...)`'s matching keyword arguments (also exposed as `cli.py`'s `--avrdude-path`
  etc.) and defaulting to the bare tool name on `$PATH` when unset. This is the extension point a
  caller uses to point at a tool that isn't on `$PATH` — the natural next step is a per-device
  settings page in testomatic-ui that sets these when it constructs its own `TestRunner`.
- **Serial port / debug-probe identification** (avrdude's/esptool's `port`, OpenOCD's
  `adapter_serial`, STM32CubeProgrammer's `port`) stays entirely suite-side — read straight out
  of `config`, exactly as Register defines it, with no tester-side override or mapping layer.
  Whether it should instead (or additionally) be tester-side config is an open question, tracked
  as Register issue #122 (see that repo's own memory/notes) — **deliberately deferred**: the plan
  is to exercise the system end-to-end using this simpler suite-side-only approach first, and
  revisit #122 only if that turns out not to be enough in practice.
- **Command lines are unverified.** Each tool's flags were built from its own documented CLI, not
  confirmed against a real chassis/programmer yet — treat the mapping above as a first pass to be
  corrected once real hardware is available (same caveat `power.py`/`iomod.py` still carry for
  their own unverified step types).
- **Verbose output** — Register issue #1 (this project's tracker). Each firmware executor's tool
  output is always captured in full into `StepResult.measured["output"]` (regardless of
  `context.verbose`), so a caller like testomatic-ui getting a `RunReport` back in-process (see
  `run()` in `testomatic-ui`'s `test_suites.views._run_test_suite()`) already has it available for
  its own storage/display, no separate API needed. `context.verbose` (set via `TestRunner(...)`'s
  `verbose=` kwarg / `cli.py`'s `--verbose` flag) additionally streams that same output to stdout
  live as the tool runs (`subprocess.Popen` read line-by-line, not `subprocess.run`, so output is
  available before the process exits) and includes it in `format_report()`'s final text. The
  `PYTHON` step follows the same convention — `exec()`'s stdout/stderr are always captured into
  `measured["output"]`, and echoed live to the console only when `context.verbose` is set.

## Runner semantics

- `TestRunner.run(suite, chassis, test_module)` executes steps by `order`, collecting a
  `StepResult` per step.
- On a step result of failure: if `abort_on_fail` is `True`, turn off all three power rails (see
  Power rail control above) and stop immediately; otherwise continue and record the failure.
- `config_schema_version` should be checked per step (`== 1` for now) so a future format change
  fails loudly instead of misreading fields — matches the guidance in `test-suite-package.md` about
  not conflating it with `export_schema_version`.
- Optional `config` fields: apply the documented defaults (e.g. `BEEP.count` defaults to `1` when
  absent) rather than assuming `null`.
- End-of-run: print a summary (step name, pass/fail, measured value where relevant) and list
  `manual_checks` for the operator to work through by hand.

## Testing without a Pi

Implemented more simply than originally planned: step executors never import `testomatic_io`
themselves — they only call methods on whatever `chassis`/`test_module` object `runner.py` was
given, via plain duck typing. So instead of stubbing `board`/`tca9548a`/`gpiod`/`busio` in
`sys.modules` before importing the real package, `tests/conftest.py` defines hand-rolled
`FakeChassis`/`FakePower`/`FakeBeeper`/`FakeIomod`/`FakeTestModule` classes matching
`testomatic-io`'s public API shape, exposed as pytest fixtures (`chassis`, `test_module`,
`context`). That stubbing approach is still exactly what `cli.py` will need when it's actually
exercised on the Pi (its `from testomatic_io import Chassis, TestModule` only succeeds on real
hardware — see the `pi` extra note below, it's not just an import-time platform check, the
package can't even be *installed* on macOS) — just not needed for unit-testing the
runner/executors themselves.
`suite.py`'s JSON parsing/validation needs no stubbing at all — tested directly against both the
extracted `aqs-hw41-test-suite-v1/test-suite-definition.json` and the packaged
`aqs-hw41-test-suite-v1.zip`.

## `pyproject.toml` changes made

- `[build-system]` (setuptools, flat package layout matching `testomatic-io`) — done
- `pytest` as a dev extra (`pip install -e ".[dev]"`) — done
- `python_classes = ["*Tests"]` under `[tool.pytest.ini_options]` — added so pytest doesn't try
  (and warn about failing) to collect `TestStep`/`TestSuiteFile`/`TestRunner` etc. as test classes
  just because of the `Test` prefix; they're plain domain dataclasses, not test classes
- `testomatic-io>=0.1.0` is on PyPI, but is a `pi` extra (`pip install -e ".[pi]"`), **not** a core
  dependency: it pulls in `gpiod` (libgpiod's Python bindings), which has a native C extension
  that only builds on Linux (needs `linux/const.h`) — installing it as a core dependency broke
  `pip install -e ".[dev]"` outright on macOS (a wheel build failure, confirmed by trying it), not
  just an import-time platform check. Install the `pi` extra on the Raspberry Pi itself when
  `cli.py`'s real-hardware path is actually exercised.
- **Not added**: `click`/`typer` — `cli.py` uses stdlib `argparse`, which was enough for the one
  `run <suite_path>` subcommand

## Staged order of work

- [x] **Phase 1** — `suite.py` parsing/validation against the sample JSON. No hardware needed,
      fully testable now.
- [x] **Phase 2** — `steps/base.py` + registry + the hardware-free executors (`DELAY`, `PYTHON`,
      `OPERATOR_INTERVENTION`) against a mocked `Chassis`.
- [ ] **Phase 3** — `power.py` and `iomod.py` are written and unit-tested against fake hardware
      (see Testing above), plus the `firmware.py`/`led_spectral.py` stubs (print-and-pass) so full
      suites containing those step types can run end-to-end. `READ_RAIL_VOLTAGE` (`power.py`) is
      confirmed working on the real chassis; `CONTROL_POWER_RAIL`/`READ_RAIL_CURRENT` and both
      `IOMOD_*` step types (`iomod.py`) are **still unverified** against real hardware.
- [x] **Phase 4** — `runner.py` orchestration + abort-on-fail/report logic, including the all-rails-off
      safety behaviour on abort-on-fail — implemented and unit-tested, and `BEEP`/`READ_RAIL_VOLTAGE`
      have now run successfully end-to-end via `cli.py` on a real chassis.
- [x] **Phase 5** — `UPLOAD_FIRMWARE_AVRDUDE`/`_ESPTOOL`/`_OPENOCD`/`_STM32CUBEPROGRAMMER`
      implemented and unit-tested against a mocked `subprocess.Popen()`, including live/verbose
      output streaming (issue #1); **still unverified against real hardware/tools** — see
      "`UPLOAD_FIRMWARE_*`" above.
- [ ] **Phase 6** — `LED_SPECTRAL_READING`, once the existing sensor driver is wired in (either via
      a `testomatic-io` `chassis.colour_sensor` subsystem or directly in this executor).
