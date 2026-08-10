# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, Timer


WINDOW = 1000
CLK_NS = 20

# A gate-level run swaps Arm A's behavioural oscillator for the real standard
# cells, and sky130's simulation models give combinational cells no delay at
# all. sky130_fd_sc_hd__inv is a bare `not`, a power-good UDP and a `buf` in
# the functional view and in the behavioural view alike, so -DUNIT_DELAY has
# nothing to attach to. An enabled Arm A ring is then a zero-delay feedback
# loop: the simulator cycles it forever at one timestamp and simulated time
# never moves. That is why the gate-level job has been running until CI kills
# it at six hours rather than failing.
#
# Arm B comes through synthesis as a preserved black box driven by
# ro_macro_hard_sim.v, whose half period is a real 1580 ps, so it simulates at
# ordinary speed. Gate-level runs therefore drive Arm B and the whole protocol
# around it, including the sixteen preserved macro enable pins, and leave Arm
# A's frequencies to SPICE and its ring structure to verify_ring_topology.py,
# which reads the same netlist this test elaborates.
GL = os.environ.get("GATES") == "yes"
ARMS = (1,) if GL else (0, 1)
PROTOCOL_ARM = 1 if GL else 0


def budget_us(measurements):
    """Simulated-time ceiling for a test that takes this many measurements.

    One measurement cannot outlast WINDOW reference cycles plus the handshake
    on either side, so twice that is roomy. This catches a handshake that
    stalls. It does not catch the zero-delay loop described above, where time
    does not advance and no simulated-time limit can ever expire; the guard
    for that one is timeout-minutes on the gl_test job in ci/gds.yaml.
    """
    return round(measurements * (WINDOW + 64) * CLK_NS / 1000 * 2 + 20)

