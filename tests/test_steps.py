"""Tests for individual step executors against the fake hardware in conftest.py."""

from __future__ import annotations

import subprocess
import time

from testomatic.steps import (
    beep,
    delay,
    firmware,
    iomod,
    led_spectral,
    operator_intervention,
    power,
    python_step,
)


class _FakePopen:
    """A subprocess.Popen stand-in: `stdout` is an iterable of lines (as the real Popen's stdout
    is when iterated), and `wait()` just returns the pre-set `returncode` already set by the
    time the caller's read-loop finishes."""

    def __init__(self, returncode=0, output_lines=None):
        self.returncode = returncode
        self.stdout = iter(output_lines or [])

    def wait(self):
        return self.returncode


def _capturing_popen(captured, returncode=0, output_lines=None):
    """A subprocess.Popen() replacement that records the command it was called with (into
    `captured["command"]`) and returns a `_FakePopen` reporting `returncode`/`output_lines`."""

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return _FakePopen(returncode=returncode, output_lines=output_lines)

    return fake_popen


def test_delay_sleeps_for_delay_ms(monkeypatch, context):
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    result = delay.execute({"delay_ms": 250}, context)

    assert result.passed
    assert slept == [0.25]


def test_beep_alternates_beep_and_silence(monkeypatch, context):
    events = []
    monkeypatch.setattr(time, "sleep", lambda s: events.append(("sleep", s)))
    context.chassis.beeper.beep = lambda duration_s: events.append(("beep", duration_s))

    result = beep.execute({"duration_ms": 100, "count": 3}, context)

    assert result.passed
    assert events == [
        ("beep", 0.1), ("sleep", 0.1),
        ("beep", 0.1), ("sleep", 0.1),
        ("beep", 0.1),
    ]


def test_beep_defaults_count_to_one_with_no_trailing_sleep(monkeypatch, context):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    result = beep.execute({"duration_ms": 50}, context)

    assert result.passed
    assert context.chassis.beeper.beeps == [0.05]
    assert sleeps == []


