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
PAR = resolve("dualarm/build_current/dualarm_par_out.txt")
PAR_FF = resolve("dualarm/build_current/dualarm_par_ff_out.txt")

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


# ---------------------------------------------------------------- the hardware

window = int(re.search(r'localparam \[15:0\] WINDOW = 16\'d(\d+)', top).group(1))
cnt_w = int(re.search(r'\.CNT_W\((\d+)\)', top).group(1))
ceiling = 2 ** cnt_w - 1

check("the window in the RTL is the one the datasheet quotes",
      re.search(r'\b%d[- ]cycle measurement window' % window, flat)
      or ("%d reference-clock cycles" % window) in flat,
      "WINDOW = %d" % window)
check("the counter width in the RTL is the one the datasheet quotes",
      ("%d-bit count" % cnt_w) in flat and ("%d bits" % cnt_w) in flat,
      "CNT_W = %d, ceiling %d" % (cnt_w, ceiling))

# The whole point of item H. ui_in[6] is registered twice before it selects a
# byte, so a reader who changes the pin and looks at uo on the next edge sees
# the previous byte.
stages = re.findall(r'reg \[6:0\] (ui_meta|ui_sync);', top)
check("the control bundle really is two flops deep",
      set(stages) == {"ui_meta", "ui_sync"}
      and "ui_meta      <= ui_in[6:0];" in top
      and "ui_sync      <= ui_meta;" in top,
      "stages found: %s" % ", ".join(stages))
check("byte select is taken from the second stage, not the pin",
      re.search(r'wire\s+byte_sel\s*=\s*ui_sync\[6\];', top) is not None)
check("the datasheet now tells the reader to wait after changing ui[6]",
      "wait three `clk` cycles after changing `ui[6]`" in flat.lower())
check("the wait the datasheet asks for covers two flops",
      3 >= len(stages), "three cycles against %d stages" % len(stages))

# There is no overflow flag to find, which is why the datasheet has to say so.
outs = re.search(r'assign uio_out\s*=\s*\{([^}]*)\}', top).group(1)
check("done is the only status bit the chip exposes",
      outs.replace(" ", "") == "7'b0,done",
      "uio_out = {%s}" % outs.strip())
check("the datasheet says the counter wraps silently",
      "no overflow flag" in flat and "wraps silently" in flat)

# The counter is a ripple chain clocked by the ring, one toggle per ring period,
# so a count is a ring period and the formula below is the whole story.
check("the counter is clocked by the selected ring itself",
      "assign tff_clk[0] = sel_ro;" in core)
check("the count holds until the next start, as the datasheet claims",
      "count_latched  <= cnt_sync;" in core
      and "There is no hurry over step 4." in flat)


# ------------------------------------------------------------------ the clocks

declared = int(re.search(r'clock_hz:\s*(\d+)', text(YAML)).group(1))
fw_clk = int(re.search(r'^CLK_HZ\s*=\s*([\d_]+)', text(FW), re.M).group(1).replace("_", ""))
fw_window = int(re.search(r'^WINDOW = (\d+)', text(FW), re.M).group(1))

check("info.yaml declares the rate the datasheet says it declares",
      declared == 50_000_000 and "declares 50 MHz" in flat,
      "clock_hz = %d" % declared)
check("the firmware asks for the rate the datasheet recommends",
      fw_clk == 25_000_000 and "asks for 25 MHz" in flat,
      "CLK_HZ = %d" % fw_clk)
check("the firmware and the RTL agree on the window",
      fw_window == window, "firmware %d, RTL %d" % (fw_window, window))


def counts(f_mhz, clk_hz):
    return f_mhz * 1e6 * window / clk_hz


# ------------------------------------------------- the arithmetic in the prose

par = par_freqs(PAR)
lo, hi = min(par), max(par)
check("the Arm A range in the datasheet is the archived one",
      "%.1f to %.1f MHz" % (lo, hi) in flat, "%.1f to %.1f" % (lo, hi))

quoted_lo, quoted_hi = (int(x) for x in
                        re.search(r'roughly (\d+) to (\d+) counts', flat).groups())
check("the quoted count range follows from the quoted frequencies",
      abs(counts(lo, fw_clk) - quoted_lo) < 10
      and abs(counts(hi, fw_clk) - quoted_hi) < 10,
      "%.0f to %.0f against %d to %d"
      % (counts(lo, fw_clk), counts(hi, fw_clk), quoted_lo, quoted_hi))

spread = int(re.search(r'about (\d+) counts', flat).group(1))
check("the spread in counts follows from the same two numbers",
      abs((counts(hi, fw_clk) - counts(lo, fw_clk)) - spread) < 10,
      "%.0f against %d" % (counts(hi, fw_clk) - counts(lo, fw_clk), spread))

ppm = int(re.search(r'that is (\d+) parts per million', flat).group(1))
check("one count is the stated fraction of full scale",
      abs(1e6 / counts(hi, fw_clk) - ppm) < 1,
      "%.1f ppm against %d" % (1e6 / counts(hi, fw_clk), ppm))

fast = max(par_freqs(PAR_FF))
check("the fast-corner ring in the datasheet is the archived one",
      "%.1f MHz" % fast in flat, "%.3f MHz" % fast)

floor_mhz = fast * window / (ceiling + 1)
quoted_floor = float(re.search(r'floor at ([\d.]+) MHz', flat).group(1))
check("the clock floor is where the counter would wrap",
      abs(floor_mhz - quoted_floor) < 0.05,
      "%.3f MHz against %.1f quoted" % (floor_mhz, quoted_floor))

at_fast = int(re.search(r'same ring reads (\d+)', flat).group(1))
check("the fast-corner count at the recommended clock is right",
      abs(counts(fast, fw_clk) - at_fast) < 1,
      "%.0f against %d" % (counts(fast, fw_clk), at_fast))
check("that count really is a little over half of full scale",
      0.5 < counts(fast, fw_clk) / ceiling < 0.6,
      "%.1f%% of %d" % (100 * counts(fast, fw_clk) / ceiling, ceiling))
check("halving the window doubles the headroom, as the datasheet says",
      abs(counts(fast, declared) / ceiling - counts(fast, fw_clk) / ceiling / 2)
      < 1e-9, "%.1f%% at %d Hz" % (100 * counts(fast, declared) / ceiling, declared))


# ------------------------------------------------------------------------ report

width = max(len(n) for n, _, _ in results)
bad = sum(1 for _, ok, _ in results if not ok)
for name, ok, detail in results:
    print("  %-5s %-*s %s" % ("ok" if ok else "FAIL", width, name, detail))
print("%d checks, %d failed" % (len(results), bad))
sys.exit(1 if bad else 0)
