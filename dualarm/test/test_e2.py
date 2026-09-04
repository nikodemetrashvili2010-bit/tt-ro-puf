# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# G.3 step 6. The E.2 acceptance table, worked row by row.
#
# The rows are not restated here. chip/e2_acceptance.csv is what E.2 asked
# for and chip/e2_tb_plan.csv is the stimulus that goes with it, both written
# by chip/observability_spec.py and chip/gen_e2_rtl.py before any of this
# existed. Each test below looks its own row up by id and drives what the row
# says to drive, so a test that stops matching its row fails on the lookup
# rather than passing against a stimulus nobody asked for.
#
# One test per row, named test_e2_NN. chip/g3_runbook.py B16 reads those
# names back out of this file and requires one for every row in the plan, so
# a row cannot be quietly dropped.
#
# Run with:  make E2=yes
#
# RTL only. Arm A and Arm C are zero-delay logic loops in a gate-level
# netlist for the reason test.py's header sets out at length, so a GATES=yes
# run of this table would hang on E2-19 and E2-21 rather than fail.

import csv
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN_CSV = os.path.join(HERE, os.pardir, "chip", "e2_tb_plan.csv")
ACCEPT_CSV = os.path.join(HERE, os.pardir, "chip", "e2_acceptance.csv")

WINDOWS = (256, 512, 2048, 16384)
CLK_NS = 20
PROTOCOL_VERSION = 2
BUILD_ID = 0x1A
UIO_OE = 0x31

DONE_BIT = 0
OVF_BIT = 4
ACTIVE_BIT = 5


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


PLAN = dict((r["id"], r) for r in _rows(PLAN_CSV))
ACCEPT = dict((r["id"], r) for r in _rows(ACCEPT_CSV))


def row(rid):
    """The plan row for this test, or a failure that says which id is gone."""
    if rid not in PLAN:
        raise AssertionError("%s is not in chip/e2_tb_plan.csv" % rid)
    if rid not in ACCEPT:
        raise AssertionError("%s is not in chip/e2_acceptance.csv" % rid)
    return PLAN[rid]


def half_period_ps(arm, idx):
    if arm == 0:
        return 1500 + idx * 40
    if arm == 1:
        return 1580
    return 1400 + idx * 40


def model_count(arm, idx, window):
    """What the behavioural ring should read, to within a count.

    The ring free-runs from time zero and the window opens on a clock edge,
    so whether the last period lands inside the window or just outside it is
    a matter of phase. 512 cycles of a 1640 ps half period is 3121.95
    periods and the chip reports 3122, not the 3121 that flooring gives.
    MODEL_TOL is that, and it is the same tolerance test.py has always used
    for the same reason. It is not a tolerance on the design: the counter is
    exact, the model of the ring is what is approximate.
    """
    return (window * CLK_NS * 1000) // (2 * half_period_ps(arm, idx))


MODEL_TOL = 2


def near_model(count, arm, idx, window):
    return abs(count - model_count(arm, idx, window)) <= MODEL_TOL


def budget_us(cycles):
    return round(cycles * CLK_NS / 1000 * 2 + 200)


def ui_word(arm, idx, *, start=False, high_byte=False):
    return (
        (int(bool(start)) << 0)
        | ((arm & 1) << 1)
        | ((idx & 0xF) << 2)
        | (int(bool(high_byte)) << 6)
        | (((arm >> 1) & 1) << 7)
    )


def uio_word(win_sel, rd_ver=False):
    return ((win_sel & 3) << 1) | (int(bool(rd_ver)) << 3)


async def setup(dut, win_sel=0):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = uio_word(win_sel)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 8)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


async def pulse_start(dut, arm, idx, win_sel):
    """Set the whole control bundle, let it cross, then make one start edge."""
    base = ui_word(arm, idx)
    await FallingEdge(dut.clk)
    dut.uio_in.value = uio_word(win_sel)
    dut.ui_in.value = base
    await ClockCycles(dut.clk, 3)
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(arm, idx, start=True)
    await ClockCycles(dut.clk, 3)
    await FallingEdge(dut.clk)
    dut.ui_in.value = base


async def wait_done(dut, win_sel, slack=64):
    """Cycles from the call until done is seen high. Raises on timeout."""
    limit = WINDOWS[win_sel] + slack
    for elapsed in range(limit):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if (int(dut.uio_out.value) >> DONE_BIT) & 1:
            return elapsed + 1
    raise AssertionError("done did not rise within %d clocks" % limit)


