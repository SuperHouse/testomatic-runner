"""Executes a parsed Test Suite's steps against real hardware."""

from __future__ import annotations

from dataclasses import dataclass, field

from .steps import ExecutionContext, StepResult, get_executor
from .suite import ManualCheck, TestStep, TestSuiteFile


@dataclass
class StepOutcome:
    step: TestStep
    result: StepResult


@dataclass
class RunReport:
    outcomes: list[StepOutcome] = field(default_factory=list)
    aborted: bool = False

    @property
    def passed(self) -> bool:
        return not self.aborted and all(outcome.result.passed for outcome in self.outcomes)


class TestRunner:
    def __init__(
        self,
        chassis,
        test_module=None,
        *,
        avrdude_path: str | None = None,
        esptool_path: str | None = None,
        openocd_path: str | None = None,
        stm32cubeprogrammer_path: str | None = None,
        verbose: bool = False,
    ):
        self.context = ExecutionContext(
            chassis=chassis,
            test_module=test_module,
            avrdude_path=avrdude_path,
            esptool_path=esptool_path,
            openocd_path=openocd_path,
            stm32cubeprogrammer_path=stm32cubeprogrammer_path,
            verbose=verbose,
        )

    def run(self, suite: TestSuiteFile) -> RunReport:
        self.context.package_dir = suite.package_dir
        report = RunReport()

        for step in suite.test_steps:
            result = self._run_step(step)
            report.outcomes.append(StepOutcome(step=step, result=result))

            if not result.passed and step.abort_on_fail:
                self._all_rails_off()
                report.aborted = True
                break

        return report

    def _run_step(self, step: TestStep) -> StepResult:
        try:
            executor = get_executor(step.step_type)
        except KeyError as exc:
            return StepResult(passed=False, message=str(exc))

        try:
            return executor(step.config, self.context)
        except Exception as exc:  # a bug in one step's executor must not crash the whole run
            return StepResult(passed=False, message=f"{step.step_type} raised: {exc}")

    def _all_rails_off(self) -> None:
        """Safety shutdown on abort-on-fail: turn off all three power rails unconditionally,
        regardless of what the runner believes their current state to be.
        """
        power = self.context.chassis.power
        power.rail_3v3(False)
        power.rail_5v(False)
        power.rail_12v(False)


def format_report(report: RunReport, manual_checks: list[ManualCheck], verbose: bool = False) -> str:
    lines = []

    for outcome in report.outcomes:
        status = "PASS" if outcome.result.passed else "FAIL"
        lines.append(f"[{status}] {outcome.step.name}: {outcome.result.message}")

        output = outcome.result.measured.get("output") if verbose else None
        if output:
            lines.append("    --- output ---")
            lines.extend(f"    {line}" for line in output.splitlines())
            lines.append("    --------------")

    if report.aborted:
        lines.append("ABORTED: abort-on-fail step failed, all power rails turned off")

    lines.append("")
    lines.append(f"Result: {'PASS' if report.passed else 'FAIL'}")

    if manual_checks:
        lines.append("")
        lines.append("Manual checks (perform by hand):")
        for check in manual_checks:
            lines.append(f"  [ ] {check.text}")

    return "\n".join(lines)
