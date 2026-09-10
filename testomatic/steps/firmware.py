"""UPLOAD_FIRMWARE_* steps: flash firmware onto the DUT via avrdude, esptool.py, OpenOCD, or
STM32CubeProgrammer — one executor per tool, since each connects to and addresses the target
differently. See test-suite-package.md for each step type's config fields.

Firmware bytes are resolved from the Test Suite Package: `context.package_dir` (set by
`TestRunner.run()` from `suite.package_dir`, itself set by `suite.load_suite()` — see suite.py)
is the directory `firmware_file`/`images[].file` are resolved relative to.

Tool executable paths are configurable per-`ExecutionContext` (`context.avrdude_path` etc., set
via `TestRunner(...)`/`cli.py`'s `--*-path` options — see base.py), defaulting to the bare tool
name on `$PATH` when unset. This is the extension point a caller (e.g. testomatic-ui, once it
grows a per-device settings page) uses to point at a tool that isn't on `$PATH`. Serial port /
debug-probe identification, by contrast, stays entirely suite-side (`config["port"]` etc., as
defined by Register) for now — see the open question tracked as Register issue #122 about
whether that should instead be tester-side config. Deliberately not resolved here: left until
the system has been exercised end-to-end using the current suite-side approach.

**Unverified against real hardware.** The exact command-line flags below are a first-pass best
effort from each tool's own documented CLI, not yet confirmed against a real chassis — see
TEST_RUNNER_PLAN.md's Phase 5 checklist.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .base import ExecutionContext, StepResult
from .registry import register_step


def _resolve_file(context: ExecutionContext, filename: str) -> tuple[Path | None, str | None]:
    """Resolves `filename` against `context.package_dir`. Returns `(path, None)` on success, or
    `(None, error_message)` if it can't be resolved — an ordinary "file not attached/found" state
    a caller turns straight into a failing `StepResult`, not an exceptional one."""
    if context.package_dir is None:
        return None, f"cannot resolve {filename!r}: no Test Suite Package directory available"
    path = context.package_dir / filename
    if not path.is_file():
        return None, f"{filename!r} not found in Test Suite Package (expected at {path})"
    return path, None


def _run_tool(command: list[str], tool_label: str, context: ExecutionContext) -> StepResult:
    """Runs a tool's command line, turning its exit code and output into a StepResult.

    Output is always captured in full into the result's `measured["output"]` (for callers such
    as testomatic-ui to store/display later), and when `context.verbose` is set it's also
    streamed to stdout line-by-line as the tool runs, rather than only appearing once the tool
    exits — useful for a long-running avrdude/esptool/openocd/STM32CubeProgrammer invocation.
    """
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
    except FileNotFoundError as exc:
        return StepResult(passed=False, message=f"{tool_label} not found: {exc}")

    lines = []
    for line in process.stdout:
        lines.append(line)
        if context.verbose:
            print(line, end="")
    process.wait()

    output = "".join(lines).strip()
    last_line = output.splitlines()[-1] if output else ""
    suffix = f": {last_line}" if last_line else ""

    if process.returncode == 0:
        return StepResult(passed=True, message=f"{tool_label} succeeded{suffix}", measured={"output": output})
    return StepResult(
        passed=False,
        message=f"{tool_label} exited {process.returncode}{suffix}",
        measured={"output": output},
    )


@register_step("UPLOAD_FIRMWARE_AVRDUDE")
def execute_avrdude(config: dict, context: ExecutionContext) -> StepResult:
    firmware_file = config.get("firmware_file")
    if not firmware_file:
        return StepResult(passed=False, message="No firmware file attached to this step")
    path, error = _resolve_file(context, firmware_file)
    if error:
        return StepResult(passed=False, message=error)

    command = [
        context.avrdude_path or "avrdude",
        "-c", config["programmer_type"],
        "-p", config["mcu"],
        "-P", config["port"],
    ]
    if config.get("baud_rate"):
        command += ["-b", str(config["baud_rate"])]
    command += ["-U", f"flash:w:{path}:i"]

    return _run_tool(command, "avrdude", context)


@register_step("UPLOAD_FIRMWARE_ESPTOOL")
def execute_esptool(config: dict, context: ExecutionContext) -> StepResult:
    images = config.get("images")
    if not images:
        return StepResult(passed=False, message="No firmware images attached to this step")

    flash_args = []
    for image in images:
        path, error = _resolve_file(context, image["file"])
        if error:
            return StepResult(passed=False, message=error)
        flash_args += [image["address"], str(path)]

    command = [
        context.esptool_path or "esptool.py",
        "--chip", config["chip"],
        "--port", config["port"],
    ]
    if config.get("baud_rate"):
        command += ["--baud", str(config["baud_rate"])]
    command += ["write-flash", *flash_args]

    return _run_tool(command, "esptool.py", context)


@register_step("UPLOAD_FIRMWARE_OPENOCD")
def execute_openocd(config: dict, context: ExecutionContext) -> StepResult:
    firmware_file = config.get("firmware_file")
    if not firmware_file:
        return StepResult(passed=False, message="No firmware file attached to this step")
    path, error = _resolve_file(context, firmware_file)
    if error:
        return StepResult(passed=False, message=error)

    command = [
        context.openocd_path or "openocd",
        "-f", config["interface_config"],
        "-f", config["target_config"],
    ]
    if config.get("adapter_serial"):
        command += ["-c", f"adapter serial {config['adapter_serial']}"]

    program_command = f"program {path}"
    if config.get("flash_address"):
        program_command += f" {config['flash_address']}"
    program_command += " verify reset exit"
    command += ["-c", program_command]

    return _run_tool(command, "openocd", context)


@register_step("UPLOAD_FIRMWARE_STM32CUBEPROGRAMMER")
def execute_stm32cubeprogrammer(config: dict, context: ExecutionContext) -> StepResult:
    firmware_file = config.get("firmware_file")
    if not firmware_file:
        return StepResult(passed=False, message="No firmware file attached to this step")
    path, error = _resolve_file(context, firmware_file)
    if error:
        return StepResult(passed=False, message=error)

    connection = f"port={config['connection_interface']}"
    if config.get("port"):
        connection += f" sn={config['port']}"

    command = [
        context.stm32cubeprogrammer_path or "STM32_Programmer_CLI",
        "-c", connection,
        "-w", str(path),
    ]
    if config.get("flash_address"):
        command.append(config["flash_address"])
    command += ["-v", "-rst"]

    return _run_tool(command, "STM32CubeProgrammer", context)
