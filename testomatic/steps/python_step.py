"""PYTHON step: run operator-authored Python source against the live hardware handles.

Register validates that the code parses (`ast.parse`) when the step is authored but never
executes it — this repo's runner is the only thing that ever runs it. The Test Suite JSON a
runner loads comes from a staff-only Register export, so this trust boundary is deliberate;
still worth knowing this executor runs arbitrary code with the same privileges as the runner
process. A raised exception is treated as a failed step rather than crashing the run.
"""

from __future__ import annotations

import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from .base import ExecutionContext, StepResult
from .registry import register_step


class _Tee(StringIO):
    """A StringIO that also writes through to a real stream, for live console output.

    `exec()` runs synchronously, so writing straight through to `stream` as each print() call
    happens is already "live" in the same sense as firmware.py's subprocess streaming — there's
    no separate process to interleave with.
    """

    def __init__(self, stream):
        super().__init__()
        self._stream = stream

    def write(self, text: str) -> int:
        self._stream.write(text)
        return super().write(text)


@register_step("PYTHON")
def execute(config: dict, context: ExecutionContext) -> StepResult:
    python_code = config["python_code"]
    namespace = {"chassis": context.chassis, "test_module": context.test_module}

    stdout = _Tee(sys.stdout) if context.verbose else StringIO()
    stderr = _Tee(sys.stderr) if context.verbose else StringIO()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(python_code, namespace)  # noqa: S102 -- deliberate, see module docstring
    except Exception as exc:
        output = (stdout.getvalue() + stderr.getvalue()).strip()
        return StepResult(passed=False, message=f"Python step raised: {exc}", measured={"output": output})

    output = (stdout.getvalue() + stderr.getvalue()).strip()
    return StepResult(passed=True, message="Python step executed", measured={"output": output})
