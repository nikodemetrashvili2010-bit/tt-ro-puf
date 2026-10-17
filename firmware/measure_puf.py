# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# Acquisition firmware for the three-arm RO-PUF on the TinyTapeout demo board.
# Runs on the board (MicroPython, TT SDK v3). Prints a metadata header plus one
# CSV row per sample to the USB console:
#
#   mpremote run measure_puf.py > chip01_room_1v8.csv
#
# Fill in the CONFIG block below for each run. The chip id, the measured supply
# voltage, and the measured temperature are not guessed by the script: a label
# like "room_1v8" records the setting you dialled in, not what the part saw,
# so record what you actually measured.
#
# Chip protocol (from tt_um_ro_puf.v):
#   ui[0] start (hold high for at least three clk cycles),
#   ui[1] arm bit 0, ui[7] arm bit 1 (0 = A auto-placed, 1 = B matched
#   macro, 2 = C hand-placed),
#   ui[5:2] oscillator index, ui[6] byte select (0 low, 1 high),
#   uio[2:1] window select, uio[3] read version bytes instead of the count,
#   uo[7:0] selected count byte, uio[0] done (high = count valid),
#   uio[4] counter overflowed, sticky until reset, uio[5] measurement active.
#
# Window choice: count = f_osc * WINDOW / f_clk, and WINDOW is now one of
# 256, 512, 2048 and 16384 rather than a fixed 1000. The counter is 16 bit,
# ceiling 65535. 2048 at 50 MHz is 41 us and reads about 23400 for the
# fastest nominal ring, which is where this script sits. 16384 exists to
# make the counter wrap on purpose, so it is a test window and not a data one.
#
# Overflow is no longer something to be careful about. uio[4] latches when
# the counter wraps and stays latched until reset, so a wrapped count is
# reported rather than guessed at from how close to the ceiling it looks.
# The old near-ceiling warning is kept as a second opinion, because a flag
# that is never read is a flag nobody trusts.
#
# Every selection is started twice and both counts are kept. The clock
# edge that takes a start switches the selector and releases the counter's
# reset at the same moment, and on some changes of selection the selector's
# mux pulses while it settles, so the first run after a change can read one
# count high (docs/phaseG_hazard.md). A second start on the same selection
# changes nothing in the selector, so its count is the clean one. `count` is
# the second run and is what every analysis uses; `count_first` is the first
# run, kept because first minus second, averaged over repeats, is that pulse
# measured on the real die. One pair also differs by the usual one-count
# boundary jitter, so read it as an average, not sample by sample.
#
# Before anything is measured the script reads the two version bytes through
# uio[3] and stops unless they are 2 and 0x1A. A wrong project, a board that
# is not driving the pins, or a die whose project does not answer all show
# up there, before any count is written.
#
# It also writes every ui_in pin and reads it back before measuring. The SDK
# leaves an input pin that reads high when it takes control as an input, its
# rule for a DIP switch left on, and only logs it, so a write to that pin then
# goes nowhere. On ui[0], start, that is loud and nothing runs. On one of the
# six pins that pick the ring it is silent, and half the selections would
# measure the other half's rings with every count looking right. Reading the
# pins back makes that a stop with the stuck bits named, not a dataset that is
# quietly half wrong.
#
# Four more things, found reading Tiny Tapeout's sources on 4 October and
# writing the FPGA scripts on the 10th:
#
#   - it probes the board before DemoBoard.get(). mpremote soft resets the
#     board before it runs a file and the SDK's main.py only runs from the
#     friendly REPL, so on a run started that way nothing has told the SDK
#     which board and carrier it is on. Its README says to probe first. A
#     board whose main.py already made a DemoBoard is not probed again
#   - a stop prints a "# ERROR:" line. MicroPython on the board prints
#     nothing for a SystemExit, it only soft resets, so the old stops ended
#     the run in silence. The analyzer refuses a file with an ERROR line
#   - it stops if enable() says no. The SDK refuses a project whose danger
#     level is not safe and returns False; the run used to carry on to the
#     version check and stop there with a message about version bytes
#   - it writes the clock the SDK says it made into the header, next to the
#     one it asked for, and drives uio 6 and 7 low. The chip reads neither,
#     and a pad input nobody drives can sit anywhere
#
# Ordering: samples are taken in randomized rounds. Each round measures all 48
# (arm, idx) selections once in a fresh random order, and the run repeats that
# for ROUNDS rounds. This keeps arm and oscillator index from being correlated
# with acquisition time (a plain arm-by-arm sweep would confound slow thermal
# or supply drift with arm identity). The random seed and the per-sample
# timestamp are recorded so the order is reproducible and any drift is visible.

