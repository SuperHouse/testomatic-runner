"""Command-line entry point: `python -m testomatic run <suite.zip|suite.json>`.

Verified against real Testomatic hardware for BEEP and READ_RAIL_VOLTAGE — see
TEST_RUNNER_PLAN.md for what's still unverified.
"""

from __future__ import annotations

import argparse

from .runner import TestRunner, format_report
from .suite import load_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="testomatic")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Execute a Test Suite")
    run_parser.add_argument(
        "suite_path",
        help="Path to a Test Suite Package (.zip) or a Test Suite Definition JSON file",
    )
    run_parser.add_argument(
        "--avrdude-path", help="Override the avrdude executable (default: 'avrdude' on $PATH)"
    )
    run_parser.add_argument(
        "--esptool-path", help="Override the esptool.py executable (default: 'esptool.py' on $PATH)"
    )
    run_parser.add_argument(
        "--openocd-path", help="Override the openocd executable (default: 'openocd' on $PATH)"
    )
    run_parser.add_argument(
        "--stm32cubeprogrammer-path",
        help="Override the STM32_Programmer_CLI executable (default: 'STM32_Programmer_CLI' on $PATH)",
    )
    run_parser.add_argument(
        "--verbose", action="store_true",
        help="Stream firmware-tool/Python-step output live as steps run, and include it in the final report",
    )

    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(
            args.suite_path,
            avrdude_path=args.avrdude_path,
            esptool_path=args.esptool_path,
            openocd_path=args.openocd_path,
            stm32cubeprogrammer_path=args.stm32cubeprogrammer_path,
            verbose=args.verbose,
        )

    return 1


def _run(
    suite_path: str,
    *,
    avrdude_path: str | None = None,
    esptool_path: str | None = None,
    openocd_path: str | None = None,
    stm32cubeprogrammer_path: str | None = None,
    verbose: bool = False,
) -> int:
    from testomatic_io import Chassis, TestModule  # imported here: only importable on real hardware

    suite = load_suite(suite_path)

    chassis = Chassis()
    chassis.init()
    test_module = TestModule()
    test_module.init()

    runner = TestRunner(
        chassis,
        test_module,
        avrdude_path=avrdude_path,
        esptool_path=esptool_path,
        openocd_path=openocd_path,
        stm32cubeprogrammer_path=stm32cubeprogrammer_path,
        verbose=verbose,
    )
    report = runner.run(suite)

    print(format_report(report, suite.manual_checks, verbose=verbose))

    return 0 if report.passed else 1
