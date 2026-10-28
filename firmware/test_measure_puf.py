# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

"""measure_puf.py against a fake demo board.

The firmware runs under MicroPython on the board and has never had a board
to run on, so this runs the file itself under CPython with the two things
MicroPython provides replaced: `time` (sleep_ms, sleep_us, ticks_ms,
ticks_us, ticks_diff) and `ttboard.demoboard.DemoBoard`. For the board
RP2's own temperature and clock, `sys.platform` and `machine` are stood in
for too, only in the tests that ask for it. The fake board keeps the
chip's pin protocol, not its physics: a start rising edge on ui[0] takes
the selection on ui[7], ui[5:2] and ui[1], done rises on uio[0], ui[6]
picks the byte, uio[3] swaps in the version bytes, uio[4] is sticky until
reset, and a listed change of selection adds one count to the next run,
the way the selector does on silicon (docs/phaseG_hazard.md). The SDK
calls the firmware makes were checked against tt-micropython-firmware
v3.1.1 on 23 September 2026, and the probe, enable() and
auto_clocking_freq against v2.0.4, v3.0.0 and v3.1.1 on 18 October.

Like the real SDK, the fake board prints a log line of its own when the
project is enabled, above the script's header, so the run that goes into
the analyzer has the same shape as a file straight off a board.
"""

import builtins
import contextlib
import io
import os
import random
import re
import tempfile
import types
import unittest
from pathlib import Path

import analyze_counts

HERE = Path(__file__).resolve().parent
SOURCE = (HERE / "measure_puf.py").read_text(encoding="utf-8")
PROJECT = "tt_um_nikodemetrashvili20_ro_puf"


def clean_count(slot):
    return 20000 + 37 * slot


class Port:
    def __init__(self, board, name):
        self._board, self._name, self._value = board, name, 0

    @property
    def value(self):
        return self._board.read(self._name)

    @value.setter
    def value(self, v):
        self._value = int(v)
        self._board.wrote(self._name, int(v))

    def __getitem__(self, bit):
        return (self.value >> bit) & 1


class FakeBoard:
    # The SDK's own version string. The chip's two version bytes are
    # chip_version, below.
    version = "3.1.1"

    def __init__(self, hazard=(), version=(2, 0x1A), die_after=None,
                 stuck_high=0, enable_ok=True, made_hz=None, ring_hz=None,
                 lock_ppm=0.0):
        self.log = []
        self.hazard = set(hazard)
        self.chip_version = version
        self.die_after = die_after
        self.enable_ok = enable_ok
        # What the SDK reports it set the clock to; None means what was asked.
        self.made_hz = made_hz
        self.asked_hz = 0
        # Ring frequencies in Hz by slot, for the tests where the clock
        # matters; None keeps clean_count. A ring within lock_ppm of a
        # multiple of the clock runs on it, the way a pulled ring would, and
        # the rest get a fresh fraction of a count each time, the way jitter
        # dithers the last one.
        self.ring_hz = ring_hz
        self.lock_ppm = lock_ppm
        self.rng = random.Random(20261027)
        # Bits a DIP switch (or anything else) holds high. The SDK leaves such
        # a pin an input, so a write to it does nothing and a read reads high.
        self.stuck_high = int(stuck_high)
        self.in_reset = False
        self.starts = 0
        for n in ("ui_in", "uio_in", "uo_out", "uio_out", "uio_oe_pico"):
            setattr(self, n, Port(self, n))
        self.shuttle = types.SimpleNamespace(
            **{PROJECT: types.SimpleNamespace(enable=self.enable)})
        self.reset_chip()

    def enable(self):
        # The real SDK logs this line, and a refusal, to the same console.
        print("ttboard.project_mux: Enable design %s" % PROJECT)
        self.log.append("enable")
        if not self.enable_ok:
            print("ttboard.project_mux: Danger level is 'HIGH'.")
            return False
        return True

    @property
    def auto_clocking_freq(self):
        return self.made_hz if self.made_hz is not None else self.asked_hz

    def reset_chip(self):
        self.active_sel, self.count, self.done, self.ovf = 0, 0, 0, 0
        self.last_ui = 0

    # Board calls the firmware makes.
    def reset_project(self, on):
        self.log.append("reset %s" % bool(on))
        self.in_reset = bool(on)
        if on:
            self.reset_chip()

    def clock_project_PWM(self, hz):
        self.asked_hz = hz
        self.log.append("clock %d" % hz)

    def clock_project_stop(self):
        self.log.append("clock stop")

    def ring_count(self, slot):
        if self.ring_hz is None:
            return clean_count(slot)
        clk = self.auto_clocking_freq
        f = self.ring_hz[slot]
        n = round(f / clk)
        if n and abs(f - n * clk) <= self.lock_ppm * 1e-6 * f:
            return n * 2048
        return int(f * 2048 / clk + self.rng.random())

    # The chip, at its pins.
    def wrote(self, name, v):
        if name != "ui_in":
            return
        v |= self.stuck_high            # a held pin acts high whatever we wrote
        rising = (v & 1) and not (self.last_ui & 1)
        self.last_ui = v
        if not rising or self.in_reset:  # a start while held in reset is a no-op
            return
        self.starts += 1
        if self.die_after is not None and self.starts > self.die_after:
            raise KeyboardInterrupt("operator stopped the run")
        slot = ((v >> 7) & 1) * 32 + ((v >> 1) & 1) * 16 + ((v >> 2) & 0xF)
        extra = 1 if (self.active_sel, slot) in self.hazard else 0
        self.active_sel = slot
        c = (self.ring_count(slot) + extra) if slot < 48 else 0
        self.ovf |= c >= 65536
        self.count, self.done = c & 0xFFFF, 1

    def read(self, name):
        if name == "uo_out":
            rd_ver = (self.uio_in._value >> 3) & 1
            high = (self.ui_in._value >> 6) & 1
            if rd_ver:
                return self.chip_version[high]
            return (self.count >> 8) & 0xFF if high else self.count & 0xFF
        if name == "uio_out":
            return self.done | (self.ovf << 4)
        if name == "ui_in":
            return self.ui_in._value | self.stuck_high
        return getattr(self, name)._value


