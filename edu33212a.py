"""EDU33212A USB control. Configuration never enables an output."""

import argparse
import json
import math
import os
from pathlib import Path

import pyvisa


class Generator:
    def __init__(self, serial=None):
        serial = serial or os.environ.get("EDU33212A_SERIAL")
        if not serial:
            raise ValueError("Set EDU33212A_SERIAL to the actual instrument serial before connecting")
        self.rm = pyvisa.ResourceManager()
        self.instrument = None
        try:
            matches = [address for address in self.rm.list_resources() if address.startswith("USB") and f"::{serial}::" in address]
            if len(matches) != 1:
                raise RuntimeError(f"Expected one USB instrument with serial {serial}, found {matches}")
            self.address = matches[0]
            self.instrument = self.rm.open_resource(self.address)
            self.instrument.timeout = 5000
            self.identity = self.query("*IDN?")
            fields = self.identity.split(",")
            if len(fields) < 3 or fields[1] != "EDU33212A" or fields[2] != serial:
                raise RuntimeError(f"Unexpected instrument: {self.identity}")
        except Exception:
            self.close()
            raise

    def close(self):
        try:
            if self.instrument is not None:
                self.instrument.close()
        finally:
            self.rm.close()

    def query(self, command):
        return self.instrument.query(command).strip()

    def write(self, command):
        self.instrument.write(command)
        self.query("*OPC?")
        error = self.query("SYST:ERR?")
        if int(error.split(",", 1)[0]) != 0:
            raise RuntimeError(f"{command}: {error}")

    def channel_status(self, channel):
        queries = {"output": f"OUTP{channel}?", "load_ohms": f"OUTP{channel}:LOAD?", "waveform": f"SOUR{channel}:FUNC?", "frequency_hz": f"SOUR{channel}:FREQ?", "amplitude": f"SOUR{channel}:VOLT?", "amplitude_unit": f"SOUR{channel}:VOLT:UNIT?", "offset_v": f"SOUR{channel}:VOLT:OFFS?", "phase_deg": f"SOUR{channel}:PHAS?", "frequency_mode": f"SOUR{channel}:FREQ:MODE?", "burst": f"SOUR{channel}:BURS:STAT?"}
        queries.update({"sweep_start_hz": f"SOUR{channel}:FREQ:STAR?", "sweep_stop_hz": f"SOUR{channel}:FREQ:STOP?", "sweep_time_s": f"SOUR{channel}:SWE:TIME?", "sweep_spacing": f"SOUR{channel}:SWE:SPAC?", "trigger_source": f"TRIG{channel}:SOUR?"})
        return {name: self.query(command) for name, command in queries.items()}

    def status(self):
        return {"identity": self.identity, "address": self.address, "channels": {str(channel): self.channel_status(channel) for channel in (1, 2)}}

    def configure(self, channel, waveform, frequency, amplitude, offset, load):
        if not all(math.isfinite(value) for value in (frequency, amplitude, offset)) or frequency <= 0 or amplitude <= 0:
            raise ValueError("Frequency and Vpp must be finite and positive; offset must be finite")
        if self.query("SOUR1:FREQ:COUP:STAT?") != "0" or self.query("SOUR1:VOLT:COUP:STAT?") != "0":
            raise RuntimeError("Channel coupling is enabled; resolve coupling before independent configuration")
        self.write(f"OUTP{channel} OFF")
        try:
            for command in (f"OUTP{channel}:LOAD {load}", f"SOUR{channel}:FREQ:MODE CW", f"SOUR{channel}:BURS:STAT OFF", *(f"SOUR{channel}:{mode}:STAT OFF" for mode in ("AM", "FM", "PM", "FSK", "BPSK", "PWM", "SUM")), f"SOUR{channel}:VOLT:UNIT VPP", f"SOUR{channel}:FUNC {waveform}", f"SOUR{channel}:FREQ {frequency:.12g}", f"SOUR{channel}:VOLT:OFFS 0", f"SOUR{channel}:VOLT {amplitude:.12g}", f"SOUR{channel}:VOLT:OFFS {offset:.12g}"):
                self.write(command)
            state = self.channel_status(channel)
            actual_load = float(state["load_ohms"])
            if state["output"] != "0" or state["waveform"] != waveform or state["amplitude_unit"] != "VPP" or (load == "50" and not math.isclose(actual_load, 50)) or (load == "INF" and actual_load < 1e30):
                raise RuntimeError("Waveform, output, amplitude unit or load readback mismatch")
            for field, expected in (("frequency_hz", frequency), ("amplitude", amplitude), ("offset_v", offset)):
                if not math.isclose(float(state[field]), expected, rel_tol=1e-6, abs_tol=1e-9):
                    raise RuntimeError(f"Readback mismatch: {field}={state[field]}, expected {expected}")
            return state
        except Exception:
            self.instrument.write(f"OUTP{channel} OFF")
            raise

    def configure_sweep(self, channel, start, stop, seconds, spacing, amplitude, offset, load):
        if not all(math.isfinite(value) and value > 0 for value in (start, stop, seconds)) or start == stop:
            raise ValueError("Sweep frequencies and time must be finite and positive; endpoints must differ")
        self.configure(channel, "SIN", start, amplitude, offset, load)
        for command in (f"SOUR{channel}:FREQ:STAR {start:.12g}", f"SOUR{channel}:FREQ:STOP {stop:.12g}", f"SOUR{channel}:SWE:SPAC {spacing}", f"SOUR{channel}:SWE:TIME {seconds:.12g}", f"SOUR{channel}:SWE:HTIM 0", f"SOUR{channel}:SWE:RTIM 0", f"TRIG{channel}:SOUR IMM", f"INIT{channel}:CONT ON", f"SOUR{channel}:FREQ:MODE SWE"):
            self.write(command)
        state = self.channel_status(channel)
        if state["output"] != "0" or state["frequency_mode"] != "SWE" or state["sweep_spacing"] != spacing:
            raise RuntimeError("Sweep mode or output readback mismatch")
        for field, expected in (("sweep_start_hz", start), ("sweep_stop_hz", stop), ("sweep_time_s", seconds)):
            if not math.isclose(float(state[field]), expected, rel_tol=1e-6, abs_tol=1e-9):
                raise RuntimeError(f"Readback mismatch: {field}={state[field]}, expected {expected}")
        return state