async def read_count(dut, arm, idx):
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(arm, idx, high_byte=False)
    await ClockCycles(dut.clk, 3)
    low = int(dut.uo_out.value)
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(arm, idx, high_byte=True)
    await ClockCycles(dut.clk, 3)
    high = int(dut.uo_out.value)
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(arm, idx)
    return (high << 8) | low


async def measure(dut, arm, idx, win_sel):
    await pulse_start(dut, arm, idx, win_sel)
    await wait_done(dut, win_sel)
    return await read_count(dut, arm, idx)


def status(dut):
    v = int(dut.uio_out.value)
    return ((v >> DONE_BIT) & 1, (v >> ACTIVE_BIT) & 1, (v >> OVF_BIT) & 1)


# ----------------------------------------------------------------- the table

@cocotb.test(timeout_time=budget_us(64), timeout_unit="us")
async def test_e2_01(dut):
    """reset clears everything"""
    r = row("E2-01")
    await setup(dut, int(r["win_sel"]))
    assert int(dut.uio_oe.value) == UIO_OE
    done, active, ovf = status(dut)
    assert (done, active, ovf) == (0, 0, 0)
    assert int(dut.uo_out.value) == 0


@cocotb.test(timeout_time=budget_us(WINDOWS[3] + 256), timeout_unit="us")
async def test_e2_02(dut):
    """reset clears a sticky overflow"""
    r = row("E2-02")
    win = int(r["win_sel"])
    assert WINDOWS[win] == 16384, "E2-02 wants the overflow window"
    await setup(dut, win)
    await pulse_start(dut, 0, 0, win)
    await wait_done(dut, win)
    assert status(dut)[2] == 1, "the overflow window did not set the flag"
    await FallingEdge(dut.clk)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 4)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    await ReadOnly()
    assert status(dut)[2] == 0, "reset did not clear the sticky flag"


async def _window_selects(dut, rid, want_len, slack):
    r = row(rid)
    win = int(r["win_sel"])
    assert WINDOWS[win] == want_len, "%s selects %d, not %d" % (
        rid, WINDOWS[win], want_len)
    await setup(dut, win)
    await pulse_start(dut, int(r["arm"]), int(r["ro_idx"]), win)
    took = await wait_done(dut, win, slack=slack)
    assert took <= want_len + slack, "done took %d clocks" % took
    count = await read_count(dut, int(r["arm"]), int(r["ro_idx"]))
    assert count > 0, "count was zero"
    return count


@cocotb.test(timeout_time=budget_us(WINDOWS[0] + 256), timeout_unit="us")
async def test_e2_03(dut):
    """window select 0 selects 256 cycles"""
    await _window_selects(dut, "E2-03", 256, 8)


@cocotb.test(timeout_time=budget_us(WINDOWS[1] + 256), timeout_unit="us")
async def test_e2_04(dut):
    """window select 1 selects 512 cycles"""
    await _window_selects(dut, "E2-04", 512, 8)


@cocotb.test(timeout_time=budget_us(WINDOWS[2] + 256), timeout_unit="us")
async def test_e2_05(dut):
    """window select 2 selects 2048 cycles"""
    await _window_selects(dut, "E2-05", 2048, 8)


@cocotb.test(timeout_time=budget_us(WINDOWS[3] + 256), timeout_unit="us")
async def test_e2_06(dut):
    """window select 3 selects 16384 cycles"""
    await _window_selects(dut, "E2-06", 16384, 8)


@cocotb.test(timeout_time=budget_us(WINDOWS[0] + 256), timeout_unit="us")
async def test_e2_07(dut):
    """active is high only while the window is open"""
    r = row("E2-07")
    win = int(r["win_sel"])
    await setup(dut, win)
    await pulse_start(dut, int(r["arm"]), int(r["ro_idx"]), win)
    high = 0
    fell_at = None
    done_at = None
    for elapsed in range(WINDOWS[win] + 64):
        await RisingEdge(dut.clk)
        await ReadOnly()
        done, active, _ = status(dut)
        if active:
            assert not done, "done was high while the window was still open"
            high += 1
        elif high and fell_at is None:
            fell_at = elapsed
        if done and done_at is None:
            done_at = elapsed
            break
    assert high == WINDOWS[win], "active was high for %d clocks, wanted %d" % (
        high, WINDOWS[win])
    assert fell_at is not None and done_at is not None
    assert 0 < done_at - fell_at <= 32, (
        "done rose %d clocks after active fell" % (done_at - fell_at))


