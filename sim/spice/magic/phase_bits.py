#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Fill phase by phase: does any pair change sign as the fill grid moves?

The SPICE runs are at phase 0. For the other phases each ring's frequency
is moved from its phase-0 value by the slope that phase 0 itself shows,
frequency change against fill load across the 48 rings, times that ring's
difference in fill load from phase 0. Separations are percent of the
arm's mean, as in compare_bits.py.

Usage: python3 phase_bits.py LOADS_BASE.csv DECKS_BASE DECKS_FILL0
                             LOADS_FILL0.csv [LOADS_FILLn.csv ...]
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


def loads(path, col):
    return {r["ring"]: float(r[col]) for r in csv.DictReader(open(path))}


def main(base_csv, d_base, d_fill0, fill0_csv, *more):
    base = loads(base_csv, "grounded_fF")
    fb, f0 = freqs(d_base), freqs(d_fill0)
    dc0 = {k: v - base[k] for k, v in loads(fill0_csv, "floating_fF").items()}
    # slope, percent of frequency per fF of fill load, through the origin
    xs = [dc0[k] for k in fb]
    ys = [(f0[k] - fb[k]) / fb[k] * 100 for k in fb]
    slope = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)
    res = [y - slope * x for x, y in zip(xs, ys)]
    print("fill slope %.4f %% per fF, residual sd %.4f %%, rings %d" % (
        slope, (sum(r * r for r in res) / len(res)) ** 0.5, len(xs)))
    phases = [("phase 0", f0)]
    for path in more:
        dc = {k: v - base[k] for k, v in loads(path, "floating_fF").items()}
        f = {k: f0[k] * (1 + slope / 100 * (dc[k] - dc0[k])) for k in f0}
        phases.append((os.path.basename(path)[6:-4], f))
    print("pair     " + "".join("%11s" % n for n, _ in phases))
    for arm in "ACB":
        for k in range(8):
            a, b = "%s%02d" % (arm, 2 * k), "%s%02d" % (arm, 2 * k + 1)
            row = "%s/%s" % (a, b)
            signs = set()
            for _, f in phases:
                mean = sum(f["%s%02d" % (arm, i)] for i in range(16)) / 16
                m = (f[a] - f[b]) / mean * 100
                signs.add(m > 0)
                row += " %+10.3f" % m
            print(row + ("" if len(signs) == 1 else "   <- sign moves"))


if __name__ == "__main__":
    main(*sys.argv[1:])