def main():
    parser = argparse.ArgumentParser(description="EDU33212A control; configuration leaves output OFF")
    parser.add_argument("--serial", default=None)
    commands = parser.add_subparsers(dest="action", required=True)
    status = commands.add_parser("status", help="Read both channels without changing settings")
    status.add_argument("--save", type=Path)
    configure = commands.add_parser("configure", help="Configure basic waveform with output OFF")
    configure.add_argument("--channel", type=int, choices=(1, 2), required=True)
    configure.add_argument("--waveform", choices=("SIN", "SQU", "RAMP", "PULS"), required=True)
    configure.add_argument("--frequency", type=float, required=True, help="Hz")
    configure.add_argument("--amplitude", type=float, required=True, help="Vpp")
    configure.add_argument("--offset", type=float, required=True, help="V")
    configure.add_argument("--load", choices=("50", "INF"), required=True, help="Actual connected load: 50 ohms or high impedance")
    sweep = commands.add_parser("sweep", help="Prepare repeating sine sweep; output stays OFF")
    sweep.add_argument("--channel", type=int, choices=(1, 2), default=2)
    sweep.add_argument("--start", type=float, required=True, help="Start frequency in Hz")
    sweep.add_argument("--stop", type=float, required=True, help="Stop frequency in Hz")
    sweep.add_argument("--seconds", type=float, required=True)
    sweep.add_argument("--spacing", choices=("LIN", "LOG"), required=True)
    sweep.add_argument("--amplitude", type=float, required=True, help="Vpp")
    sweep.add_argument("--offset", type=float, required=True, help="V")
    sweep.add_argument("--load", choices=("50", "INF"), required=True)
    output = commands.add_parser("output", help="Explicit output switch; ON requires confirmed wiring and settings")
    output.add_argument("--channel", type=int, choices=(1, 2), required=True)
    output.add_argument("--state", choices=("on", "off"), required=True)
    args = parser.parse_args()
    generator = Generator(args.serial)
    try:
        if args.action == "status":
            result = generator.status()
            if args.save:
                args.save.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        elif args.action == "configure":
            result = generator.configure(args.channel, args.waveform, args.frequency, args.amplitude, args.offset, args.load)
        elif args.action == "sweep":
            result = generator.configure_sweep(args.channel, args.start, args.stop, args.seconds, args.spacing, args.amplitude, args.offset, args.load)
        else:
            generator.write(f"OUTP{args.channel} {args.state.upper()}")
            result = generator.channel_status(args.channel)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        generator.close()


if __name__ == "__main__":
    main()

