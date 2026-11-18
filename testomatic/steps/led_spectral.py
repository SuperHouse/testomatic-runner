"""LED_SPECTRAL_READING step: read a VEML3328SL colour sensor via `chassis.colour_sensor`
(testomatic-io) and check each channel against the step's optional min/max limits.

A sensor that doesn't respond raises RuntimeError from testomatic-io, which `runner.py` turns into
a failed step naming where it looked.
"""

from __future__ import annotations

from .base import ExecutionContext, StepResult
from .registry import register_step

# Step config limit prefix -> ColourReading field, in the order they're reported.
_CHANNELS = {
    "r": "red",
    "g": "green",
    "b": "blue",
    "ir": "ir",
    "lux": "lux",
}


def _format(key: str, value: float) -> str:
    return f"{value:.1f}" if key == "lux" else str(value)


def _limit_text(low: float | None, high: float | None) -> str:
    if low is None:
        return f"max {high}"
    if high is None:
        return f"min {low}"
    return f"expected {low}-{high}"


@register_step("LED_SPECTRAL_READING")
def execute(config: dict, context: ExecutionContext) -> StepResult:
    i2c_addr = int(config["i2c_addr"], 0)
    mux_addr = int(config["mux_addr"], 0) if config.get("mux_addr") else None
    mux_chan = int(config["mux_chan"]) if mux_addr is not None else None

    reading = context.chassis.colour_sensor.read(i2c_addr, mux_addr=mux_addr, mux_chan=mux_chan)

    failures = []
    for key, field_name in _CHANNELS.items():
        low = config.get(f"{key}_min")
        high = config.get(f"{key}_max")
        if low is None and high is None:
            continue
        value = getattr(reading, field_name)
        if (low is not None and value < low) or (high is not None and value > high):
            failures.append(f"{key} {_format(key, value)} ({_limit_text(low, high)})")

    summary = (
        f"R{reading.red} G{reading.green} B{reading.blue} IR{reading.ir} "
        f"C{reading.clear} {reading.lux:.1f}lx"
    )
    # Reason first: testomatic-ui's Test Docket prints a failing step's message, wrapped, under
    # the step name, so the part an operator needs comes before the full reading.
    message = summary
    if failures:
        message = "Out of range: " + ", ".join(failures) + ". " + summary

    return StepResult(
        passed=not failures,
        message=message,
        measured={
            **reading._asdict(),
            # "display" (issue testomatic-ui#13): the value testomatic-ui's Test Docket prints on
            # its own smaller line under the check (~43 characters) -- every channel, so the
            # printed record is enough to tune a suite's limits from.
            "display": summary,
        },
    )
