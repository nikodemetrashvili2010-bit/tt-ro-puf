#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Can I predict the layout term and subtract it?

Deterministic ought to mean predictable. If I can work out each ring's share of
the dispersion ahead of time, the layout term stops being a wall and turns into
a correction that costs nothing on the die.

The RO-PUF papers already correct systematic variation, and they do it with
position: die gradients are spatially correlated, so you fit a surface in x and
y and take it away. That is the baseline to beat. My alternative reads the
design database instead. Every ring has a total capacitance and a total series
resistance sitting in the SPEF long before anything is fabricated.

Three data sets, all already in the repo:

  A  first build, 32 rings, one lumped capacitor per net
  B  shipped build, 16 rings, the same treatment
  C  shipped build, 16 rings, the full RC network from the item 7 run

C decides it. In A and B the simulator gets a single capacitance per net and
nothing else varies, so a fit against capacitance there recovers what the deck
was told and proves very little. I print them anyway, because applying the build
A fit to build B without refitting is a real test of whether the relationship
travels between builds.

Anything scored against C is scored leave-one-out. Sixteen points and a
quadratic surface with six free parameters would otherwise flatter itself badly.

Frequencies are centred, (f - mean) / mean, since a PUF reads the pattern across
oscillators rather than the absolute value. The floor everything is compared
against is the 0.062% per-ring mismatch from sim/spice/mc, an estimate rather
than a measurement.