class FakeDetect:
    """ttboard.boot.demoboard_detect.DemoboardDetect, as far as it is used."""

    def __init__(self, sure=True):
        self.sure, self.probes = sure, 0

    def probe(self):
        self.probes += 1
        return self.sure

    def PCB_str(self):
        return "TTDBv3"


class FakeMachine:
    """machine on an RP2 as far as the firmware uses it: ADC with its
    CORE_TEMP constant, 8 as on the RP2350B of the current demo board, read
    once a round, and freq(), the system clock. raw is what successive
    reads return, round by round. core_temp None is a MicroPython without
    the constant."""

    def __init__(self, raw, sys_hz, core_temp=8):
        self.raw, self.sys_hz, self.channels = list(raw), sys_hz, []
        machine = self

        class ADC:
            def __init__(self, channel):
                machine.channels.append(channel)
                self.value = machine.raw[(len(machine.channels) - 1)
                                         % len(machine.raw)]

            def read_u16(self):
                return self.value
        if core_temp is not None:
            ADC.CORE_TEMP = core_temp
        self.ADC = ADC

    def freq(self):
        return self.sys_hz


def run_firmware(board, detect=None, already_set_up=False, config=None,
                 platform=None, machine=None, sleeps=None):
    """The firmware's console output. already_set_up is a board whose main.py
    made the DemoBoard before the script ran. config replaces CONFIG lines,
    {"NAME": "python source"}. platform stands in for sys.platform and
    machine for the RP2's own module. sleeps, a list, collects ("ms", n)
    and ("us", n) for every sleep the script asks for."""
    detect = detect or FakeDetect()
    source = SOURCE
    for name, value in (config or {}).items():
        source, n = re.subn(r"(?m)^%s\s*=.*$" % name,
                            lambda m: "%s = %s" % (name, value), source)
        assert n == 1, name
    clock = {"us": 0}
    slept = sleeps if sleeps is not None else []

    def ticks_ms():
        clock["us"] += 1000
        return clock["us"] // 1000

    def sleep_ms(ms):
        slept.append(("ms", ms))
        clock["us"] += 1000 * ms

    def sleep_us(us):
        slept.append(("us", us))
        clock["us"] += us
    fake_time = types.SimpleNamespace(
        sleep_ms=sleep_ms, sleep_us=sleep_us,
        ticks_ms=ticks_ms, ticks_us=lambda: 123456,
        ticks_diff=lambda a, b: a - b)
    demoboard = types.SimpleNamespace(
        DemoBoard=types.SimpleNamespace(
            get=lambda: board,
            _DemoBoardSingleton_Instance=board if already_set_up else None))
    detect_module = types.SimpleNamespace(DemoboardDetect=detect)
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "time":
            return fake_time
        if name == "ttboard.demoboard":
            return demoboard
        if name == "ttboard.boot.demoboard_detect":
            return detect_module
        if name == "sys" and platform is not None:
            return types.SimpleNamespace(platform=platform)
        if name == "machine" and machine is not None:
            return machine
        return real_import(name, globals, locals, fromlist, level)
    env = {"__name__": "measure_puf_under_test",
           "__builtins__": dict(vars(builtins), __import__=fake_import)}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(source, str(HERE / "measure_puf.py"), "exec"), env)
    return out.getvalue()


