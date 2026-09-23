# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# Stress runs on the release netlist with every ring simulated. The gate
# level job in test/ can only drive Arm B, because the sky130 functional
# models give an inverter no delay and an enabled Arm A or Arm C ring is
# then a loop that stops simulated time. make_stress_netlist.py swaps the
# 32 cells of each ring for delayed copies with the same ports, so all 48
# rings run here, each at its own frequency, and everything else in the
# netlist is the real sky130 model. tb_stress.v watches all 48 ring
# enables, all 48 ring outputs, uio[5] and uio_oe on every event.
#
# Slot numbering is the selector's: 0..15 Arm A, 16..31 Arm B, 32..47
# Arm C, 48..63 nothing.
#
#   make                            STRESS_SEED=1 STRESS_N=150 by default
#   make COCOTB_TESTCASE=test_random_protocol STRESS_SEED=7 STRESS_N=400
#
# Every run of the whole module so far: 7 of 7 on seeds 1 to 4 against
# run 83's netlist, about three minutes each, 22 September 2026.

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import (ClockCycles, FallingEdge, ReadOnly, RisingEdge,
                             Timer)

WINDOWS = (256, 512, 2048, 16384)
CLK_NS = 20
SEED = int(os.environ.get("STRESS_SEED", "1"))
N_FUZZ = int(os.environ.get("STRESS_N", "150"))


def stage_delay(slot):
    """ps per ring stage. Must match make_stress_netlist.py."""
    arm, i = divmod(slot, 16)
    return (26 + 2 * i, 60 + i, 27 + 2 * i)[arm]


def expected_count(slot, window, clk_ns=CLK_NS):
    """Tap rising edges the counter sees in one run, as (n, n + 1).

    The tap first rises 17 stage delays after the enable and every 62
    after that. When the enable falls the NAND is forced high one stage
    later and a wavefront already past it still reaches the tap, at most
    one more edge. So the count is n or n + 1, n being the edges up to
    the moment the enable falls.
    """
    if slot >= 48:
        return (0, 0)
    d = stage_delay(slot)
    span = window * clk_ns * 1000
    n = (span - 17 * d) // (62 * d) + 1
    return (n, n + 1)


def wraps(slot, window, clk_ns=CLK_NS):
    lo, hi = expected_count(slot, window, clk_ns)
    assert (lo >= 65536) == (hi >= 65536), (slot, window, lo, hi)
    return lo >= 65536


def ui_word(slot, *, start=False, high_byte=False):
    arm, idx = divmod(slot, 16)
    return ((int(bool(start)) << 0) | ((arm & 1) << 1) | ((idx & 0xF) << 2)
            | (int(bool(high_byte)) << 6) | (((arm >> 1) & 1) << 7))


def uio_word(win_sel, rd_ver=False):
    return ((win_sel & 3) << 1) | (int(bool(rd_ver)) << 3)


class Monitors:
    """The testbench counters, read whenever a test wants a verdict."""

    NAMES = ("popcount_violations", "raw_pop_events", "en_x_events",
             "disabled_toggles", "oe_violations", "active_violations",
             "en_rises", "max_pop", "stray_clock_edges", "first_bad_time")
    FATAL = ("popcount_violations", "en_x_events", "disabled_toggles",
             "oe_violations", "active_violations")

    def __init__(self, dut):
        self.dut = dut

    def reset(self):
        for name in self.NAMES:
            getattr(self.dut, name).value = 0

    def snapshot(self):
        return {name: int(getattr(self.dut, name).value)
                for name in self.NAMES}

    def rises(self):
        return int(self.dut.en_rises.value)

    def assert_clean(self, where):
        s = self.snapshot()
        bad = {k: v for k, v in s.items() if k in self.FATAL and v}
        assert not bad, "%s: monitor offences %s, first at %d ns" % (
            where, bad, s["first_bad_time"])


