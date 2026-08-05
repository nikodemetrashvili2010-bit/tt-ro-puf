#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Independent re-derivation of hardware item 8, the Arm B per-instance result.

This imports nothing from analyze_instance.py or gen_instance_decks.py. It reads
the raw ngspice log, the routed netlist and the top SPEF, and computes every
number item 8 claims from scratch, including its own Pearson correlation and its
own SPEF parser. If the analyzer that produced the result has a bug, this script
is where it should show up, because the only thing the two share is the log.

The prose figures are hardcoded below. That is deliberate: editing a log without
editing the writing fails here rather than in review.

Run:
    python3 verify_instance.py
"""
import math
import os
import re
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BUILD = os.path.join(PROJ, "dualarm", "build_current")
LOG = os.path.join(HERE, "armb_instances_out.txt")
CSV = os.path.join(HERE, "instance_parasitics.csv")
NETLIST = os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.nl.v")
SPEF = os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")

NRO = 16
EDGES = 20             # the deck measures from edge 5 to edge 25
ARCHIVED_CTRL = 633.640    # tt control, every other deck in this project
ARM_A_PP = 5.84        # Arm A on this build, distributed RC, item 7
WINDOW, FREF = 1000, 25e6  # the counter window the RTL uses

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS  " + name + (("   [" + detail + "]") if detail else ""))
    else:
        fail += 1
        print("FAIL  " + name + (("   [" + detail + "]") if detail else ""))


def pearson(xs, ys):
    """Written out rather than imported, so it cannot share a bug with anything."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy)


