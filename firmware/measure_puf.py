# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# Acquisition firmware for the two-arm RO-PUF on the TinyTapeout demo board.
# Runs on the board (MicroPython, TT SDK v3). Prints a metadata header plus one
# CSV row per sample to the USB console:
#
#   mpremote run measure_puf.py > chip01_room_1v8.csv
#
# Fill in the CONFIG block below for each run. The chip id, the measured supply
# voltage, and the measured temperature are not guessed by the script: a label
# like "room_1v8" is a nominal setting, not a measurement, so record what you
# actually measured.
#
# Chip protocol (from tt_um_ro_puf.v):
#   ui[0] start (hold high for at least three clk cycles),
#   ui[1] arm (0 = A auto-placed, 1 = B matched macro),
#   ui[5:2] oscillator index, ui[6] byte select (0 low, 1 high),
#   uo[7:0] selected count byte, uio[0] done (high = count valid).
#   WINDOW is fixed at 1000 reference-clock cycles in the current RTL.
#
# Clock choice: count = f_osc * WINDOW / f_clk. The counter is 16 bit
# (ceiling 65535). At CLK_HZ = 25 MHz the window is 40 us, a 570 MHz nominal
# oscillator reads about 22800, and the 16-bit ceiling is about 1.6 GHz. The
# script flags any count near the ceiling, but you should confirm the fastest
# process corner cannot overflow before trusting a run.
#
# Ordering: samples are taken in randomized rounds. Each round measures all 32
# (arm, idx) selections once in a fresh random order, and the run repeats that
# for ROUNDS rounds. This keeps arm and oscillator index from being correlated
# with acquisition time (a plain arm-by-arm sweep would confound slow thermal
# or supply drift with arm identity). The random seed and the per-sample
# timestamp are recorded so the order is reproducible and any drift is visible.

import time
import random

from ttboard.demoboard import DemoBoard

# ---- CONFIG: set these per run ------------------------------------------
CHIP_ID    = "chip01"        # stable anonymous id for this physical die
CONDITION  = "room_1v8"      # nominal condition label (not a measurement)
SHUTTLE    = "ttsky26c"      # shuttle the die came from
BOARD_REV  = "unknown"       # demo board / devkit revision
SITE       = "unknown"       # operator or measurement site id
CLK_HZ     = 25_000_000      # requested project clock
MEAS_CLK_HZ = 0              # measured project clock in Hz, 0 if not measured
MEAS_VDD_V  = 0.0            # measured core supply in volts, 0.0 if not measured
TEMP_METHOD = "none"         # e.g. "ambient", "thermocouple_on_package"
MEAS_TEMP_C = None           # measured temperature in C, None if not measured
NOTES       = ""             # free text
ROUNDS      = 60             # randomized rounds; raise for a real dataset
TIMEOUT_MS  = 200
# -------------------------------------------------------------------------

SCRIPT_VERSION = "measure_puf/2"
WINDOW = 1000
SAT_WARN = 65000             # warn when a count gets this close to the ceiling
N_ARM = 2
N_IDX = 16
PROJECT = "tt_um_nikodemetrashvili20_ro_puf"

tt = DemoBoard.get()


def _ui(start, arm, idx, byte_sel):
    return (start & 1) | ((arm & 1) << 1) | ((idx & 0xF) << 2) | ((byte_sel & 1) << 6)


def measure_one(arm, idx):
    """One measurement. Returns the 16-bit count or -1 on timeout."""
    base = _ui(0, arm, idx, 0)
    tt.ui_in.value = base
    time.sleep_ms(1)
    tt.ui_in.value = base | 1
    time.sleep_ms(1)
    tt.ui_in.value = base
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


def _shuffled(pairs, _rand):
    """Fisher-Yates using the seeded RNG (MicroPython random has no shuffle)."""
    out = list(pairs)
    for i in range(len(out) - 1, 0, -1):
        j = _rand.randint(0, i)
        out[i], out[j] = out[j], out[i]
    return out


