#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Does the attacker have to fit the model on the victim?

Section 6 fits a capacitance-and-resistance model to the shipped build and
scores it leave-one-ring-out: the model that corrects ring i never saw ring i.
That is the right way to score a corrector, and it is the wrong way to describe
an attacker, because it still assumes the attacker got fifteen of the victim's
sixteen frequencies from somewhere. Where would he get them? Simulating them
needs the PDK, a SPICE deck per ring and the patience to run it. If the model
has to be calibrated on the victim, the attack costs a full re-simulation of the
target. If it does not, the attack costs a SPEF parser and one number.

So the fit is moved off the victim entirely. Three data sets, all checked in:

  A  first build, 32 rings, lumped caps    a different RTL revision, placed and
                                           routed independently
  B  shipped build, 16 rings, lumped caps  the victim layout, cheap model
  C  shipped build, 16 rings, full RC      the victim layout, the model
                                           Sections 6 and 7 actually report

C is the target. A model trained on A and applied to C never sees the victim's
frequencies and never sees the victim's parasitic model either, since A's decks
carry one lumped capacitance per net and C's carry the extracted network. Both
directions get run, because a result that only works one way is usually an
accident of sample size.

Then the bits, which is what the attack is about. Section 7 computes the chance
a reader calls a bit correctly as Phi(d / sigma_pair), where d is the pair's
routing separation. That formula quietly assumes the reader's estimate of d is
d itself. Under transfer it is not, so the general form is used:

    accuracy = Phi( sign(d_hat) * d_true / sigma_pair )

with d_hat the transferred model's estimate and d_true the victim's actual
separation. It collapses to Section 7's expression when the two agree in sign,
which turns out to be the whole story here.

Two controls, because the transfer numbers are only interesting against
something. Shuffling the victim's capacitances between rings keeps every value
and destroys the assignment; a model that still works after that is measuring
nothing. And the fit is repeated on the first two, three, four rings of build A
to see how much of somebody else's build the attacker actually needs.

What this cannot show. Both builds carry the same 32-cell ring in the same PDK,
so this is transfer across placement, routing and an RTL revision, not across
designs. A foreign design with a different ring length has a different slope and
the attacker would have to fit his own, which he can do by building that RTL
himself. That is Phase A's premise and it is not tested here.

Run: python3 build_transfer.py
     python3 build_transfer.py --selftest    (planted faults, no PDK needed)
