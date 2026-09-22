#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Check the datasheet against the hardware it describes, hardware item H.

`docs/info.md` becomes the Tiny Tapeout project page. It is the only document a
person holding the chip is likely to read, and until today it told them to set
the byte-select pin and read the byte, with no mention that the pin crosses a
two-flop synchronizer first. Following it by hand returns the wrong half of the
count and nothing indicates that anything went wrong.

Prose drifts away from RTL quietly, so the fix is not only to correct the
sentence. Every number the datasheet quotes is re-derived here from the file
that owns it: the counter width and the window from the Verilog, the two clock
rates from `info.yaml` and the firmware, the frequencies from the archived
post-layout logs. Where the datasheet states a result of arithmetic, the
arithmetic is done again and compared.

Needs nothing but the repository.

    python3 sim/verify_datasheet.py
"""

import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from repo_paths import resolve  # noqa: E402

# Working-folder names. resolve finds them in the published tree too, where
# dualarm/src has been mirrored to src.
DOC = resolve("docs/info.md")
TOP = resolve("dualarm/src/tt_um_ro_puf.v")
CORE = resolve("dualarm/src/ro_puf_core.v")
YAML = resolve("info.yaml")
FW = resolve("firmware/measure_puf.py")
# The release build since 2026-09-21. These read build_current, the two-arm
# baseline, until then, which is how the datasheet went on quoting a chip that
# is not being made.
PAR = resolve("dualarm/build_armc/dualarm_par_out.txt")
PAR_FF = resolve("dualarm/build_armc/dualarm_par_ff_out.txt")
# Arm A is not the fastest arm. Arm C's rings carry two thirds of the load and
# run faster, about 4% ring for ring, so the clock floor has to come from all
# three arms, not from the arm the go/no-go decks happen to cover. It was not
# Arm A even on the baseline: Arm B's instances reach 891.4 MHz at ff there.
# Since 22 September Arm B has a run on the release build's own routes, armb3/,
# and that is the one read here. Its fastest instance lands on the same 891.4,
# because the routes sit outside the ring and the frequency is the macro's.
ARMC_TT = resolve("sim/spice/gono/rc_validation_armc.csv")
ARMC_FF = resolve("sim/spice/gono/rc3/armC_ff")
ARMA_FF_RC3 = resolve("sim/spice/gono/rc3/armA_ff")
ARMB_FF = resolve("sim/spice/gono/armb3/armb_instances_ff_out.txt")

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def text(path):
    return open(path, encoding="utf-8", errors="replace").read()


doc = text(DOC)
# The datasheet is hard-wrapped, so any phrase long enough to be worth checking
# has a newline somewhere in the middle of it. Match against a flattened copy.
flat = re.sub(r'\s+', " ", doc)
top = text(TOP)
core = text(CORE)


def par_freqs(path):
    d = {n: float(v) / 1e6 for n, v in
         re.findall(r'^(f\d+)\s*=\s*(-?[0-9.eE+-]+)', text(path), re.M)}
    return [d["f%d" % i] for i in range(16)]


def armc_ff_freqs(folder):
    """The sixteen lumped decks at ff, one log per ring. Arm C's folder or
    Arm A's from the same generator."""
    out = []
    for i in range(16):
        log = os.path.join(folder, "ro%02d_lumped_out.txt" % i)
        vals = re.findall(r'^f = ([0-9.eE+-]+)', text(log), re.M)
        out.append(float(vals[-1]) / 1e6)
    return out