import json
import time
import random

from ttboard.boot.demoboard_detect import DemoboardDetect
from ttboard.demoboard import DemoBoard

# ---- CONFIG: set these per run ------------------------------------------
CHIP_ID    = "chip01"        # stable anonymous id for this physical die
CONDITION  = "room_1v8"      # nominal condition label, the dialled setting
SHUTTLE    = "ttsky26d"      # shuttle the die came from
BOARD_REV  = "unknown"       # demo board / devkit revision
SITE       = "unknown"       # operator or measurement site id
CLK_HZ     = 50_000_000      # requested project clock
MEAS_CLK_HZ = 0              # measured project clock in Hz, 0 if not measured
MEAS_VDD_V  = 0.0            # measured core supply in volts, 0.0 if not measured
TEMP_METHOD = "none"         # e.g. "ambient", "thermocouple_on_package"
MEAS_TEMP_C = None           # measured temperature in C, None if not measured
NOTES       = ""             # free text
ROUNDS      = 60             # randomized rounds; raise for a real dataset
TIMEOUT_MS  = 200
# -------------------------------------------------------------------------

SCRIPT_VERSION = "measure_puf/6"
WIN_SEL = 2                  # 0=256, 1=512, 2=2048, 3=16384 clk cycles
WINDOW = 2048                # must be the length WIN_SEL selects in the RTL
SAT_WARN = 65000             # warn when a count gets this close to the ceiling
N_ARM = 3
N_IDX = 16
PROTOCOL_VERSION = 2         # uio[3] high, ui[6] low: must read this
BUILD_ID = 0x1A              # uio[3] high, ui[6] high: and this
PROJECT = "tt_um_nikodemetrashvili20_ro_puf"


class Stop(Exception):
    """A reason to end the run. Printed as "# ERROR:" at the bottom."""


# None when the board's main.py had already made a DemoBoard, so nothing was
# probed here; otherwise whether the SDK's probe was sure of the board.
PROBED = None
if getattr(DemoBoard, "_DemoBoardSingleton_Instance", None) is None:
    PROBED = bool(DemoboardDetect.probe())
tt = DemoBoard.get()


def _ui(start, arm, idx, byte_sel):
    return ((start & 1) | ((arm & 1) << 1) | ((idx & 0xF) << 2)
            | ((byte_sel & 1) << 6) | (((arm >> 1) & 1) << 7))


def _uio(rd_ver=False):
    """What the board drives into the chip. Only bits 3:1 are read."""
    return ((WIN_SEL & 3) << 1) | ((1 if rd_ver else 0) << 3)


def _bits(mask):
    return " ".join(str(b) for b in range(8) if mask >> b & 1) or "none"


def _set_ui(v):
    """Write ui_in and read the pins straight back.

    The SDK leaves any input pin that reads high when it takes control as an
    input, which is how it treats a DIP switch left on, and only logs it. A
    write to that pin then does nothing. On ui[0] that stalls a run and is
    obvious; on one of the six selection pins it is silent, and half the
    selections quietly measure the other half's rings with every count still
    looking right. Reading back turns a stuck pin into a stop, naming the bits
    that would not take, instead of a dataset that is half wrong.
    """
    tt.ui_in.value = v
    got = int(tt.ui_in.value)
    if got != v:
        raise Stop("wrote ui_in 0x%02x, read back 0x%02x; bit(s) %s will"
                   " not drive. A DIP switch is on, or something else holds"
                   " the pin. Turn the DIP switches off and run again"
                   % (v, got, _bits(v ^ got)))


def check_ui_in():
    """Drive every ui_in pin both ways with the project held in reset, before
    any count. A pin that cannot be driven stops the run here, not in the
    middle of a dataset. 0x55 and 0xAA between them put each of the eight pins
    high once and low once, so a pin stuck either way shows."""
    for v in (0x00, 0xFF, 0x55, 0xAA, 0x00):
        _set_ui(v)
        time.sleep_ms(1)


def read_version():
    """The protocol and build bytes, read through uio[3].

    Both go through the same two-flop synchronizer as every other control
    pin, so each byte select is held a millisecond before uo is read.
    """
    tt.uio_in.value = _uio(rd_ver=True)
    _set_ui(_ui(0, 0, 0, 0))
    time.sleep_ms(1)
    proto = int(tt.uo_out.value)
    _set_ui(_ui(0, 0, 0, 1))
    time.sleep_ms(1)
    build = int(tt.uo_out.value)
    _set_ui(_ui(0, 0, 0, 0))
    tt.uio_in.value = _uio()
    time.sleep_ms(1)
    return proto, build


