#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Reference model for ro_puf_core, used to check the architecture when no Verilog
simulator is available. It reproduces the testbench: 8 oscillators with
half-period (1500 + 40*i) ps, a 100 MHz reference clock, and a 200-cycle window.
It counts the rising edges that fall inside the window and checks they are
non-zero, distinct, and falling with index.
"""

N_RO           = 8
XCLK_PERIOD_PS = 10_000
WINDOW_CYCLES  = 200
WINDOW_TIME_PS = WINDOW_CYCLES * XCLK_PERIOD_PS


def half_period_ps(i):
    return 1500 + i * 40


def count_for(i):
    half = half_period_ps(i)
    period = 2 * half
    if half >= WINDOW_TIME_PS:
        return 0
    # rising edges at half, half+period, half+2*period, ... while inside window
    return (WINDOW_TIME_PS - half) // period + 1


def main():
    counts = []
    for i in range(N_RO):
        period = 2 * half_period_ps(i)
        c = count_for(i)
        counts.append(c)
        print(f"RO {i}: {1e6 / period:6.1f} MHz -> count = {c}")

    ok = all(c != 0 for c in counts) and all(
        counts[j] < counts[j - 1] for j in range(1, N_RO)
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
