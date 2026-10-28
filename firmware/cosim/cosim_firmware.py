# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""measure_puf.py itself, run against the chip's RTL.

test_measure_puf.py runs the firmware against a fake board that keeps the
pin protocol and not the chip. This runs the same file, unchanged apart
from a few CONFIG lines, against the RTL the chip was built from. The
firmware sits in a thread of its own, and every pin it touches, every sleep
and every clock it asks for goes through the simulator. The rings are the
behavioural models the cocotb regression in test/ uses, so every count is
known in advance.

What a board does that the fake does not: each pin read or write takes
time, the clock runs and stops when the SDK is told to, and the poll for
done really waits for the chip.

Three hosts. A typical one, every pin operation 5 us. A fast one, 0.1 us,
five clock cycles, the hardest on the protocol's timing. And a slow,
uneven one whose every pin operation takes a seeded random 1 to 30 us.
Each runs the main rounds and a clock sweep, and every clock change comes
with a runt pulse on clk while the project sits in reset, the kind of
sliver a PWM set up again in mid-period can leave. Every count has to be
the model's, and the analyzer has to read the run.
"""

import builtins
import contextlib
import io
import os
import random
import re
import sys
import types
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.simtime import get_sim_time
from cocotb.task import bridge, resume
from cocotb.triggers import Timer

HERE = Path(__file__).resolve().parent
FW = HERE.parent
ROOT = FW.parent
SOURCE = (FW / "measure_puf.py").read_text(encoding="utf-8")
sys.path.insert(0, str(FW))
import analyze_counts  # noqa: E402

PROJECT = "tt_um_nikodemetrashvili20_ro_puf"
WINDOW = 2048


def _half_period_rule(path):
    """(base, step) from a model's HALF_PERIOD_PS line, step 0 if flat."""
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(r"HALF_PERIOD_PS\s*=\s*(\d+)(?:\s*\+\s*IDX\s*\*\s*(\d+))?;",
                  text)
    return int(m.group(1)), int(m.group(2) or 0)


# Read from the models the simulation compiles, not copied from test.py.
HALF = {0: _half_period_rule(ROOT / "src" / "ro_macro_sim.v"),
        1: _half_period_rule(ROOT / "test" / "ro_macro_hard_sim.v"),
        2: _half_period_rule(ROOT / "src" / "ro_armc_sim.v")}


def model_count(arm, idx, clk_ps):
    base, step = HALF[arm]
    return WINDOW * clk_ps / (2.0 * (base + step * idx))


# --- the simulator side ----------------------------------------------------

@resume
async def _poke(sig, value, us):
    sig.value = value
    await Timer(us, "us", round_mode="round")
    return get_sim_time("us")


@resume
async def _peek(sig, us):
    await Timer(us, "us", round_mode="round")
    v = sig.value
    if not v.is_resolvable:
        raise AssertionError("%s read %s" % (sig._path, v))
    return int(v), get_sim_time("us")


@resume
async def _sleep(us):
    await Timer(us, "us", round_mode="round")
    return get_sim_time("us")


