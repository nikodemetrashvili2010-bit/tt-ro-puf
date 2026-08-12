#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""If the layout term can be subtracted, do the response bits come back?

Section 6 showed the layout term is predictable: a capacitance-and-resistance
model built from the public SPEF removes 89.5% of the per-ring spread out of
sample. Section 7 showed the response is nearly fixed: 0.46 bits of 8 across
dies, six bits carrying essentially none.

Those two results sit next to each other and nobody has made them talk. This
script does that. It is the obvious objection to the whole paper, and it comes
from the RO-PUF literature rather than from nowhere: systematic variation gets
compensated, that is what compensation is for, so compensate the layout term and
see whether the bits recover.

The arithmetic is the same as predictable_bits.py, run on different inputs.
There the pair separation was the raw difference between two rings. Here it is
the difference between two *residuals* after each ring has had its predicted
layout term taken away:

    r[i] = f_centred[i] - model(C[i], R[i])
    d    = r[a] - r[b]

and the bit is sign(d + mismatch), same as before, same 0.062% per-ring scale.

Two ways to score the model, and the difference matters:

  leave-one-out   the model that corrects ring i never saw ring i. This is what
                  Section 6 reports and it is the honest number for a corrector
                  that has to generalise.
  full 16-ring    the model saw everything. Smaller residual, so more entropy
                  survives. This is the best case for the corrector, not the
                  realistic one.

Both are printed. Neither is the headline on its own.

One thing to hold on to while reading the output, because it decides what the
result means. The correction is computed from the SPEF. The SPEF is public. So
whatever the defender subtracts, the attacker subtracts too, and the attacker's
knowledge of the leftover is exact rather than approximate. Compensation moves
the deterministic term around; it does not move it out of the public files.

Run: python3 compensated_bits.py
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

import compensation as cp  # noqa: E402  (SPEF features and the solver, reused)

PAIRS = [(i, i + 1) for i in range(0, 16, 2)]
NRO = 16
SIGMA_RING = 0.062                   # percent, sim/spice/mc
SIGMA_LO, SIGMA_HI = 0.051, 0.080    # its sampling interval

# Section 6's checked-in residuals. If either drifts, the inputs moved and every
# number below is about a different design.
WANT_BASE = 1.739
WANT_LOO = 0.183


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def hbin(p):
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def rms(v):
    return math.sqrt(sum(x * x for x in v) / len(v))


def loo_residuals(cols, y):
    """Residual per ring, each from a fit that excluded that ring."""
    out = []
    for h in range(len(y)):
        b = cp.ols(cols, y, [i for i in range(len(y)) if i != h])
        out.append(y[h] - (b[0] + sum(bi * c[h] for bi, c in zip(b[1:], cols))))
    return out


def full_residuals(cols, y):
    b = cp.ols(cols, y)
    return [y[i] - (b[0] + sum(bi * c[i] for bi, c in zip(b[1:], cols)))
            for i in range(len(y))]


def score(resid, sigma):
    """Per pair: separation, separation in sigma, entropy, attacker accuracy."""
    sp = sigma * math.sqrt(2.0)
    rows = []
    for a, b in PAIRS:
        d = resid[a] - resid[b]
        p = phi(d / sp)
        rows.append((d, abs(d) / sp, hbin(p), max(p, 1 - p)))
    return rows


def totals(rows):
    return (sum(r[2] for r in rows),
            sum(r[3] for r in rows),
            sum(1 for r in rows if r[2] < 0.01))