def test_operator_intervention_prints_message_and_waits(monkeypatch, context, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    result = operator_intervention.execute({"message": "Connect the probe"}, context)

    assert result.passed
    assert "Connect the probe" in capsys.readouterr().out


def test_python_step_runs_code_against_chassis(context):
    result = python_step.execute({"python_code": "chassis.beeper.beep(0.5)"}, context)

    assert result.passed
    assert context.chassis.beeper.beeps == [0.5]


def test_python_step_reports_failure_on_exception(context):
    result = python_step.execute({"python_code": "raise RuntimeError('boom')"}, context)

    assert not result.passed
    assert "boom" in result.message


def test_python_step_captures_print_output_without_echoing_to_console(context, capsys):
    result = python_step.execute({"python_code": "print('reading sensor')"}, context)

    assert result.passed
    assert result.measured["output"] == "reading sensor"
    assert capsys.readouterr().out == ""


def test_python_step_streams_print_output_live_when_verbose(context, capsys):
    context.verbose = True

    result = python_step.execute({"python_code": "print('reading sensor')"}, context)

    assert result.passed
    assert result.measured["output"] == "reading sensor"
    assert "reading sensor" in capsys.readouterr().out


def test_control_power_rail_turns_rail_on(context):
    result = power.execute_control({"rail": "5V", "action": "ON"}, context)

    assert result.passed
    assert context.chassis.power.rails["5v"] is True


def test_read_rail_voltage_within_range_passes(context):
    result = power.execute_read_voltage({"rail": "3.3V", "min_v": 3.0, "max_v": 3.6}, context)

    assert result.passed
    assert result.measured["voltage"] == 3.3


def test_read_rail_voltage_out_of_range_fails(context):
    result = power.execute_read_voltage({"rail": "3.3V", "min_v": 4.0, "max_v": 4.5}, context)

    assert not result.passed


def test_read_rail_current_within_range_passes(context):
    result = power.execute_read_current({"rail": "5V", "min_ma": 150.0, "max_ma": 250.0}, context)

    assert result.passed
    assert result.measured["current"] == 200.0


def test_iomod_digital_write_then_read_roundtrip(context):
    write_result = iomod.execute_digital_write(
        {"iomod": "C", "pin": "4", "digital_write": "1"}, context
    )
    assert write_result.passed

    read_result = iomod.execute_digital_read({"iomod": "C", "pin": "4", "expect": "1"}, context)
    assert read_result.passed


def test_iomod_digital_read_mismatch_fails(context):
    result = iomod.execute_digital_read({"iomod": "C", "pin": "4", "expect": "1"}, context)

    assert not result.passed


def test_iomod_analog_read_checks_range(context):
    context.chassis.iomod.analog[("B", 3)] = 2048

    result = iomod.execute_analog_read(
        {"iomod": "B", "pin": "3", "expect_min": 1000, "expect_max": 3000}, context
    )

    assert result.passed
    assert result.measured["value"] == 2048


def test_iomod_analog_write_records_value(context):
    result = iomod.execute_analog_write({"iomod": "B", "pin": "3", "analog_write": 1500}, context)

    assert result.passed
    assert context.chassis.iomod.analog[("B", 3)] == 1500


def test_avrdude_fails_when_no_firmware_file_attached(context):
    result = firmware.execute_avrdude(
        {"port": "/dev/ttyUSB0", "programmer_type": "arduino", "mcu": "atmega328p"}, context
    )

    assert not result.passed
    assert "No firmware file attached" in result.message


def test_avrdude_fails_when_firmware_file_missing_from_package_dir(context, tmp_path):
    context.package_dir = tmp_path

    result = firmware.execute_avrdude(
        {
            "port": "/dev/ttyUSB0", "programmer_type": "arduino", "mcu": "atmega328p",
            "firmware_file": "main.hex",
        },
        context,
    )

    assert not result.passed
    assert "not found" in result.message


def test_avrdude_builds_command_and_reports_success(monkeypatch, context, tmp_path):
    firmware_file = tmp_path / "main.hex"
    firmware_file.write_text(":00000001FF")
    context.package_dir = tmp_path

    captured = {}
    monkeypatch.setattr(
        subprocess, "Popen", _capturing_popen(captured, output_lines=["avrdude done\n"])
    )

    result = firmware.execute_avrdude(
        {
            "port": "/dev/ttyUSB0", "programmer_type": "arduino", "mcu": "atmega328p",
            "baud_rate": 115200, "firmware_file": "main.hex",
        },
        context,
    )

    assert result.passed
    assert captured["command"] == [
        "avrdude",
        "-c", "arduino",
        "-p", "atmega328p",
        "-P", "/dev/ttyUSB0",
        "-b", "115200",
        "-U", f"flash:w:{firmware_file}:i",
    ]


def test_avrdude_streams_output_live_when_verbose(monkeypatch, context, tmp_path, capsys):
    (tmp_path / "main.hex").write_text(":00000001FF")
    context.package_dir = tmp_path
    context.verbose = True

    monkeypatch.setattr(
        subprocess, "Popen",
        _capturing_popen({}, output_lines=["avrdude: writing flash\n", "avrdude done\n"]),
    )

    result = firmware.execute_avrdude(
        {"port": "/dev/ttyUSB0", "programmer_type": "arduino", "mcu": "atmega328p", "firmware_file": "main.hex"},
        context,
    )

    assert result.passed
    assert result.measured["output"] == "avrdude: writing flash\navrdude done"
    printed = capsys.readouterr().out
    assert "avrdude: writing flash" in printed
    assert "avrdude done" in printed


def test_avrdude_does_not_print_output_when_not_verbose(monkeypatch, context, tmp_path, capsys):
    (tmp_path / "main.hex").write_text(":00000001FF")
    context.package_dir = tmp_path

    monkeypatch.setattr(
        subprocess, "Popen", _capturing_popen({}, output_lines=["avrdude done\n"])
    )

    result = firmware.execute_avrdude(
        {"port": "/dev/ttyUSB0", "programmer_type": "arduino", "mcu": "atmega328p", "firmware_file": "main.hex"},
        context,
    )

    assert result.passed
    assert result.measured["output"] == "avrdude done"
    assert capsys.readouterr().out == ""


def test_avrdude_uses_context_tool_path_override(monkeypatch, context, tmp_path):
    (tmp_path / "main.hex").write_text(":00000001FF")
    context.package_dir = tmp_path
    context.avrdude_path = "/opt/avrdude/bin/avrdude"

    captured = {}
    monkeypatch.setattr(subprocess, "Popen", _capturing_popen(captured))

    firmware.execute_avrdude(
        {"port": "/dev/ttyUSB0", "programmer_type": "arduino", "mcu": "atmega328p", "firmware_file": "main.hex"},
        context,
    )

    assert captured["command"][0] == "/opt/avrdude/bin/avrdude"


def test_avrdude_reports_tool_not_found(monkeypatch, context, tmp_path):
    (tmp_path / "main.hex").write_text(":00000001FF")
    context.package_dir = tmp_path

    def fake_popen(command, **kwargs):
        raise FileNotFoundError("no such file: avrdude")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = firmware.execute_avrdude(
        {"port": "/dev/ttyUSB0", "programmer_type": "arduino", "mcu": "atmega328p", "firmware_file": "main.hex"},
        context,
    )

    assert not result.passed
    assert "not found" in result.message


def test_avrdude_reports_nonzero_exit_as_failure(monkeypatch, context, tmp_path):
    (tmp_path / "main.hex").write_text(":00000001FF")
    context.package_dir = tmp_path
    monkeypatch.setattr(
        subprocess, "Popen",
        _capturing_popen({}, returncode=1, output_lines=["avrdude: verification error\n"]),
    )

    result = firmware.execute_avrdude(
        {"port": "/dev/ttyUSB0", "programmer_type": "arduino", "mcu": "atmega328p", "firmware_file": "main.hex"},
        context,
    )

    assert not result.passed
    assert "exited 1" in result.message


def test_esptool_fails_when_no_images_attached(context):
    result = firmware.execute_esptool({"chip": "esp32", "port": "/dev/ttyUSB0"}, context)

    assert not result.passed
    assert "No firmware images attached" in result.message


def test_esptool_flashes_multiple_images_in_order(monkeypatch, context, tmp_path):
    (tmp_path / "bootloader.bin").write_bytes(b"boot")
    (tmp_path / "app.bin").write_bytes(b"app")
    context.package_dir = tmp_path

    captured = {}
    monkeypatch.setattr(subprocess, "Popen", _capturing_popen(captured))

    result = firmware.execute_esptool(
        {
            "chip": "esp32", "port": "/dev/ttyUSB0", "baud_rate": 460800,
            "images": [
                {"address": "0x1000", "file": "bootloader.bin"},
                {"address": "0x10000", "file": "app.bin"},
            ],
        },
        context,
    )

    assert result.passed
    assert captured["command"] == [
        "esptool.py",
        "--chip", "esp32",
        "--port", "/dev/ttyUSB0",
        "--baud", "460800",
        "write-flash",
        "0x1000", str(tmp_path / "bootloader.bin"),
        "0x10000", str(tmp_path / "app.bin"),
    ]


def test_esptool_fails_when_an_image_file_is_missing(context, tmp_path):
    context.package_dir = tmp_path

    result = firmware.execute_esptool(
        {"chip": "esp32", "port": "/dev/ttyUSB0", "images": [{"address": "0x1000", "file": "missing.bin"}]},
        context,
    )

    assert not result.passed
    assert "not found" in result.message


def test_openocd_builds_program_command_with_flash_address(monkeypatch, context, tmp_path):
    firmware_file = tmp_path / "app.bin"
    firmware_file.write_bytes(b"app")
    context.package_dir = tmp_path

    captured = {}
    monkeypatch.setattr(subprocess, "Popen", _capturing_popen(captured))

    result = firmware.execute_openocd(
        {
            "interface_config": "interface/stlink.cfg", "target_config": "target/stm32f4x.cfg",
            "adapter_serial": "1234", "flash_address": "0x08000000", "firmware_file": "app.bin",
        },
        context,
    )

    assert result.passed
    assert captured["command"] == [
        "openocd",
        "-f", "interface/stlink.cfg",
        "-f", "target/stm32f4x.cfg",
        "-c", "adapter serial 1234",
        "-c", f"program {firmware_file} 0x08000000 verify reset exit",
    ]


def test_openocd_fails_when_no_firmware_file_attached(context):
    result = firmware.execute_openocd(
        {"interface_config": "interface/stlink.cfg", "target_config": "target/stm32f4x.cfg"}, context
    )

    assert not result.passed
    assert "No firmware file attached" in result.message


def test_stm32cubeprogrammer_builds_command_with_port_and_flash_address(monkeypatch, context, tmp_path):
    firmware_file = tmp_path / "app.bin"
    firmware_file.write_bytes(b"app")
    context.package_dir = tmp_path

    captured = {}
    monkeypatch.setattr(subprocess, "Popen", _capturing_popen(captured))

    result = firmware.execute_stm32cubeprogrammer(
        {
            "connection_interface": "SWD", "port": "066FFF", "flash_address": "0x08000000",
            "firmware_file": "app.bin",
        },
        context,
    )

    assert result.passed
    assert captured["command"] == [
        "STM32_Programmer_CLI",
        "-c", "port=SWD sn=066FFF",
        "-w", str(firmware_file),
        "0x08000000",
        "-v", "-rst",
    ]


def test_stm32cubeprogrammer_fails_when_no_firmware_file_attached(context):
    result = firmware.execute_stm32cubeprogrammer({"connection_interface": "SWD"}, context)

    assert not result.passed
    assert "No firmware file attached" in result.message


def test_led_spectral_reading_stub_prints_and_passes(context, capsys):
    result = led_spectral.execute({}, context)

    assert result.passed
    assert "LED test" in capsys.readouterr().out
