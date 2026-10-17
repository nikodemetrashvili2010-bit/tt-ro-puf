# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

"""measure_puf.py against a fake demo board.

The firmware runs under MicroPython on the board and has never had a board
to run on, so this runs the file itself under CPython with the two things
MicroPython provides replaced: `time` (sleep_ms, ticks_ms, ticks_us,
ticks_diff) and `ttboard.demoboard.DemoBoard`. The fake board keeps the
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
                 stuck_high=0, enable_ok=True, made_hz=None):
        self.log = []
        self.hazard = set(hazard)
        self.chip_version = version
        self.die_after = die_after
        self.enable_ok = enable_ok
        # What the SDK reports it set the clock to; None means what was asked.
        self.made_hz = made_hz
        self.asked_hz = 0
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
        c = (clean_count(slot) + extra) if slot < 48 else 0
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


def run_firmware(board, detect=None, already_set_up=False):
    """The firmware's console output. already_set_up is a board whose main.py
    made the DemoBoard before the script ran."""
    detect = detect or FakeDetect()
    clock = {"ms": 0}

    def ticks_ms():
        clock["ms"] += 1
        return clock["ms"]
    fake_time = types.SimpleNamespace(
        sleep_ms=lambda ms: clock.__setitem__("ms", clock["ms"] + ms),
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
        return real_import(name, globals, locals, fromlist, level)
    env = {"__name__": "measure_puf_under_test",
           "__builtins__": dict(vars(builtins), __import__=fake_import)}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(SOURCE, str(HERE / "measure_puf.py"), "exec"), env)
    return out.getvalue()


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


if __name__ == "__main__":
    unittest.main()