def table(text):
    """The CSV header and rows of a run's output, comments left out."""
    lines = text.splitlines()
    body = lines[next(i for i, l in enumerate(lines)
                      if l.startswith("run_id,")):]
    rows = [l.split(",") for l in body if l and not l.startswith("#")]
    return rows[0], rows[1:]


def ring_frequencies():
    """48 rings from 470 to 545 MHz in a scrambled order, and B05 (slot 21)
    120 ppm above 11 x 50 MHz, inside a 150 ppm lock range of the main
    clock and nowhere near a multiple of 48 or 52 MHz. Version7Tests
    checks that rather than trusting this."""
    hz = [470e6 + 1.6e6 * ((29 * k) % 48) for k in range(48)]
    hz[21] = 550e6 * (1 + 120e-6)
    return hz


class MeasurePufTests(unittest.TestCase):
    def test_a_run_records_both_starts_and_loads_in_the_analyzer(self):
        hazard = {(a, b) for a in range(48) for b in (40, 41, 42, 43)
                  if a // 4 != 10}
        board = FakeBoard(hazard=hazard)
        text = run_firmware(board)
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("ttboard.project_mux: "))
        body = lines[next(i for i, l in enumerate(lines)
                          if l.startswith("run_id,")):]
        rows = [l.split(",") for l in body if l and not l.startswith("#")]
        header, rows = rows[0], rows[1:]
        col = {k: i for i, k in enumerate(header)}
        self.assertEqual(len(rows), 60 * 48)
        self.assertIn("count_first", col)
        prev = 0  # the selection a reset leaves behind
        for r in rows:
            slot = 16 * int(r[col["arm"]]) + int(r[col["idx"]])
            self.assertEqual(int(r[col["count"]]), clean_count(slot))
            self.assertEqual(int(r[col["count_first"]]),
                             clean_count(slot) + ((prev, slot) in hazard))
            prev = slot
        self.assertIn('"protocol_version": 2', text)
        self.assertIn('"build_id": 26', text)
        self.assertEqual(board.starts, 2 * 60 * 48)
        self.assertEqual(board.log[-2:], ["reset True", "clock stop"])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "run.csv")
            Path(p).write_text(text, encoding="utf-8")
            g = analyze_counts.load_files([p])[("chip01", "room_1v8")]
            for arm in (0, 1, 2):
                self.assertEqual(len(analyze_counts.osc_means(g, arm)), 16)
            self.assertEqual(len(g["first_start"]), 60 * 48 - 1)

    def test_wrong_version_bytes_stop_before_any_count(self):
        board = FakeBoard(version=(0, 0))
        text = run_firmware(board)
        self.assertIn("# ERROR: version bytes read 0 and 0x00", text)
        self.assertNotIn("# META", text)
        self.assertEqual(board.starts, 0)
        self.assertEqual(board.log[-2:], ["reset True", "clock stop"])

    def test_an_interrupted_run_resets_before_the_clock_stops(self):
        board = FakeBoard(die_after=100)
        with self.assertRaises(KeyboardInterrupt):
            run_firmware(board)
        self.assertEqual(board.log[-2:], ["reset True", "clock stop"])

    def test_a_missing_project_stops_everything(self):
        board = FakeBoard()
        board.shuttle = types.SimpleNamespace()
        text = run_firmware(board)
        self.assertIn("# ERROR: expected project %s not on this shuttle"
                      % PROJECT, text)
        self.assertEqual(board.starts, 0)
        self.assertEqual(board.log, [])

    def test_a_dip_switch_left_on_stops_before_measuring(self):
        # ui[3], idx bit 1, is held high the way a DIP switch does. The SDK
        # leaves it an input, so the firmware's writes to it go nowhere and
        # the read back no longer matches. The run has to stop before a count,
        # not quietly measure the wrong rings.
        board = FakeBoard(stuck_high=0b0000_1000)
        text = run_firmware(board)
        self.assertIn("# ERROR: wrote ui_in 0x00, read back 0x08", text)
        self.assertIn("bit(s) 3 will not drive", text)
        self.assertEqual(board.starts, 0)
        self.assertEqual(board.log[-2:], ["reset True", "clock stop"])

    def test_the_pin_check_passes_a_board_that_drives_every_pin(self):
        # No stuck pin: check_ui_in drives all eight both ways and the run
        # goes the whole way through, same as before the check existed.
        board = FakeBoard()
        text = run_firmware(board)
        self.assertEqual(board.starts, 2 * 60 * 48)
        self.assertIn("# done rounds=60", text)
        self.assertNotIn("# ERROR", text)

    def test_a_refused_enable_stops_before_the_board_drives_anything(self):
        # The SDK returns False for a project whose danger level is not safe.
        # The run used to carry on and stop at the version bytes instead.
        board = FakeBoard(enable_ok=False)
        text = run_firmware(board)
        self.assertIn("# ERROR: the SDK would not enable %s" % PROJECT, text)
        self.assertEqual(board.log, ["enable"])
        self.assertEqual(board.uio_oe_pico._value, 0)
        self.assertEqual(board.starts, 0)

    def test_the_board_is_probed_only_when_nothing_has_set_it_up(self):
        detect = FakeDetect()
        text = run_firmware(FakeBoard(), detect)
        self.assertEqual(detect.probes, 1)
        self.assertIn('"board_probed": true', text)
        self.assertIn('"board_detected": "TTDBv3"', text)
        self.assertIn('"sdk_version": "3.1.1"', text)
        # A board whose main.py ran is not probed again: probe() turns every
        # RP2 pin back to an input under the DemoBoard that is using them.
        detect = FakeDetect()
        text = run_firmware(FakeBoard(), detect, already_set_up=True)
        self.assertEqual(detect.probes, 0)
        self.assertIn('"board_probed": null', text)
        self.assertNotIn("probe was not conclusive", text)

    def test_an_unsure_probe_is_written_down_and_the_run_goes_on(self):
        # The SDK's own main.py goes on with a best guess, and so does this;
        # the version bytes still stop a board that is really wrong.
        text = run_firmware(FakeBoard(), FakeDetect(sure=False))
        self.assertIn('"board_probed": false', text)
        self.assertIn("# WARNING: the SDK's probe was not conclusive; it is"
                      " assuming a TTDBv3 board", text)
        self.assertIn("# done rounds=60", text)

    def test_the_clock_the_sdk_made_goes_in_the_header(self):
        text = run_firmware(FakeBoard())
        self.assertIn('"clk_hz_sdk": 50000000', text)
        self.assertNotIn("the SDK says it made", text)
        text = run_firmware(FakeBoard(made_hz=49_999_744))
        self.assertIn('"clk_hz_sdk": 49999744', text)
        self.assertIn("# WARNING: asked for a 50000000 Hz clock and the SDK"
                      " says it made 49999744 Hz", text)

    def test_uio_6_and_7_are_driven_low(self):
        # The board drives 1, 2 and 3, the window and read version, and now 6
        # and 7, which the chip does not read. 0, 4 and 5 are the chip's.
        board = FakeBoard()
        writes = []
        board.wrote = (lambda name, v, _orig=board.wrote:
                       (writes.append(v) if name == "uio_in" else None,
                        _orig(name, v)))
        run_firmware(board)
        self.assertEqual(board.uio_oe_pico._value, 0b1100_1110)
        self.assertTrue(writes)
        self.assertEqual([v for v in writes if v & 0b1100_0000], [])