def _run_id(seed):
    return "%s-%08x-%08x" % (CHIP_ID, seed & 0xFFFFFFFF, time.ticks_ms() & 0xFFFFFFFF)


def _emit_metadata(run_id, seed):
    # One machine-readable JSON line, plus human-readable comments. Everything a
    # later analyzer or a community submitter needs to interpret the counts.
    meta = {
        "run_id": run_id, "script_version": SCRIPT_VERSION,
        "chip_id": CHIP_ID, "condition": CONDITION, "shuttle": SHUTTLE,
        "board_rev": BOARD_REV, "site": SITE,
        "clk_hz_requested": CLK_HZ, "clk_hz_measured": MEAS_CLK_HZ,
        "window": WINDOW, "rounds": ROUNDS, "counter_bits": 16,
        "vdd_v_measured": MEAS_VDD_V, "temp_method": TEMP_METHOD,
        "temp_c_measured": MEAS_TEMP_C, "seed": seed,
        "t_start_ms": time.ticks_ms(), "notes": NOTES,
    }
    # Build JSON manually so this stays MicroPython-safe and stable.
    items = []
    for k, v in meta.items():
        if isinstance(v, str):
            items.append('"%s": "%s"' % (k, v))
        elif v is None:
            items.append('"%s": null' % k)
        else:
            items.append('"%s": %s' % (k, v))
    print("# META " + "{" + ", ".join(items) + "}")
    print("# chip_id=%s condition=%s clk_req=%d clk_meas=%d vdd_meas=%s temp=%s"
          % (CHIP_ID, CONDITION, CLK_HZ, MEAS_CLK_HZ, MEAS_VDD_V, MEAS_TEMP_C))
    if MEAS_CLK_HZ == 0:
        print("# WARNING: reference clock not measured; absolute-frequency"
              " comparisons across boards are not valid for this run")
    if MEAS_VDD_V == 0.0:
        print("# WARNING: supply not measured; '%s' is a nominal label only"
              % CONDITION)
    return meta


def run():
    proj = getattr(tt.shuttle, PROJECT, None)
    if proj is None:
        # Fail hard. Do not fall back to the first project matching "ro_puf":
        # a shuttle can carry more than one, and picking the wrong die would
        # silently poison the dataset.
        raise SystemExit("ERROR: expected project %s not on this shuttle" % PROJECT)

    seed = time.ticks_us()
    random.seed(seed)
    run_id = _run_id(seed)

    proj.enable()
    tt.clock_project_PWM(CLK_HZ)
    tt.reset_project(True)
    time.sleep_ms(10)
    tt.reset_project(False)
    time.sleep_ms(10)

    _emit_metadata(run_id, seed)
    print("run_id,chip_id,condition,round,order,arm,idx,count,t_ms")

    pairs = [(a, i) for a in range(N_ARM) for i in range(N_IDX)]
    timeouts = 0
    saturated = 0
    zeros = 0
    try:
        for r in range(ROUNDS):
            for order, (arm, idx) in enumerate(_shuffled(pairs, random)):
                c = measure_one(arm, idx)
                if c < 0:
                    timeouts += 1
                elif c >= SAT_WARN:
                    saturated += 1
                elif c == 0:
                    zeros += 1
                print("%s,%s,%s,%d,%d,%d,%d,%d,%d"
                      % (run_id, CHIP_ID, CONDITION, r, order, arm, idx, c,
                         time.ticks_ms()))
        print("# done rounds=%d timeouts=%d near_saturation=%d zero_counts=%d"
              % (ROUNDS, timeouts, saturated, zeros))
        if saturated:
            print("# WARNING: %d samples near the 16-bit ceiling; lower CLK_HZ"
                  " or shorten the window before trusting this run" % saturated)
        if zeros:
            print("# WARNING: %d zero counts; check start/enable and the"
                  " selected oscillator" % zeros)
    finally:
        # Always leave the project safe, even if acquisition raised.
        tt.clock_project_stop()


run()