def main():
    feats = cp.spef_features(cp.CUR_SPEF, NRO)
    C = [f[0] for f in feats]
    R = [f[1] for f in feats]
    _, _, f_rc = cp.read_rc()
    y = cp.centred(f_rc)

    base = st.pstdev(y)
    loo = loo_residuals([C, R], y)
    full = full_residuals([C, R], y)

    # Guard. These two figures are quoted in Section 6 and in the README, and
    # everything below is a re-scoring of them. If they have moved, stop.
    if abs(base - WANT_BASE) > 0.001 or abs(rms(loo) - WANT_LOO) > 0.001:
        raise SystemExit("inputs moved: uncorrected %.4f%% (want %.3f), "
                         "leave-one-out %.4f%% (want %.3f)"
                         % (base, WANT_BASE, rms(loo), WANT_LOO))

    print("Compensating the layout term, then re-reading the response bits.")
    print("Section 6's correction applied per ring, Section 7's arithmetic")
    print("applied to what is left. Mismatch scale %.3f%% per ring throughout.\n"
          % SIGMA_RING)

    un = score(y, SIGMA_RING)
    lo = score(loo, SIGMA_RING)

    print("  pair    uncompensated   compensated    sigma    entropy   attacker")
    for (a, b), u, c in zip(PAIRS, un, lo):
        print("  %2d/%-2d    %+8.3f%%      %+8.3f%%   %6.2f   %7.3f    %5.1f%%%s"
              % (a, b, u[0], c[0], c[1], c[2], c[3] * 100,
                 "   sign flips" if (u[0] > 0) != (c[0] > 0) else ""))

    flips = sum(1 for u, c in zip(un, lo) if (u[0] > 0) != (c[0] > 0))
    e_un, a_un, f_un = totals(un)
    e_lo, a_lo, f_lo = totals(lo)
    e_fu, a_fu, f_fu = totals(score(full, SIGMA_RING))

    print("\n  %d of the 8 signs flip. The compensated response is not the same"
          % flips)
    print("  response with more noise in it, it is a different response.\n")

    print("                                 residual   entropy   guessed   fixed")
    print("  uncompensated                   %6.3f%%   %4.2f/8   %5.2f/8   %d of 8"
          % (base, e_un, a_un, f_un))
    print("  compensated, leave-one-out      %6.3f%%   %4.2f/8   %5.2f/8   %d of 8"
          % (rms(loo), e_lo, a_lo, f_lo))
    print("  compensated, full 16-ring fit   %6.3f%%   %4.2f/8   %5.2f/8   %d of 8"
          % (rms(full), e_fu, a_fu, f_fu))
    print("  a coin flip                          --   8.00/8    4.00/8   0 of 8")

    print("\nSo compensation works, and it is not enough. Entropy goes from")
    print("%.2f bits to %.2f of 8 and the bits that were effectively fixed drop"
          % (e_un, e_lo))
    print("from %d to %d. That is a real recovery and it should be reported as"
          % (f_un, f_lo))
    print("one. But %.2f of 8 is %.0f%% of a response, and the attacker who applies"
          % (e_lo, e_lo / 8 * 100))
    print("the same public correction still calls %.2f of 8, against %.2f for"
          % (a_lo, 4.0))
    print("guessing. Compensation is computed from the SPEF, so it is not a")
    print("secret and it is not a defence. It changes which bits are decided in")
    print("advance without changing who gets to know them.")

    # ---------------------------------------------------------------- fragility
    print("\n== how much to trust that number ==\n")

    print("The mismatch scale is an assumption, and the compensated result leans")
    print("on it far harder than the uncompensated one did. Uncompensated, the")
    print("layout term was 28x the mismatch scale and doubling the scale changed")
    print("little. Compensated, the residual is under 3x it:\n")
    print("  sigma per ring   uncompensated      compensated")
    print("                   entropy  guessed   entropy  guessed")
    for s in (SIGMA_LO, SIGMA_RING, SIGMA_HI, 2 * SIGMA_RING):
        eu, au, _ = totals(score(y, s))
        ec, ac, _ = totals(score(loo, s))
        print("     %.3f%%        %4.2f/8   %4.2f/8    %4.2f/8   %4.2f/8%s"
              % (s, eu, au, ec, ac,
                 "   <- sim/spice/mc" if s == SIGMA_RING else ""))
    print("\n  Across the sampling interval alone the compensated entropy runs")
    e_int = [totals(score(loo, s))[0] for s in (SIGMA_LO, SIGMA_HI)]
    a_int = [totals(score(loo, s))[1] for s in (SIGMA_HI, SIGMA_LO)]
    print("  %.2f to %.2f bits and the attacker %.2f to %.2f. Quote the interval."
          % (e_int[0], e_int[1], a_int[0], a_int[1]))

    print("\nSecond fragility, and it is the worse one. Eight pairs is a tiny")
    print("sample and the entropy total is not a stable statistic. Two correctors")
    print("whose per-ring residuals are within a few percent of each other do not")
    print("give answers within a few percent of each other:\n")
    print("  corrector                  residual   entropy   guessed")
    for label, cols in (("ring capacitance", [C]),
                        ("capacitance and resistance", [C, R])):
        r = loo_residuals(cols, y)
        e, a, _ = totals(score(r, SIGMA_RING))
        print("  %-26s  %6.3f%%   %4.2f/8   %5.2f/8" % (label, rms(r), e, a))
    print("\n  A 4% difference in residual, a 2x difference in entropy. The pair")
    print("  differences are what the entropy sees, and the ring-level residual")
    print("  does not determine them. Read the entropy totals as this block's")
    print("  numbers and not as a measurement of anything general.")

    print("\nAnd the limit that outranks both: none of this is fabricated. The")
    print("residuals are two reductions of one extraction disagreeing with each")
    print("other by a fifth of a percent, and the mismatch they are weighed")
    print("against was never measured on a die. Silicon decides it.")


if __name__ == "__main__":
    main()