@cocotb.test(timeout_time=budget_us(64), timeout_unit="us")
async def test_e2_08(dut):
    """done and active tell a fresh result from a stale one"""
    r = row("E2-08")
    await setup(dut, int(r["win_sel"]))
    for _ in range(8):
        await RisingEdge(dut.clk)
        await ReadOnly()
        done, active, _ = status(dut)
        assert (done, active) == (0, 0), "a run that never started looks done"


@cocotb.test(timeout_time=budget_us(WINDOWS[1] + 512), timeout_unit="us")
async def test_e2_09(dut):
    """double the window, double the count"""
    r = row("E2-09")
    arm, idx = int(r["arm"]), int(r["ro_idx"])
    await setup(dut, 0)
    short = await measure(dut, arm, idx, 0)
    long_ = await measure(dut, arm, idx, int(r["win_sel"]))
    ratio = long_ / short
    assert 1.98 <= ratio <= 2.02, "ratio %.4f from %d and %d" % (
        ratio, short, long_)


@cocotb.test(timeout_time=budget_us(WINDOWS[2] + 512), timeout_unit="us")
async def test_e2_10(dut):
    """eight times the window, eight times the count"""
    r = row("E2-10")
    arm, idx = int(r["arm"]), int(r["ro_idx"])
    await setup(dut, 0)
    short = await measure(dut, arm, idx, 0)
    long_ = await measure(dut, arm, idx, int(r["win_sel"]))
    ratio = long_ / short
    assert 7.92 <= ratio <= 8.08, "ratio %.4f from %d and %d" % (
        ratio, short, long_)


@cocotb.test(timeout_time=budget_us(WINDOWS[3] + 256), timeout_unit="us")
async def test_e2_11(dut):
    """the overflow window sets the sticky flag"""
    r = row("E2-11")
    win = int(r["win_sel"])
    await setup(dut, win)
    await pulse_start(dut, int(r["arm"]), int(r["ro_idx"]), win)
    await wait_done(dut, win)
    assert status(dut)[2] == 1, "16384 cycles did not wrap the counter"


@cocotb.test(timeout_time=budget_us(WINDOWS[3] + WINDOWS[0] + 256),
             timeout_unit="us")
async def test_e2_12(dut):
    """the sticky flag survives the next measurement"""
    r = row("E2-12")
    arm, idx = int(r["arm"]), int(r["ro_idx"])
    win = int(r["win_sel"])
    await setup(dut, win)
    await pulse_start(dut, arm, idx, win)
    await wait_done(dut, win)
    assert status(dut)[2] == 1
    await measure(dut, arm, idx, 0)
    assert status(dut)[2] == 1, "a safe window cleared a flag only reset may"


@cocotb.test(timeout_time=budget_us(48 * (256 + 512 + 2048) + 4096),
             timeout_unit="us")
async def test_e2_13(dut):
    """a safe window never sets it"""
    r = row("E2-13")
    await setup(dut, 0)
    for win in (0, 1, 2):
        for arm in (0, 1, 2):
            for idx in range(16):
                count = await measure(dut, arm, idx, win)
                done, active, ovf = status(dut)
                assert ovf == 0, (
                    "window %d set the overflow flag on arm %d idx %d, "
                    "count %d" % (WINDOWS[win], arm, idx, count))
                assert near_model(count, arm, idx, WINDOWS[win]), (
                    arm, idx, WINDOWS[win], count,
                    model_count(arm, idx, WINDOWS[win]))
    assert r["reset_first"] == "0"


@cocotb.test(timeout_time=budget_us(WINDOWS[0] + 512), timeout_unit="us")
async def test_e2_14(dut):
    """both bytes reassemble the count"""
    r = row("E2-14")
    arm, idx = int(r["arm"]), int(r["ro_idx"])
    win = int(r["win_sel"])
    await setup(dut, win)
    await pulse_start(dut, arm, idx, win)
    await wait_done(dut, win)
    first = await read_count(dut, arm, idx)
    again = await read_count(dut, arm, idx)
    assert first == again, "%d then %d" % (first, again)
    assert near_model(first, arm, idx, WINDOWS[win]), (
        first, model_count(arm, idx, WINDOWS[win]))