async def setup(dut, clk_ns=CLK_NS, win_sel=0):
    clock = cocotb.start_soon(Clock(dut.clk, clk_ns, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = uio_word(win_sel)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 8)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    Monitors(dut).reset()
    dut.monitors_armed.value = 1
    await ClockCycles(dut.clk, 1)
    return clock


async def pulse_start(dut, slot, hold_cycles=3, settle_cycles=3):
    """Meet the host protocol for one start, and watch the quiet cycle.

    Returns the ripple counter's value just before the window opens,
    which is 0 unless the selector switch clocked the counter (see
    test_restart_carries_one_count). The watch begins before the start
    is driven, because with a long hold the window is already open by
    the time start is dropped. A start while a run is on first waits
    for that run's enable to fall.
    """
    base = ui_word(slot)
    await FallingEdge(dut.clk)
    dut.ui_in.value = base
    await ClockCycles(dut.clk, settle_cycles)
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(slot, start=True)
    carried = None
    value = 0
    watching = False
    for cycle in range(60):
        await RisingEdge(dut.clk)
        await ReadOnly()
        on = int(dut.en_vec.value) != 0 or ((int(dut.uio_out.value) >> 5) & 1)
        if carried is None:
            if not watching:
                if not on:
                    watching = True
                    value = int(dut.cnt_probe.value)
            elif on:
                carried = value
            else:
                value = int(dut.cnt_probe.value)
        if cycle + 1 == hold_cycles:
            await FallingEdge(dut.clk)
            dut.ui_in.value = base
        if carried is not None and cycle + 1 >= hold_cycles:
            return carried
    raise AssertionError("no window opened after the start pulse")


async def wait_done(dut, budget_cycles):
    """Wait for done to go low then high. Returns cycles waited."""
    saw_low = False
    for elapsed in range(budget_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        done = int(dut.uio_out.value) & 1
        if not done:
            saw_low = True
        if saw_low and done:
            return elapsed
    raise AssertionError("done did not rise within %d cycles" % budget_cycles)


async def read_count(dut, slot):
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(slot, high_byte=False)
    await ClockCycles(dut.clk, 3)
    low = int(dut.uo_out.value)
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(slot, high_byte=True)
    await ClockCycles(dut.clk, 3)
    high = int(dut.uo_out.value)
    assert int(dut.uio_out.value) & 1, "done fell during readout"
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(slot)
    return (high << 8) | low


def check_count(slot, window, count, clk_ns=CLK_NS, where="", carried=0):
    """The count is n or n + 1, plus whatever the counter already held
    when the window opened (0 or 1). Returns the excess over n."""
    assert carried in (0, 1), \
        "%s: counter held %d in the quiet cycle" % (where, carried)
    lo, hi = expected_count(slot, window, clk_ns)
    allowed = [(lo + k) % 65536 for k in range(2 + carried)]
    assert count in allowed, \
        "%s slot %d window %d: count %d, expected %d..%d" % (
            where, slot, window, count, lo, hi + carried)
    return allowed.index(count)


async def measure(dut, slot, win_sel, hold_cycles=3, where=""):
    """One measurement the way the firmware does it. Returns (count,
    counter value in the quiet cycle)."""
    window = WINDOWS[win_sel]
    await FallingEdge(dut.clk)
    dut.uio_in.value = uio_word(win_sel)
    await ClockCycles(dut.clk, 3)
    carried = await pulse_start(dut, slot, hold_cycles)
    await wait_done(dut, window + 64)
    count = await read_count(dut, slot)
    check_count(slot, window, count, where=where, carried=carried)
    return count, carried


# ---------------------------------------------------------------------------


@cocotb.test(timeout_time=50, timeout_unit="us")
async def test_power_up_deselected_no_clock(dut):
    """Power-up with ena low and no clock: every flop is X in the model,
    and ena alone has to shut all 48 rings and zero the pins, with no
    clock edge and no rst_n. Then ena high without a clock changes
    nothing, and rst_n low without a clock changes nothing either."""
    dut.clk.value = 0
    dut.rst_n.value = 1          # the worst case: no reset from the host
    dut.ena.value = 0
    dut.ui_in.value = 0xAB       # any host state
    dut.uio_in.value = 0x0E
    await Timer(10, unit="ns")
    en = dut.en_vec.value
    assert en.is_resolvable and int(en) == 0, \
        "enables with ena low, no clock: %s" % en
    assert dut.out_vec.value.is_resolvable, \
        "a ring output is X with ena low: %s" % dut.out_vec.value
    assert int(dut.uio_out.value) == 0, \
        "uio_out %#x with ena low" % int(dut.uio_out.value)
    assert int(dut.uo_out.value) == 0, \
        "uo_out %#x with ena low" % int(dut.uo_out.value)
    assert int(dut.uio_oe.value) == 0x31
    outs0 = int(dut.out_vec.value)
    await Timer(200, unit="ns")
    assert int(dut.out_vec.value) == outs0 and int(dut.en_vec.value) == 0, \
        "a ring moved with ena low"

    # ena high, still no clock: the two-stage release needs clock edges.
    dut.ena.value = 1
    await Timer(200, unit="ns")
    assert int(dut.en_vec.value) == 0 and int(dut.out_vec.value) == outs0, \
        "ena high without a clock woke a ring"
    assert int(dut.uio_out.value) == 0 and int(dut.uo_out.value) == 0

    # rst_n low, no clock.
    dut.rst_n.value = 0
    await Timer(200, unit="ns")
    assert int(dut.en_vec.value) == 0 and int(dut.out_vec.value) == outs0
    mon = Monitors(dut)
    mon.reset()
    dut.monitors_armed.value = 1

    # Now a clock: reset releases after two edges, nothing starts on its own.
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await ClockCycles(dut.clk, 4)
    dut.rst_n.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = uio_word(0)
    await ClockCycles(dut.clk, 50)
    assert int(dut.en_vec.value) == 0 and int(dut.uio_out.value) == 0
    mon.assert_clean("power-up")
    assert mon.rises() == 0

    # And the first measurement after that power-up sequence is a good one.
    count, _ = await measure(dut, 5, 0, where="after power-up")
    assert count > 0
    mon.assert_clean("first measurement after power-up")


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_every_selector_value(dut):
    """All 64 selector codes on the shortest window. The enable logic
    depends only on active_sel[5:0] and en_window (read off the
    netlist), so this sweep is every state it can be in, whatever the
    flops power up as. Each real slot must raise exactly its own enable
    once and count its own ring; a dead slot raises nothing and counts
    zero."""
    await setup(dut)
    mon = Monitors(dut)
    for slot in range(64):
        before = mon.rises()
        await FallingEdge(dut.clk)
        dut.uio_in.value = uio_word(0)
        carried = await pulse_start(dut, slot)
        seen = 0
        saw_low = False
        for _ in range(WINDOWS[0] + 64):
            await RisingEdge(dut.clk)
            await ReadOnly()
            seen |= int(dut.en_vec.value)
            done = int(dut.uio_out.value) & 1
            if not done:
                saw_low = True
            if saw_low and done:
                break
        else:
            raise AssertionError("slot %d: no done" % slot)
        count = await read_count(dut, slot)
        rises = mon.rises() - before
        if slot < 48:
            assert seen == (1 << slot), "slot %d enabled %#x" % (slot, seen)
            assert rises == 1, "slot %d: %d enable rises" % (slot, rises)
        else:
            assert seen == 0 and rises == 0, \
                "dead slot %d enabled %#x" % (slot, seen)
        check_count(slot, WINDOWS[0], count, where="sweep", carried=carried)
        assert not (int(dut.uio_out.value) >> 4) & 1
        dut._log.info("slot %2d count %5d expected %s carried %d", slot, count,
                      expected_count(slot, WINDOWS[0]), carried)
    mon.assert_clean("selector sweep")
    assert mon.snapshot()["max_pop"] == 1


@cocotb.test(timeout_time=60000, timeout_unit="us")
async def test_random_protocol(dut):
    """Seeded random host behaviour against the reference count: normal
    runs on every window, restarts at random points, rst_n and ena
    dropped at random sub-cycle offsets, noise on the control pins
    while idle and while running, short start pulses, version reads.
    Every completed run is checked against its ring, and the monitors
    are checked after every action."""
    rng = random.Random(SEED)
    await setup(dut)
    mon = Monitors(dut)
    overflow_sticky = False
    stored = None          # (slot, count) currently latched, None after reset
    starts = carries = 0   # runs checked, and those that began at 1
    dut._log.info("seed %d, %d actions", SEED, N_FUZZ)

    def pick_slot():
        if rng.random() < 0.9:
            return rng.randrange(48)
        return rng.randrange(48, 64)

    def pick_win():
        r = rng.random()
        return 0 if r < 0.62 else 1 if r < 0.87 else 2 if r < 0.985 else 3

    async def finish(slot, window, carried, where):
        nonlocal starts, carries, overflow_sticky, stored
        await wait_done(dut, window + 64)
        count = await read_count(dut, slot)
        check_count(slot, window, count, where=where, carried=carried)
        starts += 1
        carries += carried
        if wraps(slot, window):
            overflow_sticky = True
        stored = (slot, count)

    for step in range(N_FUZZ):
        action = rng.choices(
            ["measure", "measure_noisy", "restart", "reset_mid", "ena_mid",
             "idle_noise", "short_start", "version"],
            weights=[30, 15, 12, 8, 8, 12, 8, 7])[0]
        where = "step %d %s" % (step, action)
        before = mon.rises()

        if action in ("measure", "measure_noisy"):
            slot, ws = pick_slot(), pick_win()
            window = WINDOWS[ws]
            await FallingEdge(dut.clk)
            dut.uio_in.value = uio_word(ws)
            await ClockCycles(dut.clk, 3)
            carried = await pulse_start(dut, slot, rng.randrange(3, 9))
            if action == "measure_noisy":
                # Wiggle arm, index and byte select while the run is on.
                # The window bits are held: they are read live by design.
                for _ in range(rng.randrange(1, 6)):
                    await ClockCycles(dut.clk, rng.randrange(1, 40))
                    await FallingEdge(dut.clk)
                    dut.ui_in.value = ui_word(rng.randrange(64),
                                              high_byte=rng.random() < 0.5)
                await FallingEdge(dut.clk)
                dut.ui_in.value = ui_word(slot)
            await finish(slot, window, carried, where)
            delta = mon.rises() - before
            assert delta == (1 if slot < 48 else 0), \
                "%s: %d rises" % (where, delta)

        elif action == "restart":
            s1, s2, ws = pick_slot(), pick_slot(), pick_win()
            window = WINDOWS[ws]
            await FallingEdge(dut.clk)
            dut.uio_in.value = uio_word(ws)
            await ClockCycles(dut.clk, 3)
            await pulse_start(dut, s1)
            await ClockCycles(dut.clk, rng.randrange(1, min(window, 400)))
            carried = await pulse_start(dut, s2, rng.randrange(3, 9))
            await finish(s2, window, carried, where)
            delta = mon.rises() - before
            assert (s2 < 48) <= delta <= (s1 < 48) + (s2 < 48), (where, delta)

        elif action in ("reset_mid", "ena_mid"):
            slot, ws = pick_slot(), pick_win()
            await FallingEdge(dut.clk)
            dut.uio_in.value = uio_word(ws)
            await ClockCycles(dut.clk, 3)
            await pulse_start(dut, slot)
            await ClockCycles(dut.clk, rng.randrange(0, 60))
            # At any phase of the clock.
            await Timer(rng.randrange(0, CLK_NS * 1000), unit="ps")
            pin = dut.rst_n if action == "reset_mid" else dut.ena
            pin.value = 0
            await Timer(5, unit="ns")
            # Asynchronous: 5 ns is past the two flop delays of the
            # model and no clock edge is needed for any of it.
            assert int(dut.en_vec.value) == 0, \
                "%s: enables %#x 5 ns after the drop" % (
                    where, int(dut.en_vec.value))
            assert int(dut.uio_out.value) == 0, where
            assert int(dut.uo_out.value) == 0, where
            await Timer(rng.randrange(1, 4) * CLK_NS, unit="ns")
            assert int(dut.en_vec.value) == 0
            pin.value = 1
            dut.ui_in.value = 0
            await ClockCycles(dut.clk, 4)
            assert int(dut.uio_out.value) == 0, \
                "%s: pins not clear after release" % where
            overflow_sticky = False
            stored = None

        elif action == "idle_noise":
            # Anything on the pins with start low starts nothing.
            for _ in range(rng.randrange(2, 12)):
                await FallingEdge(dut.clk)
                dut.ui_in.value = rng.randrange(256) & 0xFE
                dut.uio_in.value = ((rng.randrange(256) & 0xF9)
                                    | (int(dut.uio_in.value) & 0x06))
                await ClockCycles(dut.clk, rng.randrange(1, 6))
            await FallingEdge(dut.clk)
            dut.ui_in.value = 0
            dut.uio_in.value = uio_word(0)
            await ClockCycles(dut.clk, 4)
            assert mon.rises() == before, "%s: a ring started" % where
            if stored is not None:
                assert int(dut.uio_out.value) & 1, "%s: done fell" % where
                count = await read_count(dut, stored[0])
                assert count == stored[1], \
                    "%s: stored count changed %d -> %d" % (
                        where, stored[1], count)

        elif action == "short_start":
            # A start pulse shorter than the protocol asks for, at a
            # random phase. It may or may not be sampled; whichever, the
            # outcome must be a whole measurement or nothing.
            slot = rng.randrange(48)
            await FallingEdge(dut.clk)
            dut.uio_in.value = uio_word(0)
            dut.ui_in.value = ui_word(slot)
            await ClockCycles(dut.clk, 3)
            await Timer(rng.randrange(0, CLK_NS * 1000), unit="ps")
            dut.ui_in.value = ui_word(slot, start=True)
            await Timer(rng.randrange(200, 6000), unit="ps")
            dut.ui_in.value = ui_word(slot)
            await ClockCycles(dut.clk, 6)
            await ReadOnly()
            if mon.rises() > before:
                await wait_done(dut, WINDOWS[0] + 64)
                count = await read_count(dut, slot)
                check_count(slot, WINDOWS[0], count, where=where, carried=1)
                stored = (slot, count)
            else:
                assert mon.rises() == before

        elif action == "version":
            for high, want in ((False, 2), (True, 0x1A)):
                await FallingEdge(dut.clk)
                dut.uio_in.value = uio_word(0, rd_ver=True)
                dut.ui_in.value = ui_word(rng.randrange(64), high_byte=high)
                await ClockCycles(dut.clk, 3)
                await ReadOnly()
                assert int(dut.uo_out.value) == want, \
                    "%s: version byte %#x" % (where, int(dut.uo_out.value))
            await FallingEdge(dut.clk)
            dut.uio_in.value = uio_word(0)
            dut.ui_in.value = 0
            await ClockCycles(dut.clk, 3)
            if stored is not None:
                count = await read_count(dut, stored[0])
                assert count == stored[1], \
                    "%s: version read disturbed the count" % where

        await FallingEdge(dut.clk)
        flag = (int(dut.uio_out.value) >> 4) & 1
        assert flag == int(overflow_sticky), \
            "%s: overflow flag %d, expected %d" % (
                where, flag, overflow_sticky)
        assert int(dut.uio_oe.value) == 0x31
        mon.assert_clean(where)

    s = mon.snapshot()
    dut._log.info("seed %d: %d runs checked, %d began with the counter at 1; "
                  "%d enable rises, max_pop %d, delta-cycle pop>1 events %d",
                  SEED, starts, carries, s["en_rises"], s["max_pop"],
                  s["raw_pop_events"])


@cocotb.test(timeout_time=3000, timeout_unit="us")
async def test_window_changed_while_running(dut):
    """The window bits are read live, not latched at start. Switching
    from 2048 to 256 with the timer past 256 makes the run go on until
    the 16-bit timer wraps back round to 255: about 65k cycles, one ring
    on the whole time, the counter wrapping and the flag set. It must
    end on its own, with one ring only, and the next run must be
    normal."""
    await setup(dut)
    mon = Monitors(dut)
    slot = 31                    # the slowest ring, 75 ps a stage
    await FallingEdge(dut.clk)
    dut.uio_in.value = uio_word(2)
    await ClockCycles(dut.clk, 3)
    await pulse_start(dut, slot)
    await ClockCycles(dut.clk, 600)
    await FallingEdge(dut.clk)
    dut.uio_in.value = uio_word(0)
    elapsed = await wait_done(dut, 65536 + 512)
    dut._log.info("done after %d more cycles", elapsed)
    assert elapsed > 60000, "the run ended early at %d cycles" % elapsed
    assert (int(dut.uio_out.value) >> 4) & 1, \
        "no overflow flag after a 65k cycle run"
    assert mon.rises() == 1
    await read_count(dut, slot)
    mon.assert_clean("window change")
    count, _ = await measure(dut, 3, 0, where="after the long run")
    assert count > 0
    assert (int(dut.uio_out.value) >> 4) & 1, "flag lost"
    mon.assert_clean("after window change")


@cocotb.test(timeout_time=20000, timeout_unit="us")
async def test_reference_clock_extremes(dut):
    """The count scales with the reference clock: 100 MHz and 12.5 MHz
    against the model for each ring, and the wrap: at 12.5 MHz the 2048
    window is 164 us and the fastest ring wraps, at 100 MHz nothing
    does on 2048."""
    for clk_ns, slots in ((10, (0, 15, 16, 31, 32, 47)), (80, (0, 31, 47))):
        clock = await setup(dut, clk_ns=clk_ns)
        mon = Monitors(dut)
        for slot in slots:
            for ws in (0, 2):
                window = WINDOWS[ws]
                await FallingEdge(dut.clk)
                dut.uio_in.value = uio_word(ws)
                await ClockCycles(dut.clk, 3)
                carried = await pulse_start(dut, slot)
                await wait_done(dut, window + 64)
                count = await read_count(dut, slot)
                check_count(slot, window, count, clk_ns=clk_ns,
                            where="clk %d ns" % clk_ns, carried=carried)
                flag = (int(dut.uio_out.value) >> 4) & 1
                dut._log.info("clk %d ns slot %d window %d count %d flag %d",
                              clk_ns, slot, window, count, flag)
                assert flag == int(wraps(slot, window, clk_ns)), \
                    (clk_ns, slot, window, count, flag)
                if flag:
                    await FallingEdge(dut.clk)
                    dut.rst_n.value = 0
                    await ClockCycles(dut.clk, 3)
                    dut.rst_n.value = 1
                    dut.ui_in.value = 0
                    await ClockCycles(dut.clk, 4)
        mon.assert_clean("clock %d ns" % clk_ns)
        clock.cancel()
        await Timer(1, unit="ns")
        dut.clk.value = 0
        await Timer(clk_ns, unit="ns")


@cocotb.test(timeout_time=30000, timeout_unit="us")
async def test_soak_all_rings_long_window(dut):
    """Every real slot on the 2048 window back to back, then the 16384
    overflow window on eight of them, checking counts, one-hot, and the
    sticky flag through it all."""
    await setup(dut)
    mon = Monitors(dut)
    for slot in range(48):
        await measure(dut, slot, 2, where="soak 2048")
        assert not (int(dut.uio_out.value) >> 4) & 1
    mon.assert_clean("soak 2048")
    for slot in (0, 15, 16, 31, 32, 47, 7, 40):
        await measure(dut, slot, 3, where="soak 16384")
        assert (int(dut.uio_out.value) >> 4) & 1, \
            "slot %d: no flag on 16384" % slot
    assert mon.rises() == 56, mon.snapshot()
    mon.assert_clean("soak 16384")


@cocotb.test(timeout_time=200000, timeout_unit="us")
async def test_restart_carries_one_count(dut):
    """The edge that takes a start does three things at once: the
    selector flops switch the counter clock mux, the old ring's enable
    falls, and the counter's reset is released. The mux tree has a
    static-0 hazard (sim/mux_hazard.py lists where), so the switch
    can clock the counter once, and a ring stopped by a restart can
    still deliver its draining edge. Either way the new run may begin
    with the counter at 1 and never more. This pins that bound, on
    restarts while a ring runs and on starts from idle, and checks
    that a second start on the same slot, which moves nothing, begins
    at 0."""
    await setup(dut)
    mon = Monitors(dut)
    rows = []
    for s1 in (20, 0, 47, 31, 5, 33):
        for s2 in (41, 20, 6, 0, 47):
            for gap in range(1, 25):
                await FallingEdge(dut.clk)
                dut.uio_in.value = uio_word(0)
                await ClockCycles(dut.clk, 2)
                await pulse_start(dut, s1)
                await ClockCycles(dut.clk, gap)
                carried = await pulse_start(dut, s2, 3)
                await wait_done(dut, WINDOWS[0] + 64)
                count = await read_count(dut, s2)
                excess = check_count(
                    s2, WINDOWS[0], count, carried=carried,
                    where="restart %d->%d gap %d" % (s1, s2, gap))
                rows.append((s1, s2, gap, carried, excess))
    over = [r for r in rows if r[4] == 2]
    dut._log.info("restarts %d, counter at 1 in the quiet cycle %d, "
                  "count n+2 %d", len(rows), sum(r[3] for r in rows),
                  len(over))
    by_pair = {}
    for r in rows:
        if r[3]:
            by_pair[(r[0], r[1])] = by_pair.get((r[0], r[1]), 0) + 1
    dut._log.info("(s1, s2) -> restarts of 24 that began at 1: %s",
                  sorted(by_pair.items()))

    # Starts from idle, then the same slot again after done.
    first = second = 0
    for prev, nxt in ((0, 41), (5, 40), (20, 42), (31, 43), (47, 41), (33, 41),
                      (41, 0), (2, 3), (16, 17), (32, 33), (46, 47), (63, 1)):
        await FallingEdge(dut.clk)
        dut.uio_in.value = uio_word(0)
        await ClockCycles(dut.clk, 1)
        await measure(dut, prev, 0, where="idle %d" % prev)
        _, c1 = await measure(dut, nxt, 0, where="idle %d->%d" % (prev, nxt))
        _, c2 = await measure(dut, nxt, 0, where="again %d" % nxt)
        first += c1
        second += c2
        assert c2 == 0, "a repeated start on slot %d began at %d" % (nxt, c2)
    dut._log.info("starts from idle that began at 1: %d of 12; "
                  "repeated starts: %d", first, second)
    mon.assert_clean("restart")
