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
v3.1.1 on 23 September 2026.
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
    def __init__(self, hazard=(), version=(2, 0x1A), die_after=None):
        self.log = []
        self.hazard = set(hazard)
        self.version = version
        self.die_after = die_after
        self.starts = 0
        for n in ("ui_in", "uio_in", "uo_out", "uio_out", "uio_oe_pico"):
            setattr(self, n, Port(self, n))
        self.shuttle = types.SimpleNamespace(
            **{PROJECT: types.SimpleNamespace(
                enable=lambda: self.log.append("enable"))})
        self.reset_chip()

    def reset_chip(self):
        self.active_sel, self.count, self.done, self.ovf = 0, 0, 0, 0
        self.last_ui = 0

    # Board calls the firmware makes.
    def reset_project(self, on):
        self.log.append("reset %s" % bool(on))
        if on:
            self.reset_chip()

    def clock_project_PWM(self, hz):
        self.log.append("clock %d" % hz)

    def clock_project_stop(self):
        self.log.append("clock stop")

    # The chip, at its pins.
    def wrote(self, name, v):
        if name != "ui_in":
            return
        rising = (v & 1) and not (self.last_ui & 1)
        self.last_ui = v
        if not rising:
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
                return self.version[high]
            return (self.count >> 8) & 0xFF if high else self.count & 0xFF
        if name == "uio_out":
            return self.done | (self.ovf << 4)
        return getattr(self, name)._value


def run_firmware(board):
    clock = {"ms": 0}

    def ticks_ms():
        clock["ms"] += 1
        return clock["ms"]
    fake_time = types.SimpleNamespace(
        sleep_ms=lambda ms: clock.__setitem__("ms", clock["ms"] + ms),
        ticks_ms=ticks_ms, ticks_us=lambda: 123456,
        ticks_diff=lambda a, b: a - b)
    demoboard = types.SimpleNamespace(
        DemoBoard=types.SimpleNamespace(get=lambda: board))
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "time":
            return fake_time
        if name == "ttboard.demoboard":
            return demoboard
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
        rows = [l.split(",") for l in text.splitlines()
                if l and not l.startswith("#")]
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
        with self.assertRaises(SystemExit) as ctx:
            run_firmware(board)
        self.assertIn("version bytes", str(ctx.exception))
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
        with self.assertRaises(SystemExit) as ctx:
            run_firmware(board)
        self.assertIn("not on this shuttle", str(ctx.exception))
        self.assertEqual(board.starts, 0)


if __name__ == "__main__":
    unittest.main()