class Version7Tests(unittest.TestCase):
    """measure_puf/7, 27 October: the pace, the board RP2's temperature,
    the clock sweep (docs/phaseG_physical_review.md)."""

    def test_a_start_waits_microseconds_not_milliseconds(self):
        # Every millisecond sleep left is the setup's: reset, the pin check
        # and the version bytes. A start is three waits of SETTLE_US.
        sleeps = []
        board = FakeBoard()
        text = run_firmware(board, sleeps=sleeps)
        self.assertEqual([n for k, n in sleeps if k == "ms"],
                         [10, 1, 1, 1, 1, 1, 10, 1, 1, 1])
        self.assertEqual([n for k, n in sleeps if k == "us"],
                         [20] * (3 * board.starts))
        self.assertEqual(board.starts, 2 * 60 * 48)
        self.assertIn('"settle_us": 20', text)

    def test_rows_carry_their_clock_and_no_temperature_off_an_rp2(self):
        text = run_firmware(FakeBoard())
        header, rows = table(text)
        self.assertEqual(header[-3:], ["t_ms", "clk_hz", "t_rp_c"])
        self.assertEqual({r[-2] for r in rows}, {"50000000"})
        self.assertEqual({r[-1] for r in rows}, {""})
        self.assertIn('"t_rp_c_is": null', text)
        self.assertIn('"rp2_sys_hz": null', text)
        self.assertIn('"clk_sweep_hz": []', text)
        self.assertIn("# done rounds=60 timeouts=0", text)

    def test_on_an_rp2_each_round_carries_the_die_temperature(self):
        # 14020 of 65535 is 0.70598 V, 27.0 C by the datasheet's line, and
        # 13800 is 0.69490 V, 33.45 C. One read of the sensor a round, on
        # the channel CORE_TEMP names and never on 4.
        machine = FakeMachine(raw=[14020, 13800], sys_hz=100_000_000)
        text = run_firmware(FakeBoard(), platform="rp2", machine=machine)
        header, rows = table(text)
        temps = [r[header.index("t_rp_c")] for r in rows]
        self.assertEqual(temps[:96], ["27.0"] * 48 + ["33.5"] * 48)
        self.assertEqual(machine.channels, [8] * 60)
        self.assertIn('"rp2_sys_hz": 100000000', text)
        self.assertIn('"t_rp_c_is": "board RP2 die"', text)
        self.assertNotIn("does not divide", text)

    def test_without_core_temp_no_adc_is_touched(self):
        # An older MicroPython with no ADC.CORE_TEMP: the column stays
        # empty, and no channel, which on an RP2350B could be a pin, is read.
        machine = FakeMachine([14020], 100_000_000, core_temp=None)
        text = run_firmware(FakeBoard(), platform="rp2", machine=machine)
        header, rows = table(text)
        self.assertEqual({r[header.index("t_rp_c")] for r in rows}, {""})
        self.assertEqual(machine.channels, [])

    def test_a_system_clock_the_project_clock_does_not_divide_is_warned(self):
        # 125 MHz over 50 is 2.5: the PWM divides by a fraction. 150 over 50
        # is 3, whole, and only the duty is off half a period, which a
        # design that uses rising edges alone never sees.
        text = run_firmware(FakeBoard(), platform="rp2",
                            machine=FakeMachine([14020], 125_000_000))
        self.assertIn("# WARNING: the board's RP2 runs at 125000000 Hz,"
                      " which the 50000000 Hz project clock does not divide",
                      text)
        text = run_firmware(FakeBoard(), platform="rp2",
                            machine=FakeMachine([14020], 150_000_000))
        self.assertNotIn("does not divide", text)

    def test_the_fixture_has_one_ring_in_lock_range(self):
        # The sweep test below leans on this, so check it rather than trust
        # the arithmetic in the docstring.
        hz = ring_frequencies()
        near = sorted((k, clk) for k, f in enumerate(hz)
                      for clk in (48e6, 50e6, 52e6)
                      if abs(f - round(f / clk) * clk) <= 150e-6 * f)
        self.assertEqual(near, [(21, 50e6)])
        # And no ring left to itself reads within two counts of a multiple
        # of a quarter window at 50 MHz, the finest step the analyzer
        # flags. B05 would read 22530.7; it reads 22528 only because it is
        # locked.
        counts = [f * 2048 / 50e6 for f in hz]
        on_step = [k for k, c in enumerate(counts)
                   if abs(c - 512 * round(c / 512)) <= 2]
        self.assertEqual(on_step, [])

    def test_a_clock_sweep_finds_a_ring_pulled_onto_the_clock(self):
        board = FakeBoard(ring_hz=ring_frequencies(), lock_ppm=150)
        text = run_firmware(board, config={
            "CLK_SWEEP_HZ": "(48_000_000, 52_000_000)"})
        header, rows = table(text)
        self.assertEqual(len(rows), (60 + 2 * 10) * 48)
        clk = [r[header.index("clk_hz")] for r in rows][::48]
        self.assertEqual(clk, ["50000000"] * 60 + ["48000000"] * 10
                         + ["52000000"] * 10)
        self.assertIn("# sweep clk=48000000 rounds=10", text)
        self.assertIn("# done rounds=60 sweep_rounds=20 timeouts=0", text)
        self.assertIn('"clk_sweep_hz": [48000000, 52000000]', text)
        self.assertIn('"sweep_rounds": 10', text)
        # The project sits in reset while each clock changes.
        for hz in (48_000_000, 52_000_000):
            i = board.log.index("clock %d" % hz)
            self.assertEqual(board.log[i - 1:i + 2],
                             ["reset True", "clock %d" % hz, "reset False"])
        self.assertEqual(board.log[-2:], ["reset True", "clock stop"])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "run.csv")
            Path(p).write_text(text, encoding="utf-8")
            g = analyze_counts.load_files([p])[("chip01", "room_1v8")]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                analyze_counts.print_pulling({("chip01", "room_1v8"): g})
        # Nothing from the sweep reaches the main statistics.
        self.assertEqual(len(g["by_round"]), 60)
        self.assertEqual(len(g["first_start"]), 60 * 48 - 1)
        self.assertEqual(analyze_counts.osc_means(g, 1)[5], 11 * 2048)
        self.assertEqual(sorted(next(iter(g["sweep"].values()))),
                         [48_000_000, 52_000_000])
        report = out.getvalue()
        self.assertIn("B05 reads 11 x 2048 (550.0 MHz), repeat SD 0.00",
                      report)
        self.assertEqual(report.count(" reads "), 1)
        flagged = re.findall(r"at (\d+) Hz: shift all rings share [+-]\d+ ppm,"
                             r" spread [\d.]+ ppm; off by more than \d+ ppm:"
                             r" (.*)", report)
        self.assertEqual([c for c, _ in flagged], ["48000000", "52000000"])
        for _, names in flagged:
            self.assertRegex(names, r"^B05 \+1[0-3]\d ppm$")

    def test_a_sweep_clock_too_slow_for_the_window_is_warned(self):
        text = run_firmware(FakeBoard(), config={
            "CLK_SWEEP_HZ": "(40_000_000,)", "ROUNDS": "2",
            "SWEEP_ROUNDS": "1"})
        self.assertIn("# WARNING: at 40000000 Hz and the 2048 window the"
                      " counter can report 1280 MHz before it wraps, under"
                      " 1.5 times the fastest simulated ring", text)
        self.assertNotIn("at 50000000 Hz and the", text)
        self.assertIn('"settle_us": 20', text)

    def test_a_sweep_clock_the_sdk_did_not_make_is_written_down(self):
        board = FakeBoard()
        board.clock_project_PWM = (
            lambda hz, _orig=board.clock_project_PWM:
            (_orig(hz), setattr(board, "made_hz",
                                hz if hz == 50_000_000 else hz + 3)))
        text = run_firmware(board, config={
            "CLK_SWEEP_HZ": "(48_000_000,)", "ROUNDS": "2",
            "SWEEP_ROUNDS": "1"})
        self.assertIn("# WARNING: sweep asked for 48000000 Hz and the SDK"
                      " says it made 48000003 Hz", text)
        header, rows = table(text)
        self.assertEqual(rows[-1][header.index("clk_hz")], "48000003")


if __name__ == "__main__":
    unittest.main()