def _run(arm, idx):
    """One start and its readout. The count, or -1 on timeout."""
    base = _ui(0, arm, idx, 0)
    _set_ui(base)
    time.sleep_ms(1)
    _set_ui(base | 1)
    time.sleep_ms(1)
    _set_ui(base)
    t0 = time.ticks_ms()
    while not tt.uio_out[0]:
        if time.ticks_diff(time.ticks_ms(), t0) > TIMEOUT_MS:
            return -1
    lo = int(tt.uo_out.value)
    _set_ui(_ui(0, arm, idx, 1))
    time.sleep_ms(1)
    hi = int(tt.uo_out.value)
    _set_ui(base)
    return (hi << 8) | lo


def measure_one(arm, idx):
    """Two runs of one selection, see the header.

    Returns (count, count_first, overflow): count is the second run's,
    count_first the first's, -1 for a run that timed out, and overflow the
    sticky flag after both.
    """
    tt.uio_in.value = _uio()
    first = _run(arm, idx)
    second = _run(arm, idx)
    return second, first, int(tt.uio_out[4])


def _shuffled(pairs, _rand):
    """Fisher-Yates using the seeded RNG (MicroPython random has no shuffle)."""
    out = list(pairs)
    for i in range(len(out) - 1, 0, -1):
        j = _rand.randint(0, i)
        out[i], out[j] = out[j], out[i]
    return out


def _run_id(seed):
    return "%s-%08x-%08x" % (CHIP_ID, seed & 0xFFFFFFFF, time.ticks_ms() & 0xFFFFFFFF)


