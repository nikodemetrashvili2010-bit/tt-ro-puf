# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


async def measure(dut, arm, idx):
    """Run one measurement and return the 16-bit count."""
    # ui_in[1] = arm, ui_in[5:2] = ro_idx, ui_in[6] = byte select, ui_in[0] = start
    sel = ((arm & 1) << 1) | ((idx & 0xF) << 2)

    dut.ui_in.value = sel
    await ClockCycles(dut.clk, 2)

    # one start pulse
    dut.ui_in.value = sel | 0x01
    await ClockCycles(dut.clk, 2)
    dut.ui_in.value = sel

    # wait for done on uio_out[0]
    done = 0
    for _ in range(4000):
        await ClockCycles(dut.clk, 1)
        if int(dut.uio_out.value) & 1:
            done = 1
            break
    assert done, f"done did not assert for arm {arm}, idx {idx}"

    # read low byte (byte select 0) then high byte (byte select 1)
    dut.ui_in.value = sel
    await ClockCycles(dut.clk, 2)
    low = int(dut.uo_out.value)

    dut.ui_in.value = sel | 0x40
    await ClockCycles(dut.clk, 2)
    high = int(dut.uo_out.value)

    return (high << 8) | low


@cocotb.test()
async def test_ro_puf(dut):
    dut._log.info("Starting RO-PUF test")
    cocotb.start_soon(Clock(dut.clk, 20, units="ns").start())  # 50 MHz

    # reset
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)

    count_a = await measure(dut, arm=0, idx=0)
    dut._log.info(f"Arm A oscillator 0: count = {count_a}")
    assert count_a > 0, "Arm A count should be non-zero"

    count_b = await measure(dut, arm=1, idx=0)
    dut._log.info(f"Arm B oscillator 0: count = {count_b}")
    assert count_b > 0, "Arm B count should be non-zero"

    dut._log.info("Test passed")
