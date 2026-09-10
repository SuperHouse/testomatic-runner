"""Shared types every step executor uses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StepResult:
    """The outcome of executing one Test Step."""

    passed: bool
    message: str = ""
    measured: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    """Hardware handles, plus Test Suite Package/tool-path context, passed to every step executor.

    `package_dir` is set by `TestRunner.run()` from `suite.package_dir` (see suite.py) — the
    directory a firmware step's `firmware_file`/`images[].file` resolve relative to.

    The four `*_path` fields override the executable a firmware-upload step shells out to
    (default: the bare tool name on $PATH — see firmware.py). This is the extension point a
    caller sets from its own per-device configuration (e.g. testomatic-ui, once it grows a
    settings page for this); it's deliberately separate from the serial port/debug-probe fields,
    which stay suite-side (`config["port"]` etc., as defined by Register) — see the open question
    tracked as Register issue #122, not resolved here.

    `verbose` (set via `TestRunner(...)`/`cli.py`'s `--verbose` flag) asks executors that shell
    out or run arbitrary code (firmware.py, python_step.py) to stream their subprocess/stdout
    output live to the console as it happens, in addition to always capturing it into
    `StepResult.measured["output"]` regardless of this flag.
    """

    chassis: Any
    test_module: Any = None
    package_dir: Path | None = None
    avrdude_path: str | None = None
    esptool_path: str | None = None
    openocd_path: str | None = None
    stm32cubeprogrammer_path: str | None = None
    verbose: bool = False