async def setup(dut):
    """Start the clock, then reset the design to a known state.

    cocotb starts each test with a fresh scheduler, so the clock is launched
    per test rather than once for the module.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 8)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


def ui_word(arm, idx, *, start=False, high_byte=False):
    return (
        (int(bool(start)) << 0)
        | ((arm & 1) << 1)
        | ((idx & 0xF) << 2)
        | (int(bool(high_byte)) << 6)
    )


def rtl_handles(dut):
    """Return optional pre-synthesis observability points."""
    try:
        core = dut.user_project.u_puf.u_core
        return core.en_window, dut.user_project.armb_en
    except AttributeError:
        return None, None


def hard_macro_enable_handles(dut):
    """Return the preserved Arm-B macro enable pins when they are visible."""
    try:
        top = dut.user_project
        return [getattr(getattr(top, f"u_rob{idx}"), "en") for idx in range(16)]
    except AttributeError:
        return None


async def pulse_start(dut, arm, idx, hold_cycles=3):
    """Meet the async-input protocol, then create one external start edge."""
    base = ui_word(arm, idx)
    await FallingEdge(dut.clk)
    dut.ui_in.value = base
    # The bundled controls must be stable before start crosses the two-flop
    # synchronizer. Three cycles is deliberately more than the required two.
    await ClockCycles(dut.clk, 3)
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(arm, idx, start=True)
    en_window, _ = rtl_handles(dut)
    active_while_held = False
    for _ in range(hold_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if en_window is not None and int(en_window.value) == 1:
            active_while_held = True
    await FallingEdge(dut.clk)
    dut.ui_in.value = base
    return active_while_held


async def wait_for_result(
    dut,
    arm,
    idx,
    *,
    mutate_to=None,
    check_window=True,
    require_rearm=False,
    rearm_low_already_seen=False,
):
    """Wait for a fresh done edge and audit the internal window when visible."""
    en_window, armb_en = rtl_handles(dut)
    saw_done_low = False
    high_cycles = 0
    bad_enable_samples = []
    mutated = False
    saw_rearm_low = (
        not require_rearm or en_window is None or rearm_low_already_seen
    )
    new_window_started = not require_rearm or en_window is None
    macro_enables = hard_macro_enable_handles(dut)

    for elapsed in range(WINDOW + 64):
        await RisingEdge(dut.clk)
        await ReadOnly()

        done = int(dut.uio_out.value) & 1
        if not done:
            saw_done_low = True

        window_high = False
        if en_window is not None:
            window_high = int(en_window.value) == 1

            # During an in-flight restart, ignore the tail of the aborted
            # window. Count only after the required low gap and the next rise.
            if require_rearm and not new_window_started:
                if not window_high:
                    saw_rearm_low = True
                elif saw_rearm_low:
                    new_window_started = True

            if window_high and new_window_started:
                high_cycles += 1

        if armb_en is not None and new_window_started:
            observed = int(armb_en.value)
            expected = (1 << idx) if (window_high and arm == 1) else 0
            if observed != expected:
                bad_enable_samples.append((elapsed, observed, expected))

        # The hard-macro boundary survives synthesis. Reading its actual enable
        # pins catches selector-to-instance permutations that identical output
        # frequencies alone cannot reveal.
        if macro_enables is not None and new_window_started:
            observed = sum(int(handle.value) << bit for bit, handle in enumerate(macro_enables))
            expected = (1 << idx) if (window_high and arm == 1) else 0
            if observed != expected:
                bad_enable_samples.append((elapsed, observed, expected))

        # Change the external selector while the measurement is active. The
        # synchronized, latched selection must remain unchanged until restart.
        do_mutate = mutate_to is not None and not mutated and (
            high_cycles == 50 if en_window is not None else elapsed == 100
        )
        if do_mutate:
            await FallingEdge(dut.clk)
            dut.ui_in.value = ui_word(mutate_to[0], mutate_to[1])
            mutated = True

        if saw_done_low and done and new_window_started:
            break
    else:
        raise AssertionError(f"done timeout for arm={arm}, idx={idx}")

    assert not bad_enable_samples, (
        f"Arm-B enable was not one-hot/quiet for arm={arm}, idx={idx}: "
        f"{bad_enable_samples[:4]}"
    )
    if en_window is not None and check_window:
        assert high_cycles == WINDOW, (
            f"measurement window was {high_cycles} cycles, expected {WINDOW}"
        )


async def read_count(dut, arm, idx):
    """Read the frozen snapshot through both synchronized byte selections."""
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(arm, idx, high_byte=False)
    await ClockCycles(dut.clk, 3)
    low = int(dut.uo_out.value)

    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(arm, idx, high_byte=True)
    await ClockCycles(dut.clk, 3)
    high = int(dut.uo_out.value)

    # The snapshot and done must remain stable while software reads both bytes.
    assert int(dut.uio_out.value) & 1
    await FallingEdge(dut.clk)
    dut.ui_in.value = ui_word(arm, idx)
    return (high << 8) | low


async def measure(
    dut,
    arm,
    idx,
    *,
    hold_start_cycles=3,
    mutate_to=None,
    check_window=True,
    require_active_while_held=False,
):
    active_while_held = await pulse_start(dut, arm, idx, hold_start_cycles)
    en_window, _ = rtl_handles(dut)
    if require_active_while_held and en_window is not None:
        assert active_while_held, "measurement did not start while start stayed high"
    await wait_for_result(
        dut,
        arm,
        idx,
        mutate_to=mutate_to,
        check_window=check_window,
    )
    return await read_count(dut, arm, idx)


@cocotb.test(timeout_time=budget_us(0), timeout_unit="us")
async def test_power_on_defaults(dut):
    """After reset the outputs are quiet and only done drives the bidir bus."""
    await setup(dut)
    assert int(dut.uio_oe.value) == 0x01
    assert int(dut.uio_out.value) == 0
    assert int(dut.uo_out.value) == 0


@cocotb.test(timeout_time=budget_us(len(ARMS) * 16), timeout_unit="us")
async def test_all_selectors_and_bytes(dut):
    """Every arm/index selection measures, and both result bytes read back."""
    await setup(dut)
    counts = {0: [], 1: []}
    en_window, _ = rtl_handles(dut)

    for arm in ARMS:
        for idx in range(16):
            count = await measure(dut, arm, idx)
            counts[arm].append(count)
            dut._log.info("arm=%d idx=%d count=%d", arm, idx, count)
            assert 0 < count < 65536
            assert int(dut.uio_oe.value) == 0x01

    if en_window is not None and 0 in ARMS:
        # Arm A's behavioral model deliberately slows with IDX.
        assert all(a > b for a, b in zip(counts[0], counts[0][1:])), counts[0]
        for idx, count in enumerate(counts[0]):
            half_period_ps = 1500 + idx * 40
            expected = (WINDOW * CLK_NS * 1000) // (2 * half_period_ps)
            assert abs(count - expected) <= 2, (idx, count, expected)

        # The absolute Arm B count is checked against the model only where the
        # rest of the path is behavioural too. Gate-level adds the real counter
        # and readout cells around the same macro model, and I have no measured
        # basis yet for how many counts that is allowed to move.
        expected_b = (WINDOW * CLK_NS * 1000) // (2 * 1580)
        assert all(abs(count - expected_b) <= 2 for count in counts[1])

    if 1 in ARMS:
        # This half holds in both runs. Arm B is the same parameterless macro
        # sixteen times over, so whatever the count is, all sixteen must agree.
        # A selector that lands on the wrong instance, or a readout that mixes
        # bytes between selections, breaks this without needing Arm A.
        assert max(counts[1]) - min(counts[1]) <= 1, counts[1]


@cocotb.test(timeout_time=budget_us(2), timeout_unit="us")
async def test_held_start_is_one_run(dut):
    """Holding start high creates one measurement, not repeated restarts."""
    await setup(dut)
    baseline = await measure(dut, PROTOCOL_ARM, 5)
    held = await measure(
        dut,
        PROTOCOL_ARM,
        5,
        hold_start_cycles=8,
        check_window=False,
        require_active_while_held=True,
    )
    assert abs(held - baseline) <= 2


@cocotb.test(timeout_time=budget_us(2), timeout_unit="us")
async def test_selector_is_latched(dut):
    """Changing arm/index mid-run must not change the captured selection."""
    await setup(dut)
    baseline = await measure(dut, PROTOCOL_ARM, 2)
    # In RTL the mutation crosses arms, and Arm A's model frequencies differ
    # enough that a non-latched selector shows up as a different count. In a
    # gate-level run both selections are Arm B, where every copy toggles at the
    # same rate and the count cannot tell them apart. There the evidence is the
    # one-hot check inside wait_for_result, which reads the sixteen preserved
    # macro enable pins directly and sees the wrong instance turn on.
    latched = await measure(dut, PROTOCOL_ARM, 2, mutate_to=(1, 14))
    assert abs(latched - baseline) <= 2


@cocotb.test(timeout_time=budget_us(3), timeout_unit="us")
async def test_restart_during_measurement(dut):
    """A second start aborts the in-flight run and re-arms cleanly."""
    await setup(dut)
    baseline = await measure(dut, PROTOCOL_ARM, 15)
    await pulse_start(dut, PROTOCOL_ARM, 0)
    await ClockCycles(dut.clk, 100)
    await pulse_start(dut, PROTOCOL_ARM, 15)
    await wait_for_result(
        dut, PROTOCOL_ARM, 15, require_rearm=True, rearm_low_already_seen=True
    )
    restarted = await read_count(dut, PROTOCOL_ARM, 15)
    assert abs(restarted - baseline) <= 2


@cocotb.test(timeout_time=budget_us(2), timeout_unit="us")
async def test_reset_during_measurement(dut):
    """Reset mid-run clears done and the snapshot; the core still works after."""
    await setup(dut)
    await pulse_start(dut, 1, 0)
    await ClockCycles(dut.clk, 50)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 4)
    assert int(dut.uio_out.value) == 0
    assert int(dut.uo_out.value) == 0
    dut.rst_n.value = 1
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, 5)
    assert await measure(dut, 1, 0) > 0


@cocotb.test(timeout_time=budget_us(2), timeout_unit="us")
async def test_deselect_shutdown(dut):
    """Deselecting the project shuts the RO down asynchronously and recovers."""
    await setup(dut)
    en_window, _ = rtl_handles(dut)
    await pulse_start(dut, 1, 3)
    await ClockCycles(dut.clk, 20)
    if en_window is not None:
        assert int(en_window.value) == 1
    await FallingEdge(dut.clk)
    dut.ena.value = 0
    await Timer(1, unit="ns")
    # The shutdown path must not wait for a clock edge; this protects a
    # deselected project whose clock has been stopped.
    assert int(dut.uio_out.value) == 0
    assert int(dut.uo_out.value) == 0
    _, armb_en = rtl_handles(dut)
    if armb_en is not None:
        assert int(armb_en.value) == 0
    dut.ena.value = 1
    dut.ui_in.value = 0
    user_project = getattr(dut, "user_project", None)
    project_rst_n = (
        getattr(user_project, "project_rst_n", None)
        if user_project is not None
        else None
    )
    if project_rst_n is not None:
        assert int(project_rst_n.value) == 0
        await ClockCycles(dut.clk, 1)
        await Timer(1, unit="ns")
        assert int(project_rst_n.value) == 0
        await ClockCycles(dut.clk, 1)
        await Timer(1, unit="ns")
        assert int(project_rst_n.value) == 1
    await ClockCycles(dut.clk, 5)
    assert await measure(dut, PROTOCOL_ARM, 0) > 0