def armc_tt_lumped(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    return [float(r["lumped_MHz"]) for r in rows]


def armb_freqs(path):
    return [float(v) / 1e6 for v in
            re.findall(r'^f_k\d+\s*=\s*([0-9.eE+-]+)', text(path), re.M)]


# ---------------------------------------------------------------- the hardware

# The window used to be one constant. E.2 made it four, chosen on uio[2:1],
# so the number every count below is derived from is no longer a property of
# the RTL alone: it is the RTL's table read at the firmware's selection.
wins = dict((int(i), int(v)) for i, v in
            re.findall(r"localparam \[15:0\] WIN(\d)\s*=\s*16'd(\d+);", top))
cnt_w = int(re.search(r'\.CNT_W\((\d+)\)', top).group(1))
ceiling = 2 ** cnt_w - 1

check("the RTL offers the four windows the datasheet lists",
      sorted(wins) == [0, 1, 2, 3]
      and "256, 512,\n2048 or 16384 reference-clock cycles" in doc,
      "WIN0..3 = %s" % ", ".join(str(wins[k]) for k in sorted(wins)))
check("the counter width in the RTL is the one the datasheet quotes",
      ("%d-bit count" % cnt_w) in flat and ("%d bits" % cnt_w) in flat,
      "CNT_W = %d, ceiling %d" % (cnt_w, ceiling))

# The whole point of item H. ui_in[6] is registered twice before it selects a
# byte, so a reader who changes the pin and looks at uo on the next edge sees
# the previous byte.
stages = re.findall(r'reg \[10:0\] (ui_meta|ui_sync);', top)
check("the control bundle really is two flops deep",
      set(stages) == {"ui_meta", "ui_sync"}
      and "ui_meta      <= {uio_in[3:1], ui_in[7:0]};" in top
      and "ui_sync      <= ui_meta;" in top,
      "stages found: %s" % ", ".join(stages))
check("byte select is taken from the second stage, not the pin",
      re.search(r'wire\s+byte_sel\s*=\s*ui_sync\[6\];', top) is not None)
check("the datasheet now tells the reader to wait after changing ui[6]",
      "wait three `clk` cycles after changing `ui[6]`" in flat.lower())
check("the wait the datasheet asks for covers two flops",
      3 >= len(stages), "three cycles against %d stages" % len(stages))

# There is an overflow flag now, and the paragraph that told the reader there
# was not has gone. Both halves have to move together or the datasheet is
# describing a different chip, which is what this whole file exists to catch.
outs = re.search(r'assign uio_out\s*=\s*\{([^}]*)\}', top).group(1)
check("the chip exposes done, overflow and active",
      outs.replace(" ", "") == "2'b0,active,overflow,3'b0,done",
      "uio_out = {%s}" % outs.strip())
check("the datasheet documents the flag rather than the old silence",
      "no overflow flag" not in flat and "wraps silently" not in flat
      and "latches on the wrap and holds until reset" in flat
      and "`uio[4]` latches" in flat)

# The counter is a ripple chain clocked by the ring, one toggle per ring period,
# so a count is a ring period and the formula below is the whole story.
check("the counter is clocked by the selected ring itself",
      "assign tff_clk[0] = sel_ro;" in core)
# The sampler got a bit wider when the overflow flag went in: it carries
# bit CNT_W as the wrap, so the latch takes a slice now rather than the whole
# word. Same property, one index deeper.
check("the count holds until the next start, as the datasheet claims",
      "count_latched  <= cnt_sync[CNT_W-1:0];" in core
      and "There is no hurry over step 4." in flat)


# ------------------------------------------------------------------ the clocks

declared = int(re.search(r'clock_hz:\s*(\d+)', text(YAML)).group(1))
fw_clk = int(re.search(r'^CLK_HZ\s*=\s*([\d_]+)', text(FW), re.M).group(1).replace("_", ""))
fw_window = int(re.search(r'^WINDOW = (\d+)', text(FW), re.M).group(1))
fw_win_sel = int(re.search(r'^WIN_SEL = (\d+)', text(FW), re.M).group(1))
window = fw_window

check("info.yaml declares the rate the datasheet says it declares",
      declared == 50_000_000 and "declares 50 MHz" in flat,
      "clock_hz = %d" % declared)
check("the firmware asks for the rate the datasheet recommends",
      fw_clk == 50_000_000 and "asks for 50 MHz" in flat,
      "CLK_HZ = %d" % fw_clk)
check("the firmware and the RTL agree on the window it selects",
      fw_win_sel in wins and fw_window == wins[fw_win_sel],
      "WIN_SEL %d, firmware %d, RTL %s"
      % (fw_win_sel, fw_window, wins.get(fw_win_sel)))


def counts(f_mhz, clk_hz):
    return f_mhz * 1e6 * window / clk_hz


def quoted(pattern, what, conv=int):
    """The numbers one datasheet sentence states, or a FAIL saying it is gone.

    Until 2026-09-22 a reworded sentence stopped this script with an
    AttributeError, a red job with no reason on it. Now it says which one.
    """
    m = re.search(pattern, flat)
    if m is None:
        check("the datasheet still states " + what, False,
              "no sentence matches %r" % pattern)
        return None
    return tuple(conv(g) for g in m.groups())


# ------------------------------------------------- the arithmetic in the prose

par = par_freqs(PAR)
lo, hi = min(par), max(par)
check("the Arm A range in the datasheet is the archived one",
      "%.1f to %.1f MHz" % (lo, hi) in flat, "%.1f to %.1f" % (lo, hi))

got = quoted(r'roughly (\d+) to (\d+) counts', "the Arm A count range")
if got:
    quoted_lo, quoted_hi = got
    check("the quoted count range follows from the quoted frequencies",
          abs(counts(lo, fw_clk) - quoted_lo) < 10
          and abs(counts(hi, fw_clk) - quoted_hi) < 10,
          "%.0f to %.0f against %d to %d"
          % (counts(lo, fw_clk), counts(hi, fw_clk), quoted_lo, quoted_hi))

got = quoted(r'about (\d+) counts', "the spread in counts")
if got:
    spread, = got
    check("the spread in counts follows from the same two numbers",
          abs((counts(hi, fw_clk) - counts(lo, fw_clk)) - spread) < 10,
          "%.0f against %d" % (counts(hi, fw_clk) - counts(lo, fw_clk), spread))

c_tt = armc_tt_lumped(ARMC_TT)
got = quoted(r'Arm C sits higher and much closer together, (\d+) to (\d+)',
             "the Arm C count range")
if got:
    c_lo, c_hi = got
    check("the Arm C count range follows from its lumped decks",
          len(c_tt) == 16
          and abs(counts(min(c_tt), fw_clk) - c_lo) < 10
          and abs(counts(max(c_tt), fw_clk) - c_hi) < 10,
          "%.0f to %.0f against %d to %d"
          % (counts(min(c_tt), fw_clk), counts(max(c_tt), fw_clk), c_lo, c_hi))

got = quoted(r'that is (\d+) parts per million', "one count in ppm")
if got:
    ppm, = got
    check("one count is the stated fraction of full scale",
          abs(1e6 / counts(hi, fw_clk) - ppm) < 1,
          "%.1f ppm against %d" % (1e6 / counts(hi, fw_clk), ppm))

fast_a = max(par_freqs(PAR_FF))
fast_c = max(armc_ff_freqs(ARMC_FF))
fast_b = max(armb_freqs(ARMB_FF))
fast = max(fast_a, fast_b, fast_c)
check("the fastest ring at ff over all three arms is the one quoted",
      "%.1f MHz" % fast in flat and fast == fast_c
      and "fastest ring on the chip in the simulated fast corner is an Arm C"
      in flat,
      "A %.3f, B %.3f, C %.3f MHz" % (fast_a, fast_b, fast_c))
check("and Arm A's fastest there is the archived one",
      "Arm A's fastest there is %.1f" % fast_a in flat, "%.3f MHz" % fast_a)
# 887.2 comes from the go/no-go decks and 911.1 from gen_rc_decks, which run
# about half a percent apart on the same ring, so the datasheet gives Arm A on
# Arm C's generator as well, and Arm B, and all of them have to be below it.
fast_a3 = max(armc_ff_freqs(ARMA_FF_RC3))
check("Arm A and Arm B on the other generators are quoted and slower",
      "or %.1f in the decks the Arm C figure comes from" % fast_a3 in flat
      and "Arm B's is %.1f" % fast_b in flat
      and fast_a3 < fast_c and fast_b < fast_c,
      "A %.3f on gen_rc_decks, B %.3f" % (fast_a3, fast_b))

# The Arm B spreads the datasheet quotes are the release routes' own, the
# three logs in armb3/, to the four decimals it prints. Added 2026-09-22 with
# that run, so a rerun that moves them cannot leave the page behind.
ARMB = {c: resolve("sim/spice/gono/armb3/" + n) for c, n in
        (("tt", "armb_instances_out.txt"), ("ss", "armb_instances_ss_out.txt"),
         ("ff", "armb_instances_ff_out.txt"))}
got = quoted(r"spread ([\d.]+)% peak to peak at tt, ([\d.]+)% at ss and "
             r"([\d.]+)% at ff", "the Arm B spreads on the release routes", str)
if got:
    want = []
    for c in ("tt", "ss", "ff"):
        f = armb_freqs(ARMB[c])
        want.append("%.4f" % (100.0 * (max(f) - min(f)) / (sum(f) / len(f))))
    check("the Arm B spreads it quotes are the release logs'",
          list(got) == want, "%s against %s" % ("/".join(got), "/".join(want)))

floor_mhz = fast * window / (ceiling + 1)
got = quoted(r'floor at ([\d.]+) MHz', "the clock floor", float)
if got:
    quoted_floor, = got
    check("the clock floor is where the counter would wrap",
          abs(floor_mhz - quoted_floor) < 0.05,
          "%.3f MHz against %.1f quoted" % (floor_mhz, quoted_floor))

got = quoted(r'same ring reads (\d+)', "the fast-corner reading")
if got:
    at_fast, = got
    check("the fast-corner count at the recommended clock is right",
          abs(counts(fast, fw_clk) - at_fast) < 1,
          "%.0f against %d" % (counts(fast, fw_clk), at_fast))
check("that count really is a little over half of full scale",
      0.5 < counts(fast, fw_clk) / ceiling < 0.6,
      "%.1f%% of %d" % (100 * counts(fast, fw_clk) / ceiling, ceiling))
check("the window below the one in use is a quarter of it, as the "
      "datasheet says",
      wins[1] * 4 == wins[2] and wins[0] * 8 == wins[2]
      and "The 512 window gives a quarter of each, and 256 an eighth." in flat,
      "%d, %d, %d" % (wins[0], wins[1], wins[2]))

got = quoted(r'At 512 it is (\d+) ppm', "the resolution at 512")
if got:
    ppm_512, = got
    check("the finer window's resolution follows from the same frequencies",
          abs(1e6 / (hi * 1e6 * wins[1] / fw_clk) - ppm_512) < 1,
          "%.1f ppm against %d"
          % (1e6 / (hi * 1e6 * wins[1] / fw_clk), ppm_512))


# ------------------------------------------------------------------------ report

width = max(len(n) for n, _, _ in results)
bad = sum(1 for _, ok, _ in results if not ok)
for name, ok, detail in results:
    print("  %-5s %-*s %s" % ("ok" if ok else "FAIL", width, name, detail))
print("%d checks, %d failed" % (len(results), bad))
sys.exit(1 if bad else 0)