Run: python3 compensation.py
"""

import csv
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import gen_rc_decks as rcd  # noqa: E402  (SPEF parser, reused rather than copied)

FIRST_CSV = os.path.join(HERE, "gono_results.csv")
FIRST_SPEF = os.path.join(HERE, "first_build",
                          "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
RC_CSV = os.path.join(HERE, "rc_validation.csv")
CUR = os.path.join(PROJ, "dualarm", "build_current")
CUR_POS = os.path.join(CUR, "dualarm_positions.csv")
CUR_PAR = os.path.join(CUR, "dualarm_par_out.txt")
CUR_SPEF = os.path.join(CUR, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")

NLOOP = 31          # n[0..30] are the loop nets. `out` hangs outside the loop.
MISMATCH_PCT = 0.062


# ---------------------------------------------------------------- inputs

def spef_features(path, nro):
    """Per ring: loop capacitance in fF, loop resistance in ohms, and the
    Elmore-like sum of per-net R*C. Uses the loop-net set gen_dualarm_decks.py
    sums, so the capacitance column reproduces the checked-in CSVs."""
    names, nets = rcd.parse_spef(path)
    num = {v: k for k, v in names.items()}
    out = []
    for ro in range(nro):
        loop = [num[f"u_puf.u_core.g_ro_bank[{ro}].u_ro.n[{k}]"]
                for k in range(NLOOP)]
        cap = sum(nets[n]["total"] for n in loop) * 1000.0
        res = sum(sum(o for _, _, o in nets[n]["res"]) for n in loop)
        elm = sum(sum(o for _, _, o in nets[n]["res"]) * nets[n]["total"]
                  for n in loop) * 1000.0
        out.append((cap, res, elm))
    return out


def read_first():
    rows = list(csv.DictReader(open(FIRST_CSV)))
    return (rows, [float(r["x_um"]) for r in rows],
            [float(r["y_um"]) for r in rows],
            [float(r["freq_MHz"]) for r in rows])


def read_shipped_lumped():
    rows = list(csv.DictReader(open(CUR_POS)))
    fmap = {int(m.group(1)): float(m.group(2)) / 1e6 for m in
            re.finditer(r"^f(\d+)\s*=\s*([0-9.eE+-]+)", open(CUR_PAR).read(), re.M)}
    return ([float(r["x_um"]) for r in rows], [float(r["y_um"]) for r in rows],
            [fmap[int(r["ro"])] for r in rows])


def read_rc():
    rows = list(csv.DictReader(open(RC_CSV)))
    pos = {int(r["ro"]): r for r in csv.DictReader(open(CUR_POS))}
    return ([float(pos[int(r["ro"])]["x_um"]) for r in rows],
            [float(pos[int(r["ro"])]["y_um"]) for r in rows],
            [float(r["rc_MHz"]) for r in rows])


# ---------------------------------------------------------------- fitting

def ols(cols, yv, idx=None):
    idx = range(len(yv)) if idx is None else idx
    A = [[1.0] + [c[i] for c in cols] for i in idx]
    Y = [yv[i] for i in idx]
    k = len(A[0])
    M = [[sum(A[i][a] * A[i][b] for i in range(len(A))) for b in range(k)]
         + [sum(A[i][a] * Y[i] for i in range(len(A)))] for a in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12:
            raise ValueError("singular design matrix")
        for r in range(k):
            if r != c:
                f = M[r][c] / M[c][c]
                for q in range(c, k + 1):
                    M[r][q] -= f * M[c][q]
    return [M[i][k] / M[i][i] for i in range(k)]


def centred(f):
    m = st.mean(f)
    return [(v - m) / m * 100.0 for v in f]


def quad(x, y):
    return [x, y, [v * v for v in x], [v * v for v in y],
            [a * b for a, b in zip(x, y)]]


def loo_rms(cols, c):
    """Leave-one-out residual RMS, in percent of mean frequency."""
    res = []
    for h in range(len(c)):
        b = ols(cols, c, [i for i in range(len(c)) if i != h])
        res.append(c[h] - (b[0] + sum(bi * col[h] for bi, col in zip(b[1:], cols))))
    return math.sqrt(sum(r * r for r in res) / len(res))


def line(label, sd, base):
    print("    %-34s %6.3f%%   %+6.1f%%      %5.1fx"
          % (label, sd, (1 - sd / base) * 100, sd / MISMATCH_PCT))


# ---------------------------------------------------------------- report

def main():
    rows_a, ax, ay, af = read_first()
    fa = spef_features(FIRST_SPEF, 32)
    fb = spef_features(CUR_SPEF, 16)

    # If this column does not match the CSVs then I am summing the wrong nets
    # and everything below is measuring something else.
    for lbl, mine, want in (
            ("A", [f[0] for f in fa], [float(r["ring_cap_fF"]) for r in rows_a]),
            ("B", [f[0] for f in fb],
             [float(r["ring_cap_fF"]) for r in csv.DictReader(open(CUR_POS))])):
        bad = max(abs(m - w) for m, w in zip(mine, want))
        if bad > 0.011:
            raise SystemExit(f"build {lbl}: recomputed ring capacitance is off "
                             f"by {bad:.4f} fF, refusing to continue")
    print("Ring capacitance recomputed from both SPEFs matches the checked-in")
    print("CSVs to under 0.01 fF, so the loop-net selection is the same one.")

    model_a = ols([[f[0] for f in fa]], af)
    print("\nModel trained once on build A, 32 oscillators:")
    print("  f = %.2f %+.3f * ring_cap_fF   (MHz, fF)" % (model_a[0], model_a[1]))

    print("\nColumns: residual spread, how much of the spread it removed, and")
    print("the residual as a multiple of the %.3f%% mismatch floor.\n" % MISMATCH_PCT)

    # --- lumped data, cross-build only -------------------------------------
    for lbl, x, y, f, caps in (
            ("A  first build, 32 rings, lumped caps", ax, ay, af, [v[0] for v in fa]),
            ("B  shipped build, 16 rings, lumped caps", *read_shipped_lumped(),
             [v[0] for v in fb])):
        c = centred(f)
        base = st.pstdev(c)
        print("%s\n    uncorrected                        %6.3f%%                 %5.1fx"
              % (lbl, base, base / MISMATCH_PCT))
        b = ols(quad(x, y), c)
        line("position, quadratic surface",
             st.pstdev([v - (b[0] + sum(bi * col[i] for bi, col in zip(b[1:], quad(x, y))))
                        for i, v in enumerate(c)]), base)
        if lbl.startswith("B"):
            pc = centred([model_a[0] + model_a[1] * v for v in caps])
            line("build A model, no refit",
                 st.pstdev([a - p for a, p in zip(c, pc)]), base)
        print()

    print("  Take those two lightly. The lumped deck gets one capacitance per net")
    print("  and nothing else moves, so a capacitance fit is recovering its own")
    print("  input. Build B does show one real thing: the first build's fit, a")
    print("  different RTL on a different placement, lands on this pattern without")
    print("  being refitted.\n")

    # --- the real test -----------------------------------------------------
    cx, cy, cf = read_rc()
    c = centred(cf)
    base = st.pstdev(c)
    C = [v[0] for v in fb]
    R = [v[1] for v in fb]
    E = [v[2] for v in fb]
    print("C  shipped build, 16 rings, full RC network from the SPEF")
    print("    uncorrected                        %6.3f%%                 %5.1fx"
          % (base, base / MISMATCH_PCT))
    print("    every line below is leave-one-out cross validated:")
    for cols, label in ((quad(cx, cy), "position, quadratic surface"),
                        ([cx, cy], "position, linear"),
                        ([R], "ring resistance"),
                        ([E], "Elmore-like sum(R*C)"),
                        ([C], "ring capacitance"),
                        ([C, R], "capacitance and resistance")):
        line(label, loo_rms(cols, c), base)

    best = loo_rms([C, R], c)
    print("\nPosition gets nowhere. Cross validated it is worse than leaving the")
    print("data alone, which is what a per-instance routing fingerprint should do:")
    print("no smooth surface underneath, so the fit only adds noise. The literature")
    print("correction for systematic process variation does not reach this.")
    print("\nThe design database does carry it. Capacitance and resistance together")
    print("take %.0f%% of the spread out of sample, from %.0fx the mismatch floor down"
          % ((1 - best / base) * 100, base / MISMATCH_PCT))
    print("to %.0fx. Two numbers cannot stand in for 33 resistors and 65 capacitors"
          % (best / MISMATCH_PCT))
    print("per ring, so the rest needs the network simulated instead of summarised,")
    print("and gen_rc_decks.py already runs that.")
    print("\nWhether any of it survives fabrication is not something this can answer.")
    print("Two parasitic models of one layout bound the prediction from below and say")
    print("nothing about a real die. The per-ring numbers are frozen before the chips")
    print("arrive, so at least it will be a test and not a fit.")


if __name__ == "__main__":
    main()