"""

import argparse
import csv
import math
import os
import random
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import compensation as cp   # noqa: E402  (SPEF features, solver, scoring)

CUR = os.path.join(PROJ, "dualarm", "build_current")
FIRST_SPEF = os.path.join(HERE, "first_build",
                          "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
CUR_SPEF = os.path.join(CUR, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
FIRST_CSV = os.path.join(HERE, "gono_results.csv")
RC_CSV = os.path.join(HERE, "rc_validation.csv")
CUR_PAR = os.path.join(CUR, "dualarm_par_out.txt")

PAIRS = [(i, i + 1) for i in range(0, 16, 2)]
SIGMA_RING = 0.062
SIGMA_PAIR = SIGMA_RING * math.sqrt(2.0)
SEED = 20260814

# Section 6 and 7.1, and the two slopes Section 5 quotes. Guards, not results.
WANT_C_SD = 1.739
WANT_C_LOO = 0.183
WANT_SLOPE_A = -4.93
WANT_SLOPE_B = -4.94
SLOPE_TOL = 0.02


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def demean(v):
    m = st.mean(v)
    return [x - m for x in v]


def predict(beta, cols, n):
    """Model output, recentred.

    The intercept is the victim's mean frequency and the attacker does not have
    it. He does not need it either: a PUF reads differences between rings, so
    only the shape matters and the level is removed on both sides.
    """
    return demean([beta[0] + sum(b * col[i] for b, col in zip(beta[1:], cols))
                   for i in range(n)])


def resid_sd(pred, truth):
    return st.pstdev([t - p for t, p in zip(truth, pred)])


def pair_deltas(centred):
    return [centred[a] - centred[b] for a, b in PAIRS]


def guessed(d_hat, d_true):
    return sum(phi((1.0 if x > 0 else -1.0) * t / SIGMA_PAIR)
               for x, t in zip(d_hat, d_true))


def signs_agree(d_hat, d_true):
    return sum(1 for x, t in zip(d_hat, d_true) if (x > 0) == (t > 0))


# ---------------------------------------------------------------- inputs

def load():
    rows_a = list(csv.DictReader(open(FIRST_CSV)))
    fa = cp.spef_features(FIRST_SPEF, 32)
    fc = cp.spef_features(CUR_SPEF, 16)
    cur_rows = list(csv.DictReader(open(os.path.join(CUR,
                                                     "dualarm_positions.csv"))))
    # Same guard compensation.py uses. If the recomputed capacitance disagrees
    # with the checked-in tables then the loop-net set is wrong and every number
    # below is about different nets.
    for lbl, mine, want in (("A", [v[0] for v in fa],
                             [float(r["ring_cap_fF"]) for r in rows_a]),
                            ("C", [v[0] for v in fc],
                             [float(r["ring_cap_fF"]) for r in cur_rows])):
        bad = max(abs(m - w) for m, w in zip(mine, want))
        if bad > 0.011:
            raise SystemExit("build %s: recomputed ring capacitance is off by "
                             "%.4f fF, refusing to continue" % (lbl, bad))
    af = [float(r["freq_MHz"]) for r in rows_a]
    rc = {int(r["ro"]): float(r["rc_MHz"]) for r in csv.DictReader(open(RC_CSV))}
    cf = [rc[i] for i in range(16)]
    lump = {int(m.group(1)): float(m.group(2)) / 1e6 for m in
            re.finditer(r"^f(\d+)\s*=\s*([0-9.eE+-]+)", open(CUR_PAR).read(),
                        re.M)}
    bf = [lump[i] for i in range(16)]
    return dict(acap=[v[0] for v in fa], ares=[v[1] for v in fa], af=af,
                ccap=[v[0] for v in fc], cres=[v[1] for v in fc],
                bf=bf, cf=cf)


# ---------------------------------------------------------------- the report

def report(d, out=print, seed=SEED):
    fail = []
    acap, ares, af = d["acap"], d["ares"], d["af"]
    ccap, cres = d["ccap"], d["cres"]
    ca, cb, cc = cp.centred(af), cp.centred(d["bf"]), cp.centred(d["cf"])

    out("Slopes. The left column is what Section 5 quotes; the right is the same")
    out("fit on centred frequency, which is the form the transfer uses.\n")
    out("  %-34s %12s %12s" % ("", "MHz/fF", "%/fF"))
    slopes = {}
    for lbl, cap, f, cen in (("A  first build, 32, lumped", acap, af, ca),
                             ("B  shipped build, 16, lumped", ccap, d["bf"], cb),
                             ("C  shipped build, 16, full RC", ccap, d["cf"], cc)):
        mhz = cp.ols([cap], f)[1]
        pct = cp.ols([cap], cen)[1]
        slopes[lbl[0]] = mhz
        out("  %-34s %12.4f %12.4f" % (lbl, mhz, pct))
    for who, want in (("A", WANT_SLOPE_A), ("B", WANT_SLOPE_B)):
        if abs(slopes[who] - want) > SLOPE_TOL:
            fail.append("build %s reads %.4f MHz/fF where Section 5 quotes %.2f"
                        % (who, slopes[who], want))
    out("\n  A and B agree to %.2f%%, which Section 5.2 already reports. The full"
        % (abs(slopes["A"] - slopes["B"]) / abs(slopes["A"]) * 100))
    out("  RC build is %.1f%% steeper, and that gap is the whole difficulty: a"
        % (abs(slopes["C"] - slopes["A"]) / abs(slopes["A"]) * 100))
    out("  model trained on a lumped deck has never seen a distributed network.")

    bA = cp.ols([acap], ca)
    bAr = cp.ols([acap, ares], ca)
    bB = cp.ols([ccap], cb)
    bC = cp.ols([ccap], cc)
    bCr = cp.ols([ccap, cres], cc)

    out("\nTransfer onto C, the full RC frequencies of the shipped build.")
    out("Residual spread, how much of C's spread it removes, and the residual as")
    out("a multiple of the %.3f%% mismatch scale.\n" % SIGMA_RING)
    base_c = st.pstdev(cc)
    if abs(base_c - WANT_C_SD) > 0.002:
        fail.append("C's uncorrected spread reads %.4f%% where Section 6 reports "
                    "%.3f%%" % (base_c, WANT_C_SD))
    out("  %-54s %8s %9s %8s" % ("", "residual", "removed", "vs sigma"))
    out("  %-54s %7.4f%% %8s %7.1fx" % ("uncorrected", base_c, "--",
                                        base_c / SIGMA_RING))

    def line(label, r):
        out("  %-54s %7.4f%% %+8.1f%% %7.2fx"
            % (label, r, (1.0 - r / base_c) * 100.0, r / SIGMA_RING))
        return r

    line("model trained on A, cap only, never refitted",
         resid_sd(predict(bA, [ccap], 16), cc))
    line("model trained on A, cap and res, never refitted",
         resid_sd(predict(bAr, [ccap, cres], 16), cc))
    line("model trained on B, cap only, the victim's cheap model",
         resid_sd(predict(bB, [ccap], 16), cc))
    own = line("C's own leave-one-ring-out, Section 6",
               cp.loo_rms([ccap, cres], cc))
    if abs(own - WANT_C_LOO) > 0.002:
        fail.append("C's own leave-one-out residual reads %.4f%% where Section 6 "
                    "reports %.3f%%" % (own, WANT_C_LOO))

    out("\nTransfer the other way, onto A's 32 rings.\n")
    base_a = st.pstdev(ca)
    out("  %-54s %7.4f%% %8s %7.1fx" % ("uncorrected", base_a, "--",
                                        base_a / SIGMA_RING))
    for label, r in (("model trained on C, cap only, never refitted",
                      resid_sd(predict(bC, [acap], 32), ca)),
                     ("model trained on C, cap and res, never refitted",
                      resid_sd(predict(bCr, [acap, ares], 32), ca)),
                     ("A's own leave-one-ring-out, cap only",
                      cp.loo_rms([acap], ca))):
        out("  %-54s %7.4f%% %+8.1f%% %7.2fx"
            % (label, r, (1.0 - r / base_a) * 100.0, r / SIGMA_RING))

    out("\nResistance does not travel. Its coefficient is %+.6f on A and %+.6f on"
        % (bAr[2], bCr[2]))
    out("C, opposite signs, so the extra it buys inside one build is that build's")
    out("own leftovers. Capacitance alone transfers better than capacitance and")
    out("resistance in both directions, which is the sign of a coefficient that")
    out("means something physical next to one that does not.")

    rnd = random.Random(seed)
    shuffled = ccap[:]
    rnd.shuffle(shuffled)
    r = resid_sd(predict(bA, [shuffled], 16), cc)
    out("\nControl. Keep every capacitance and shuffle which ring owns it, seed")
    out("%d: the A model then leaves %.4f%%, %+.1f%% against doing nothing. The"
        % (seed, r, (1.0 - r / base_c) * 100.0))
    out("assignment is the information, not the distribution.")

    out("\nThe eight bits of the shipped build. d_true is what Section 7 reads")
    out("off the full RC run; the rest are what a reader computes without ever")
    out("simulating this layout.\n")
    d_true = pair_deltas(cc)
    cands = (("exact extraction and simulation, Section 7", d_true),
             ("model trained on build A, cap only",
              pair_deltas(predict(bA, [ccap], 16))),
             ("model trained on build A, cap and res",
              pair_deltas(predict(bAr, [ccap, cres], 16))),
             ("lumped model of the victim layout", pair_deltas(cb)),
             ("control, shuffled capacitances",
              pair_deltas(predict(bA, [shuffled], 16))))
    out("  pair  " + "".join("%11s" % n for n in
                             ("d_true", "A cap", "A cap+res", "lumped", "shuffled")))
    for i, (a, b) in enumerate(PAIRS):
        out("  %2d/%-2d " % (a, b)
            + "".join("%+10.4f%%" % v[1][i] for v in cands))
    out("")
    for label, dh in cands:
        out("  %-42s signs %d of 8   bits guessed %.2f of 8"
            % (label, signs_agree(dh, d_true), guessed(dh, d_true)))

    out("\nHow much of somebody else's build the attacker needs. The model is fit")
    out("on the first n rings of A in the order they appear in the CSV, then")
    out("applied to C.\n")
    out("  %6s %10s %12s %8s %10s" % ("rings", "slope", "residual", "signs",
                                      "bits"))
    for n in (2, 3, 4, 8, 16, 32):
        b = cp.ols([acap[:n]], ca[:n])
        p = predict(b, [ccap], 16)
        dh = pair_deltas(p)
        out("  %6d %10.4f %11.4f%% %6d/8 %10.2f"
            % (n, b[1], resid_sd(p, cc), signs_agree(dh, d_true),
               guessed(dh, d_true)))

    out("\nVerdict.")
    out("The victim's extraction is load bearing and the victim's simulation is")
    out("not. Shuffling which ring owns which capacitance is worse than applying")
    out("no correction at all, so the attacker does need the target's own SPEF.")
    out("What he does not need is a frequency from it: a slope taken from another")
    out("build, or from two rings of another build, calls all eight bits the same")
    out("way the full simulation does. On this pair of builds the transfer costs")
    removed_own = (1.0 - own / base_c) * 100.0
    removed_tr = (1.0 - resid_sd(predict(bA, [ccap], 16), cc) / base_c) * 100.0
    out("%.1f points of the %.1f%% Section 6 reports, and no bits at all."
        % (removed_own - removed_tr, removed_own))
    out("")
    out("Read that as a statement about attacker cost, not about accuracy. The")
    out("transferred model is slightly worse at reproducing the frequencies and")
    out("exactly as good at deciding the bits, because a bit only needs the sign")
    out("of a difference and the sign is the part that survives.")
    return fail


# ------------------------------------------------------------------- self test

def synth(n_a=32, n_c=16, slope=-5.0, drift=0.0, noise=0.0, seed=1):
    """A pair of builds with a known slope, optionally drifted or noisy."""
    rnd = random.Random(seed)
    acap = [10.0 + 6.0 * rnd.random() for _ in range(n_a)]
    ccap = [10.0 + 6.0 * rnd.random() for _ in range(n_c)]
    ares = [20.0 + 40.0 * rnd.random() for _ in range(n_a)]
    cres = [20.0 + 40.0 * rnd.random() for _ in range(n_c)]
    af = [600.0 + slope * c + rnd.gauss(0, noise) for c in acap]
    cf = [600.0 + (slope + drift) * c + rnd.gauss(0, noise) for c in ccap]
    return dict(acap=acap, ares=ares, af=af, ccap=ccap, cres=cres,
                bf=cf[:], cf=cf)


def selftest():
    ok = True

    def bits(d, label):
        lines = []
        try:
            report(d, out=lines.append)
        except SystemExit:
            pass
        txt = "\n".join(lines)
        row = [ln for ln in txt.splitlines()
               if "model trained on build A, cap only" in ln][0]
        return int(row.split("signs")[1].split("of")[0]), float(row.split()[-3])

    # A build pair with one shared slope: everything has to transfer.
    s, _ = bits(synth(), "clean")
    print("  %s a shared slope transfers all eight signs (%d of 8)"
          % ("ok   " if s == 8 else "WRONG", s))
    ok &= s == 8

    # The same, with the target's slope moved 20%: still the same signs, because
    # a scale change cannot reorder a monotone prediction.
    s, _ = bits(synth(drift=-1.0), "drift")
    print("  %s a 20%% slope error changes no sign (%d of 8)"
          % ("ok   " if s == 8 else "WRONG", s))
    ok &= s == 8

    # A target whose frequencies owe nothing to capacitance: the transfer has to
    # stop working and land near a coin.
    d = synth()
    rnd = random.Random(7)
    d["cf"] = [600.0 + rnd.gauss(0, 8.0) for _ in range(16)]
    d["bf"] = d["cf"][:]
    s, g = bits(d, "unrelated")
    print("  %s a target unrelated to capacitance falls to chance "
          "(%d of 8, %.2f bits guessed)"
          % ("ok   " if s <= 6 and g < 6.5 else "WRONG", s, g))
    ok &= s <= 6 and g < 6.5

    # Recentring has to make a constant capacitance offset invisible. If it
    # does not, the attacker would need the victim's absolute level as well.
    d = synth()
    d["acap"] = [c + 5.0 for c in d["acap"]]
    s2, _ = bits(d, "offset")
    hit = s2 == 8
    print("  %s a constant capacitance offset changes no sign, as recentring "
          "requires (%d of 8)" % ("ok   " if hit else "WRONG", s2))
    ok &= hit

    print("selftest: %s" % ("all four planted cases behaved" if ok
                            else "SOMETHING IS WRONG"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true",
                    help="run the planted cases and exit; needs no SPEF, no PDK "
                         "and no ngspice")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    fail = report(load())
    if fail:
        print()
        for m in fail:
            print("FAIL: " + m)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