def _emit_metadata(run_id, seed, clk_sdk):
    # One machine-readable JSON line, plus human-readable comments. Everything a
    # later analyzer or a community submitter needs to interpret the counts.
    meta = {
        "run_id": run_id, "script_version": SCRIPT_VERSION,
        "chip_id": CHIP_ID, "condition": CONDITION, "shuttle": SHUTTLE,
        "board_rev": BOARD_REV, "site": SITE,
        "board_detected": DemoboardDetect.PCB_str(), "board_probed": PROBED,
        "sdk_version": getattr(tt, "version", "unknown"),
        "clk_hz_requested": CLK_HZ, "clk_hz_sdk": clk_sdk,
        "clk_hz_measured": MEAS_CLK_HZ,
        "window": WINDOW, "win_sel": WIN_SEL, "arms": N_ARM,
        "rounds": ROUNDS, "counter_bits": 16,
        "vdd_v_measured": MEAS_VDD_V, "temp_method": TEMP_METHOD,
        "temp_c_measured": MEAS_TEMP_C, "seed": seed,
        "t_start_ms": time.ticks_ms(), "notes": NOTES,
        "protocol_version": PROTOCOL_VERSION, "build_id": BUILD_ID,
        "starts_per_sample": 2, "count_is": "second start",
    }
    # This used to build the JSON by hand, on the grounds that it kept the
    # script MicroPython-safe. It escaped nothing. A double quote or a backslash
    # in CHIP_ID, CONDITION, SITE or NOTES emitted invalid JSON, and the reader
    # answered a parse failure by returning None, so the whole header vanished
    # without a word and the counts loaded anyway. NOTES is free text typed by
    # whoever ran the board, which is the one field most likely to contain a
    # quote, and a volunteer whose clock and supply silently disappeared is
    # exactly the failure this dataset cannot afford.
    #
    # MicroPython ships json, so use it. If it is ever missing the import at the
    # top fails loudly on the board, which is the right way round: a script that
    # will not start beats a run that looks fine and carries no metadata.
    print("# META " + json.dumps(meta))
    print("# chip_id=%s condition=%s clk_req=%d clk_meas=%d vdd_meas=%s temp=%s"
          % (CHIP_ID, CONDITION, CLK_HZ, MEAS_CLK_HZ, MEAS_VDD_V, MEAS_TEMP_C))
    if PROBED is False:
        # The SDK's own boot says "(best guess)" in the same case. On an
        # RP2040 board with SDK 2.0 that is every TT06 or later board.
        print("# WARNING: the SDK's probe was not conclusive; it is assuming"
              " a %s board" % DemoboardDetect.PCB_str())
    if clk_sdk is not None and clk_sdk != CLK_HZ:
        print("# WARNING: asked for a %d Hz clock and the SDK says it made %s"
              " Hz; every count scales with it" % (CLK_HZ, clk_sdk))
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
        raise Stop("expected project %s not on this shuttle" % PROJECT)

    seed = time.ticks_us()
    random.seed(seed)
    run_id = _run_id(seed)

    if proj.enable() is False:
        # The SDK will not enable a project whose danger level is not safe
        # unless it is forced, and its log above says which level it read.
        # Nothing here forces it.
        raise Stop("the SDK would not enable %s, see its log above" % PROJECT)
    # The RP2040 side of the bidirectional pins comes up as inputs, so the
    # window bits written to uio_in below would never reach the chip and
    # uio[3:1] would float. Make bits 1, 2 and 3 outputs from the board
    # first, and 6 and 7, which the chip does not read, so that they sit low
    # instead of wherever an undriven line drifts. Bits 0, 4 and 5 stay inputs
    # because the chip drives those.
    tt.uio_oe_pico.value = 0b1100_1110
    tt.clock_project_PWM(CLK_HZ)
    # What the SDK says it set up, which is what every count is a count of.
    # SDK 2.0 and 3.x have it; None means this SDK does not say.
    clk_sdk = getattr(tt, "auto_clocking_freq", None)
    tt.reset_project(True)
    time.sleep_ms(10)

    try:
        # Check the pins while the project is held in reset, so a stuck one
        # stops the run before a single ring turns.
        check_ui_in()
        tt.reset_project(False)
        time.sleep_ms(10)
        proto, build = read_version()
        if (proto, build) != (PROTOCOL_VERSION, BUILD_ID):
            # A wrong project, a board that is not reaching the pins, or a
            # die whose project does not answer. Nothing measured after
            # this could be trusted, so nothing is measured.
            raise Stop("version bytes read %d and 0x%02x, expected %d and"
                       " 0x%02x" % (proto, build, PROTOCOL_VERSION, BUILD_ID))
    except BaseException:
        tt.reset_project(True)
        tt.clock_project_stop()
        raise

    _emit_metadata(run_id, seed, clk_sdk)
    print("run_id,chip_id,condition,round,order,arm,idx,count,overflow,"
          "count_first,t_ms")

    pairs = [(a, i) for a in range(N_ARM) for i in range(N_IDX)]
    timeouts = 0
    saturated = 0
    wrapped = 0
    zeros = 0
    # First minus second start, over samples where both ran and nothing
    # wrapped: -1, 0, +1 and anything else.
    diffs = {-1: 0, 0: 0, 1: 0, "other": 0}
    try:
        for r in range(ROUNDS):
            for order, (arm, idx) in enumerate(_shuffled(pairs, random)):
                c, c1, ovf = measure_one(arm, idx)
                if c >= 0 and c1 >= 0 and not ovf:
                    d = c1 - c
                    diffs[d if d in (-1, 0, 1) else "other"] += 1
                if c < 0:
                    timeouts += 1
                elif ovf:
                    wrapped += 1
                elif c >= SAT_WARN:
                    saturated += 1
                elif c == 0:
                    zeros += 1
                print("%s,%s,%s,%d,%d,%d,%d,%d,%d,%d,%d"
                      % (run_id, CHIP_ID, CONDITION, r, order, arm, idx, c,
                         ovf, c1, time.ticks_ms()))
        print("# done rounds=%d timeouts=%d wrapped=%d near_saturation=%d"
              " zero_counts=%d"
              % (ROUNDS, timeouts, wrapped, saturated, zeros))
        print("# first minus second start: -1 in %d, 0 in %d, +1 in %d,"
              " other in %d" % (diffs[-1], diffs[0], diffs[1], diffs["other"]))
        if wrapped:
            print("# WARNING: %d samples set the overflow flag; drop WIN_SEL"
                  " to 1 and rerun. A wrapped count is not a slow ring."
                  % wrapped)
        if saturated:
            print("# WARNING: %d samples near the 16-bit ceiling without the"
                  " overflow flag; shorten the window before the next die"
                  % saturated)
        if zeros:
            print("# WARNING: %d zero counts; check start/enable and the"
                  " selected oscillator" % zeros)
    finally:
        # Always leave the project safe, even if acquisition raised. Reset
        # first: a ring whose window is open when the clock stops stays on,
        # and docs/info.md says to abort with rst_n or ena before stopping
        # the clock. The earlier version stopped the clock only.
        tt.reset_project(True)
        tt.clock_project_stop()


try:
    run()
except Stop as e:
    # A stop after the clock started has already put the project in reset and
    # stopped the clock on its way out of run(). This only makes the reason
    # visible on the console.
    print("# ERROR: %s" % e)