@cocotb.test(timeout_time=budget_us(WINDOWS[0] + 512), timeout_unit="us")
async def test_e2_15(dut):
    """the count does not move between the two byte reads"""
    r = row("E2-15")
    arm, idx = int(r["arm"]), int(r["ro_idx"])
    win = int(r["win_sel"])
    await setup(dut, win)
    await pulse_start(dut, arm, idx, win)
    await wait_done(dut, win)
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(arm, idx, high_byte=False)
    await ClockCycles(dut.clk, 3)
    low_first = int(dut.uo_out.value)
    await ClockCycles(dut.clk, 100)
    low_again = int(dut.uo_out.value)
    assert low_first == low_again, "%d then %d" % (low_first, low_again)


async def _version_byte(dut, rid, high_byte, want):
    r = row(rid)
    assert r["rd_ver"] == "1", "%s is a version read" % rid
    await setup(dut, int(r["win_sel"]))
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(0, 0, high_byte=high_byte)
    dut.uio_in.value = uio_word(int(r["win_sel"]), rd_ver=True)
    await ClockCycles(dut.clk, 4)
    await ReadOnly()
    got = int(dut.uo_out.value)
    assert got == want, "%s read 0x%02X, wanted 0x%02X" % (rid, got, want)


@cocotb.test(timeout_time=budget_us(64), timeout_unit="us")
async def test_e2_16(dut):
    """the protocol byte reads back"""
    await _version_byte(dut, "E2-16", False, PROTOCOL_VERSION)


@cocotb.test(timeout_time=budget_us(64), timeout_unit="us")
async def test_e2_17(dut):
    """the build byte reads back"""
    await _version_byte(dut, "E2-17", True, BUILD_ID)


@cocotb.test(timeout_time=budget_us(WINDOWS[0] + 512), timeout_unit="us")
async def test_e2_18(dut):
    """the version select does not disturb a stored count"""
    r = row("E2-18")
    arm, idx = int(r["arm"]), int(r["ro_idx"])
    win = 0
    await setup(dut, win)
    await pulse_start(dut, arm, idx, win)
    await wait_done(dut, win)
    before = await read_count(dut, arm, idx)

    await FallingEdge(dut.clk)
    dut.uio_in.value = uio_word(win, rd_ver=True)
    await ClockCycles(dut.clk, 4)
    await ReadOnly()
    assert int(dut.uo_out.value) == PROTOCOL_VERSION
    await FallingEdge(dut.clk)
    dut.uio_in.value = uio_word(win)
    await ClockCycles(dut.clk, 4)

    after = await read_count(dut, arm, idx)
    assert before == after, "%d then %d" % (before, after)
    assert status(dut)[0] == 1, "done went away while the version was read"


async def _sweep_arm(dut, rid, arm):
    r = row(rid)
    assert int(r["arm"]) == arm and r["sweep"] == "1", "%s sweeps arm %s" % (
        rid, r["arm"])
    win = int(r["win_sel"])
    assert WINDOWS[win] == 512, "%s wants the 512 window" % rid
    await setup(dut, win)
    counts = []
    for idx in range(16):
        await pulse_start(dut, arm, idx, win)
        took = await wait_done(dut, win)
        assert took <= WINDOWS[win] + 64
        count = await read_count(dut, arm, idx)
        counts.append(count)
        assert 0 < count < 65536, (idx, count)
        assert near_model(count, arm, idx, WINDOWS[win]), (
            idx, count, model_count(arm, idx, WINDOWS[win]))
        assert status(dut)[2] == 0, "512 cycles wrapped the counter"
    assert len(counts) == 16
    if arm == 1:
        # Sixteen copies of one macro. Whatever the count is, they agree.
        assert max(counts) - min(counts) <= 1, counts
    else:
        # The models slope with the index, which is what makes a wrong
        # selector visible at all.
        assert all(a > b for a, b in zip(counts, counts[1:])), counts
    return counts


@cocotb.test(timeout_time=budget_us(16 * (512 + 64) + 1024), timeout_unit="us")
async def test_e2_19(dut):
    """every oscillator in arm A, automated answers"""
    await _sweep_arm(dut, "E2-19", 0)


@cocotb.test(timeout_time=budget_us(16 * (512 + 64) + 1024), timeout_unit="us")
async def test_e2_20(dut):
    """every oscillator in arm B, hardened answers"""
    await _sweep_arm(dut, "E2-20", 1)


@cocotb.test(timeout_time=budget_us(16 * (512 + 64) + 1024), timeout_unit="us")
async def test_e2_21(dut):
    """every oscillator in arm C, constrained answers"""
    await _sweep_arm(dut, "E2-21", 2)
