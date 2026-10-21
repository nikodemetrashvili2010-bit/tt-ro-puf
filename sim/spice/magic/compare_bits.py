#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Frequencies from the magic decks against the release build's SPEF decks.

Reads f from every decks_*/RING.log, the SPEF full-RC frequencies of
sim/spice/gono/rc_validation_3arm.csv and _armc.csv, and the loads, and
prints per pair: the SPEF margin, and what the magic decks say with and
without fill. A pair's bit is 1 when its even ring is the faster.

A separation is f_a - f_b as a percent of the mean of that arm's sixteen
rings in the same table, the way sim/spice/gono/predictable_bits.py and
extraction/TOLERANCES.json count it. The copy run on 20 October divided
by the pair's own mean instead, which moves a number by 0.06 at most.

Usage: python3 compare_bits.py SPEF_A.csv SPEF_C.csv DECKDIR [DECKDIR ...]
"""
import csv
import glob
import os
import re
import sys


def freqs(d):
    out = {}
    for log in glob.glob(os.path.join(d, "*.log")):
        m = re.search(r"^f = ([0-9.e+-]+)", open(log).read(), re.M)
        if m:
            out[os.path.basename(log)[:-4]] = float(m.group(1)) / 1e6
    return out


def spef(path, arm):
    return {"%s%02d" % (arm, int(r["ro"])): float(r["rc_MHz"])
            for r in csv.DictReader(open(path))}


def arm_mean(f, arm):
    v = [f["%s%02d" % (arm, i)] for i in range(16)]
    return sum(v) / len(v)


def margin(f, a, b):
    return (f[a] - f[b]) / arm_mean(f, a[0]) * 100


def main(spef_a, spef_c, *dirs):
    ref = spef(spef_a, "A")
    ref.update(spef(spef_c, "C"))
    runs = [(d, freqs(d)) for d in dirs]
    head = "pair       SPEF %   " + "  ".join("%12s" % os.path.basename(d)
                                            for d, _ in runs)
    print(head)
    for arm in "ACB":
        bits = {d: "" for d, _ in runs}
        bits["SPEF"] = ""
        for k in range(8):
            a, b = "%s%02d" % (arm, 2 * k), "%s%02d" % (arm, 2 * k + 1)
            row = "%s/%s " % (a, b)
            if a in ref:
                m = margin(ref, a, b)
                bits["SPEF"] += "1" if m > 0 else "0"
                row += " %+7.3f  " % m
            else:
                row += "    n/a   "
            for d, f in runs:
                if a in f and b in f:
                    m = margin(f, a, b)
                    bits[d] += "1" if m > 0 else "0"
                    row += "  %+10.3f" % m
                else:
                    row += "  %10s" % "-"
            print(row)
        print("  bits", " ".join("%s=%s" % (os.path.basename(k), v)
                                 for k, v in bits.items() if v))
        for d, f in runs:
            v = [f[r] for r in f if r.startswith(arm)]
            if len(v) > 1:
                print("  %s %s: %d rings, %.2f to %.2f MHz, spread %.3f %%"
                      % (os.path.basename(d), arm, len(v), min(v), max(v),
                         (max(v) - min(v)) / (sum(v) / len(v)) * 100))


if __name__ == "__main__":
    main(*sys.argv[1:])