@resume
async def _start_clock(board, hz):
    dut = board.dut
    if board.clock is not None:
        board.clock.stop()
        board.clock = None
        await Timer(5, "ns")
        if board.runt:
            # A PWM set up again mid-flight can leave a sliver of a pulse:
            # one rising edge 700 ps wide, with the project in reset.
            dut.clk.value = 0
            await Timer(5, "ns")
            dut.clk.value = 1
            await Timer(700, "ps")
            dut.clk.value = 0
            await Timer(1, "us")
            board.log.append("runt")
    # Whole picoseconds, so 48 MHz is 20833 ps here, 48 000 768 Hz, and the
    # board says so the way the SDK does, through auto_clocking_freq.
    period = int(round(1e12 / hz))
    board.clock = Clock(dut.clk, period, unit="ps", period_high=period // 2)
    board.clock.start()
    board.period_ps = period
    await Timer(1, "us")
    return get_sim_time("us")


@resume
async def _stop_clock(board):
    if board.clock is not None:
        board.clock.stop()
        board.clock = None
    board.dut.clk.value = 0
    board.period_ps = None
    await Timer(1, "us")
    return get_sim_time("us")


class Port:
    """One of the SDK's 8-bit pin groups."""

    def __init__(self, board, name):
        self.board, self.name = board, name

    @property
    def value(self):
        return self.board.read(self.name)

    @value.setter
    def value(self, v):
        self.board.write(self.name, int(v))

    def __getitem__(self, bit):
        return (self.value >> bit) & 1


class SimBoard:
    """ttboard.demoboard.DemoBoard as far as measure_puf.py uses it, with
    the chip's RTL at the pins."""

    version = "3.1.1"

    def __init__(self, dut, out, pin_us=5.0, rng=None, runt=True):
        self.dut, self.out = dut, out
        self.pin_us, self.rng, self.runt = pin_us, rng, runt
        self.mask, self.ui, self.uio = 0, 0, 0
        self.clock, self.period_ps = None, None
        self.now_us = get_sim_time("us")
        self.log = []
        for n in ("ui_in", "uio_in", "uo_out", "uio_out", "uio_oe_pico"):
            setattr(self, n, Port(self, n))
        self.shuttle = types.SimpleNamespace(
            **{PROJECT: types.SimpleNamespace(enable=self.enable)})

    def cost(self):
        return self.rng.uniform(1.0, 30.0) if self.rng else self.pin_us

    def enable(self):
        self.out.write("ttboard.project_mux: Enable design %s\n" % PROJECT)
        self.now_us = _poke(self.dut.ena, 1, self.cost())
        self.log.append("enable")
        return True

    def write(self, name, v):
        if name == "ui_in":
            self.ui = v
            self.now_us = _poke(self.dut.ui_in, v, self.cost())
        elif name == "uio_in":
            self.uio = v
            self.now_us = _poke(self.dut.uio_in, v & self.mask, self.cost())
        elif name == "uio_oe_pico":
            self.mask = v
            self.now_us = _sleep(self.cost())
        else:
            raise AssertionError("the firmware wrote %s" % name)

    def read(self, name):
        if name in ("uo_out", "uio_out"):
            v, self.now_us = _peek(getattr(self.dut, name), self.cost())
            return v
        if name == "ui_in":
            v, self.now_us = _peek(self.dut.ui_in, self.cost())
            return v
        return {"uio_in": self.uio, "uio_oe_pico": self.mask}[name]

    def reset_project(self, on):
        self.log.append("reset %s" % bool(on))
        self.now_us = _poke(self.dut.rst_n, 0 if on else 1, self.cost())

    def clock_project_PWM(self, hz):
        self.log.append("clock %d" % hz)
        self.now_us = _start_clock(self, hz)

    def clock_project_stop(self):
        self.log.append("clock stop")
        self.now_us = _stop_clock(self)

    @property
    def auto_clocking_freq(self):
        if self.period_ps is None:
            return 0
        return int(round(1e12 / self.period_ps))


class Detect:
    probes = 0

    @classmethod
    def probe(cls):
        cls.probes += 1
        return True

    @staticmethod
    def PCB_str():
        return "TTDBv3"


class Console(io.StringIO):
    """The board's console: kept, and written to a file as it comes, so a
    long run can be watched."""

    def __init__(self, path):
        super().__init__()
        self.fh = open(path, "w", encoding="utf-8")

    def write(self, s):
        self.fh.write(s)
        self.fh.flush()
        return super().write(s)

    def close(self):
        self.fh.close()


def run_firmware(board, config):
    """The firmware's console output. Runs in a bridge thread."""
    source = SOURCE
    for name, value in config.items():
        source, n = re.subn(r"(?m)^%s\s*=.*$" % name,
                            lambda m: "%s = %s" % (name, value), source)
        assert n == 1, name
    out = board.out

    def fw_print(*args, sep=" ", end="\n", file=None):
        out.write(sep.join(str(a) for a in args) + end)

    def sleep_us(us):
        board.now_us = _sleep(float(us))

    fake_time = types.SimpleNamespace(
        sleep_us=sleep_us, sleep_ms=lambda ms: sleep_us(1000.0 * ms),
        ticks_ms=lambda: int(board.now_us // 1000),
        ticks_us=lambda: int(board.now_us),
        ticks_diff=lambda a, b: a - b)
    demoboard = types.SimpleNamespace(DemoBoard=types.SimpleNamespace(
        get=lambda: board, _DemoBoardSingleton_Instance=None))
    detect = types.SimpleNamespace(DemoboardDetect=Detect)
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "time":
            return fake_time
        if name == "ttboard.demoboard":
            return demoboard
        if name == "ttboard.boot.demoboard_detect":
            return detect
        return real_import(name, globals, locals, fromlist, level)
    env = {"__name__": "measure_puf_on_rtl",
           "__builtins__": dict(vars(builtins), __import__=fake_import,
                                print=fw_print)}
    exec(compile(source, str(FW / "measure_puf.py"), "exec"), env)
    return out.getvalue()


def rows_of(text):
    lines = text.splitlines()
    head = next(i for i, l in enumerate(lines) if l.startswith("run_id,"))
    rows = [l.split(",") for l in lines[head:] if l and not l.startswith("#")]
    cols = {k: i for i, k in enumerate(rows[0])}
    return cols, rows[1:]


async def run_host(dut, tag, rounds, sweep, sweep_rounds=1, pin_us=5.0,
                   rng=None):
    dut.ena.value = 0
    dut.rst_n.value = 0
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.clk.value = 0
    await Timer(1, "us")
    path = Path(os.environ.get("COSIM_OUT", HERE / "sim_build")) / (
        "cosim_%s.csv" % tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = Console(path)
    board = SimBoard(dut, out, pin_us=pin_us, rng=rng)
    config = {"CHIP_ID": '"cosim_%s"' % tag, "ROUNDS": str(rounds),
              "CLK_SWEEP_HZ": repr(tuple(sweep)),
              "SWEEP_ROUNDS": str(sweep_rounds)}
    try:
        text = await bridge(run_firmware)(board, config)
    finally:
        out.close()

    log = cocotb.log
    swept = sweep_rounds * len(sweep)
    assert "# ERROR" not in text, text[-2000:]
    assert ("# done rounds=%d sweep_rounds=%d timeouts=0 wrapped=0"
            " near_saturation=0 zero_counts=0" % (rounds, swept)) in text
    cols, rows = rows_of(text)
    assert len(rows) == (rounds + swept) * 48, len(rows)
    worst = 0.0
    for r in rows:
        arm, idx = int(r[cols["arm"]]), int(r[cols["idx"]])
        clk = int(r[cols["clk_hz"]])
        want = model_count(arm, idx, 1e12 / clk)
        for col in ("count", "count_first"):
            got = int(r[cols[col]])
            worst = max(worst, abs(got - want))
            assert abs(got - want) <= 2, (tag, col, r, want)
        assert r[cols["overflow"]] == "0", r
    # The project sits in reset through every clock change, runt and all.
    for hz in sweep:
        i = board.log.index("clock %d" % hz)
        assert board.log[i - 1] == "reset True", board.log[i - 3:i + 3]
        assert board.log[i + 1:i + 3] == ["runt", "reset False"], \
            board.log[i - 3:i + 4]
    # First to last reading of a round, in simulated time.
    by_round = {}
    for r in rows:
        by_round.setdefault(int(r[cols["round"]]), []).append(
            int(r[cols["t_ms"]]))
    spans = [max(v) - min(v) for v in by_round.values()]
    log.info("%s host: %d rows, every count within %.2f of the model, a"
             " round's readings spread over %d to %d ms", tag, len(rows),
             worst, min(spans), max(spans))
    groups = analyze_counts.load_files([str(path)])
    g = groups[("cosim_%s" % tag, "room_1v8")]
    assert len(g["by_round"]) == rounds
    assert sum(len(readings) for per_clk in g["sweep"].values()
               for rings in per_clk.values()
               for readings in rings.values()) == 48 * swept
    report = io.StringIO()
    with contextlib.redirect_stdout(report):
        assert analyze_counts.main([str(path)]) == 0
    tail = report.getvalue()
    tail = tail[tail.index("== A ring pulled"):]
    log.info("analyzer, pulling section:\n%s",
             tail.split("\nDescriptive")[0])
    return text


@cocotb.test()
async def typical(dut):
    """5 us a pin operation, two main rounds, two more at 48 MHz."""
    await run_host(dut, "typical", rounds=2, sweep=(48_000_000,),
                   sweep_rounds=2)


@cocotb.test()
async def fast(dut):
    """0.1 us a pin operation, five clock cycles, the tightest timing."""
    await run_host(dut, "fast", rounds=1, sweep=(52_000_000,), pin_us=0.1)


@cocotb.test()
async def uneven(dut):
    """1 to 30 us a pin operation, seeded, two clocks in the sweep."""
    await run_host(dut, "uneven", rounds=1, sweep=(48_000_000, 52_000_000),
                   rng=random.Random(20261028))
