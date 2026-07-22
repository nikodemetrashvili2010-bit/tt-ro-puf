# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# Reads every oscillator of the two-arm RO-PUF on the TinyTapeout demo board.
# Runs on the board itself (MicroPython, TT SDK v3). Prints CSV to the USB
# console, so from the PC you just do:
#
#   mpremote run measure_puf.py > chip01_room_1v8.csv
#
# Chip protocol (from tt_um_ro_puf.v):
#   ui[0] start (hold high for at least 3 clk cycles),
#   ui[1] arm (0=A auto, 1=B matched),
#   ui[5:2] oscillator index, ui[6] byte select (0 low, 1 high),
#   uo[7:0] selected count byte, uio[0] done (high = count valid).
#   The current RTL fixes WINDOW at 1000 reference-clock cycles.
#
# Clock choice: count = f_osc * WINDOW / f_clk. The counter is 16 bit
# (ceiling 65535). At CLK_HZ = 25 MHz the window is 40 us, a 570 MHz
# nominal post-layout oscillator would read about 22800, and the 16-bit ceiling
# corresponds to about 1.6 GHz. Check the observed counts for saturation; a
# lower reference clock reduces this headroom.

import time
from ttboard.demoboard import DemoBoard

PROJECT  = "tt_um_nikodemetrashvili20_ro_puf"
CLK_HZ   = 25_000_000
WINDOW   = 1000
REPEATS  = 5          # samples per oscillator; raise for noise studies
# The first underscore separates chip id from condition for analyze_counts.py.
# Keep the chip id unchanged when measuring that device under another condition.
LABEL    = "chip01_room_1v8"
TIMEOUT_MS = 200

tt = DemoBoard.get()


def _ui(start, arm, idx, byte_sel):
    return (start & 1) | ((arm & 1) << 1) | ((idx & 0xF) << 2) | ((byte_sel & 1) << 6)


def measure_one(arm, idx):
    """One measurement. Returns the 16-bit count or -1 on timeout."""
    base = _ui(0, arm, idx, 0)
    tt.ui_in.value = base
    time.sleep_ms(1)
    # One millisecond is far longer than the three-clock minimum at 25 MHz.
    # Keep arm/index unchanged through the transaction.
    tt.ui_in.value = base | 1
    time.sleep_ms(1)
    tt.ui_in.value = base
    # window is 40 us at 25 MHz; poll done with a generous timeout
    t0 = time.ticks_ms()
    while not tt.uio_out[0]:
        if time.ticks_diff(time.ticks_ms(), t0) > TIMEOUT_MS:
            return -1
    lo = int(tt.uo_out.value)
    tt.ui_in.value = _ui(0, arm, idx, 1)
    time.sleep_ms(1)
    hi = int(tt.uo_out.value)
    tt.ui_in.value = base
    return (hi << 8) | lo


def run(label=LABEL, repeats=REPEATS):
    proj = getattr(tt.shuttle, PROJECT, None)
    if proj is None:
        matches = tt.shuttle.find("ro_puf")
        if not matches:
            print("# ERROR: project not found in shuttle index")
            return
        proj = matches[0]
    proj.enable()
    tt.clock_project_PWM(CLK_HZ)
    tt.reset_project(True)
    time.sleep_ms(10)
    tt.reset_project(False)
    time.sleep_ms(10)

    print("# tt_ro_puf measurement, label=%s clk=%d window=%d repeats=%d"
          % (label, CLK_HZ, WINDOW, repeats))
    print("label,arm,idx,sample,count")
    bad = 0
    for arm in (0, 1):
        for idx in range(16):
            for s in range(repeats):
                c = measure_one(arm, idx)
                if c < 0:
                    bad += 1
                print("%s,%d,%d,%d,%d" % (label, arm, idx, s, c))
    print("# done, timeouts=%d" % bad)
    tt.clock_project_stop()


run()
