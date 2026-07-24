#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Outlier sensitivity and cross-build prediction for the dual-arm result.

Two questions, both answered from checked-in raw files.

1. How much of the 10.5% peak-to-peak spread depends on the single
   heavy-routing oscillator (RO15, 24.35 fF)? Recompute everything with it
   left out.

2. Does the capacitance-frequency fit trained on the earlier 32-oscillator
   build predict the current build per oscillator, not just on average?
   Train the linear fit on the first build, apply it to the current caps,
   report per-oscillator error.

Run: python3 sensitivity.py
"""

import csv
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CUR_PAR = os.path.join(PROJ, "dualarm", "build_current", "dualarm_par_out.txt")
CUR_POS = os.path.join(PROJ, "dualarm", "build_current", "dualarm_positions.csv")
OLD_PAR = os.path.join(HERE, "par2.txt")
OLD_CSV = os.path.join(HERE, "gono_results.csv")


def freqs(path):
    text = open(path).read()
    d = {int(m.group(1)): float(m.group(2)) / 1e6
         for m in re.finditer(r"^f(\d+)\s*=\s*([0-9.eE+-]+)", text, re.M)}
    return [d[i] for i in sorted(d)]


def ring_caps(path):
    return [float(r["ring_cap_fF"]) for r in csv.DictReader(open(path))]


def mean(v):
    return sum(v) / len(v)


def psd(v):
    m = mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))


def pearson(x, y):
    mx, my = mean(x), mean(y)
    dx = [a - mx for a in x]
    dy = [b - my for b in y]
    return sum(a * b for a, b in zip(dx, dy)) / math.sqrt(
        sum(a * a for a in dx) * sum(b * b for b in dy))


def spearman(x, y):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    return pearson(rank(x), rank(y))


def stats_line(tag, f, c):
    m = mean(f)
    pp = max(f) - min(f)
    print("%s  mean %.2f MHz  p-p %.2f MHz (%.2f%%)  SD %.2f%%  "
          "r %.4f  rank r %.3f"
          % (tag, m, pp, 100 * pp / m, 100 * psd(f) / m,
             pearson(c, f), spearman(c, f)))


def main():
    f = freqs(CUR_PAR)
    c = ring_caps(CUR_POS)
    assert len(f) == len(c) == 16

    print("-- outlier sensitivity, current dual-arm build --")
    stats_line("all 16:      ", f, c)
    hot = max(range(16), key=lambda i: c[i])
    print("heaviest routing load: RO%d, %.2f fF (next highest %.2f fF)"
          % (hot, c[hot], sorted(c)[-2]))
    f15 = [x for i, x in enumerate(f) if i != hot]
    c15 = [x for i, x in enumerate(c) if i != hot]
    stats_line("without RO%d:" % hot, f15, c15)

    print()
    print("-- cross-build per-oscillator prediction --")
    f1 = freqs(OLD_PAR)
    c1 = [float(r["ring_cap_fF"]) for r in csv.DictReader(open(OLD_CSV))]
    assert len(f1) == len(c1) == 32
    mc, mf = mean(c1), mean(f1)
    slope = (sum(a * b for a, b in zip(c1, f1)) - 32 * mc * mf) / (
        sum(a * a for a in c1) - 32 * mc * mc)
    icpt = mf - slope * mc
    print("fit on first build: f = %.2f %+.3f * cap" % (icpt, slope))
    pred = [icpt + slope * x for x in c]
    err = [p - x for p, x in zip(pred, f)]
    mae = mean([abs(e) for e in err])
    rmse = math.sqrt(mean([e * e for e in err]))
    print("applied to current 16 caps: MAE %.2f MHz (%.2f%% of mean), "
          "RMSE %.2f MHz, rank corr %.3f"
          % (mae, 100 * mae / mean(f), rmse, spearman(pred, f)))
    print("largest error: RO%d, %+.2f MHz (%+.2f%%)"
          % (max(range(16), key=lambda i: abs(err[i])),
             err[hot], 100 * err[hot] / f[hot]))


if __name__ == "__main__":
    main()