def read_measurements(path):
    """Every '<name> = <value>' ngspice prints, keyed by name."""
    out = {}
    pat = re.compile(r"^([a-z][a-z0-9_]*)\s*=\s*([-+0-9.eE]+)")
    for line in open(path, errors="replace"):
        m = pat.match(line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def read_spef_totals(path):
    """Net name -> total capacitance in fF, straight off each *D_NET header."""
    names, totals = {}, {}
    for line in open(path, errors="replace"):
        m = re.match(r"^\*(\d+)\s+(\S+)\s*$", line)
        if m:
            names[m.group(1)] = m.group(2).replace("\\", "")
            continue
        m = re.match(r"^\*D_NET\s+\*(\d+)\s+([-+0-9.eE]+)", line)
        if m:
            totals[names[m.group(1)]] = float(m.group(2)) * 1000.0
    return totals


def read_macro_nets(path):
    """u_rob<k> -> (enable net, output net), read out of the routed netlist."""
    text = open(path, errors="replace").read()
    nets = {}
    for m in re.finditer(
            r"ro_macro_hard\s+u_rob(\d+)\s*\(\s*\.en\(\s*(\S+?)\s*\)\s*,"
            r"\s*\.out\(\s*(\S+?)\s*\)\s*\)\s*;", text):
        nets[int(m.group(1))] = (m.group(2).replace("\\", ""),
                                 m.group(3).replace("\\", ""))
    return nets


def read_csv_caps(path):
    en, out = {}, {}
    rows = [r.split(",") for r in open(path).read().strip().splitlines()]
    head = rows[0]
    for r in rows[1:]:
        d = dict(zip(head, r))
        en[int(d["instance"])] = float(d["en_cap_fF"])
        out[int(d["instance"])] = float(d["out_cap_fF"])
    return en, out


print("== the log parses, and every ring reported ==")
m = read_measurements(LOG)
tags = ["c", "r"] + ["k%02d" % k for k in range(NRO)]
for pre, want in (("f", 18), ("tp", 18), ("hi", 18), ("tq", 16),
                  ("hx", 16), ("dr", 16), ("df", 16), ("sm", 16), ("sr", 16)):
    got = len([k for k in m if k.startswith(pre + "_")])
    check("%s: %d measurements" % (pre, want), got == want, str(got))
check("no measurement came back as a failed ngspice result",
      all(math.isfinite(v) for v in m.values()))

print("\n== frequency re-derived from the period, not taken from f_ ==")
worst = 0.0
for t in tags:
    mine = EDGES / m["tp_" + t]
    worst = max(worst, abs(mine - m["f_" + t]) / m["f_" + t])
check("all 18 frequencies reproduce from %d periods" % EDGES, worst < 1e-6,
      "worst relative difference %.2e" % worst)

fc = EDGES / m["tp_c"] / 1e6
fr = EDGES / m["tp_r"] / 1e6
fk = [EDGES / m["tp_k%02d" % k] / 1e6 for k in range(NRO)]
check("the control lands on the archived tt control within one percent",
      abs(fc - ARCHIVED_CTRL) / ARCHIVED_CTRL < 0.01,
      "%.3f against %.3f, %.2f%% high" % (fc, ARCHIVED_CTRL,
                                          100 * (fc - ARCHIVED_CTRL) / ARCHIVED_CTRL))

print("\n== the spread across the sixteen ==")
pp = 100.0 * (max(fk) - min(fk)) / st.fmean(fk)
sd = 100.0 * st.stdev(fk) / st.fmean(fk)
off = 100.0 * (st.fmean(fk) - fr) / fr
check("peak to peak is 0.0025 percent", abs(pp - 0.0025) < 5e-5, "%.4f" % pp)
check("standard deviation is 0.0008 percent", abs(sd - 0.0008) < 5e-5, "%.4f" % sd)
check("the mean sits 0.0005 percent off the reference", abs(off - 0.0005) < 5e-5,
      "%+.4f" % off)
check("the spread came in under the 0.01 percent written down before the run",
      pp < 0.01, "%.4f against 0.01" % pp)
check("it is far under the 0.62 percent flag and the 5.84 percent failure line",
      pp < 0.62, "%.4f" % pp)
check("integration is 2330 times smaller than Arm A on the same build",
      round(ARM_A_PP / pp / 10) * 10 == 2330, "%.0f" % (ARM_A_PP / pp))

print("\n== the four things that have to hold before the spread means anything ==")
bad = [k for k in range(NRO)
       if abs(m["tp_k%02d" % k] - m["tq_k%02d" % k]) / m["tp_k%02d" % k] > 1e-6]
check("every output route preserved its period end to end", not bad, str(bad))
worst = max(abs((m["hx_k%02d" % k] - m["hi_k%02d" % k])
                - (m["df_k%02d" % k] - m["dr_k%02d" % k])) for k in range(NRO))
check("the width identity closes: high gained equals fall delay minus rise delay",
      worst < 1e-15, "worst %.2e s" % worst)
check("all sixteen instances ran and so did the control and the reference",
      len(fk) == NRO and math.isfinite(fc) and math.isfinite(fr))
check("no instance sits further from the reference than the sixteen do from "
      "each other, which would mean the reference is not their model",
      max(abs(f - fr) for f in fk) / fr * 100 < 2 * pp,
      "%.4f percent" % (max(abs(f - fr) for f in fk) / fr * 100))

print("\n== the parasitics the deck used are the ones in the extraction ==")
totals = read_spef_totals(SPEF)
nets = read_macro_nets(NETLIST)
check("the netlist has all sixteen u_rob instances", len(nets) == NRO, str(len(nets)))
en_csv, out_csv = read_csv_caps(CSV)
en_spef = {k: totals[nets[k][0]] for k in range(NRO)}
out_spef = {k: totals[nets[k][1]] for k in range(NRO)}
worst = max(max(abs(en_spef[k] - en_csv[k]), abs(out_spef[k] - out_csv[k]))
            for k in range(NRO))
check("both routes match the SPEF net totals for every instance", worst < 0.002,
      "worst %.4f fF" % worst)
caps = [out_spef[k] for k in range(NRO)]
check("output routes span 2.89 to 29.46 fF, mean 14.46",
      abs(min(caps) - 2.89) < 0.01 and abs(max(caps) - 29.46) < 0.01
      and abs(st.fmean(caps) - 14.46) < 0.01)
ecaps = [en_spef[k] for k in range(NRO)]
check("enable routes span 1.00 to 12.81 fF",
      abs(min(ecaps) - 1.00) < 0.01 and abs(max(ecaps) - 12.81) < 0.01)

print("\n== what the scatter correlates with, which is how noise is told from Miller ==")
delay = [m["dr_k%02d" % k] * 1e12 for k in range(NRO)]
slew_in = [m["sm_k%02d" % k] * 1e12 for k in range(NRO)]
slew_out = [m["sr_k%02d" % k] * 1e12 for k in range(NRO)]
r_f = pearson(caps, fk)
r_d = pearson(caps, delay)
r_s = pearson(caps, slew_out)
check("frequency against route capacitance is -0.160", abs(r_f + 0.160) < 5e-4,
      "%+.3f" % r_f)
check("route delay against route capacitance is +0.910", abs(r_d - 0.910) < 5e-4,
      "%+.3f" % r_d)
check("receiver edge against route capacitance is +0.999", abs(r_s - 0.999) < 5e-4,
      "%+.3f" % r_s)
t = abs(r_f) * math.sqrt(NRO - 2) / math.sqrt(1 - r_f * r_f)
check("that frequency correlation is not significant at 14 degrees of freedom, "
      "so the scatter is solver noise and not a measured Miller path",
      t < 2.1448, "t = %.3f against a 2.145 critical value" % t)
check("the sign is at least the one a real Miller path would need, so nothing "
      "is wired backwards", r_f < 0, "%+.3f" % r_f)
check("both correlations that should be real are real", r_d > 0.5 and r_s > 0.99)

print("\n== the edge arriving at the selector, which is item 3's open debt ==")
alls = slew_in + slew_out
check("the receiver edge spans 62.6 to 318.2 ps",
      abs(min(alls) - 62.6) < 0.05 and abs(max(alls) - 318.2) < 0.05,
      "%.1f to %.1f" % (min(alls), max(alls)))
check("route delay spans 0.1 to 4.5 ps",
      abs(min(delay) - 0.1) < 0.05 and abs(max(delay) - 4.5) < 0.05,
      "%.1f to %.1f" % (min(delay), max(delay)))
check("the edge spread is a factor of five, which is the number the arms have "
      "to be compared across", 4.5 < max(alls) / min(alls) < 5.5,
      "%.2fx" % (max(alls) / min(alls)))

print("\n== can the chip even see this spread ==")
periods = st.fmean(fk) * 1e6 * WINDOW / FREF
one_count = 100.0 / periods
check("the 40 us window holds about 22826 Arm B periods",
      abs(periods - 22826) < 5, "%.0f" % periods)
check("the whole per-instance spread is smaller than one count of the counter",
      pp < one_count,
      "%.4f percent against %.4f percent per count, %.2f counts"
      % (pp, one_count, pp / one_count))

print()
print("== SUMMARY ==  %d passed, %d failed" % (ok, fail))
print("Arm B integration spread %.4f percent peak to peak, %.4f standard deviation."
      % (pp, sd))
print("Arm A on the same build spreads %.2f percent, a factor of %.0f."
      % (ARM_A_PP, ARM_A_PP / pp))
print("The spread is %.2f of one counter count, so it is below what the chip can "
      "resolve." % (pp / one_count))
raise SystemExit(1 if fail else 0)
