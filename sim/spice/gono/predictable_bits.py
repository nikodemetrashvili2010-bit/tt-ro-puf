#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""How many response bits does the design database already decide?

The dispersion numbers elsewhere are frequencies. What a PUF actually hands out
is bits, so this turns the same data into the quantity that matters. The design
compares neighbouring oscillators, 0 against 1, 2 against 3, and so on, which is
eight bits from Arm A's sixteen rings.

For each pair there are two contributions to the frequency difference. One comes
from routing and is fixed by the mask, so it is the same on every die and it can
be read out of the SPEF before anything is fabricated. The other comes from
random device mismatch and is different on every die. The bit is the sign of the
sum. If the routing part is much larger than the mismatch part, the sign is
already settled and every chip returns the same bit.

That is the whole calculation. Write the per-die difference as

    D = delta_routing + noise,  noise ~ N(0, sigma_pair)

with sigma_pair = sigma_ring * sqrt(2) for two independent rings. Then across
dies the bit is one with probability Phi(delta / sigma_pair), and its entropy is
the binary entropy of that. Zero routing offset gives half a bit each way and a
full bit of entropy. A large routing offset gives none.

Two things this does not do. It assumes the extracted delta is what a real die
will show, which is exactly the assumption the silicon measurement exists to
test. And eight bits is a small response, so treat the totals as a
characterisation of this block rather than a general statement about RO-PUFs.

Arm B needs no calculation. Sixteen instances of one macro have the same
internal routing by construction, so delta_routing is zero and every bit is
decided by mismatch alone.

Run: python3 predictable_bits.py
"""

import csv
import math
import os
import re
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PAR = os.path.join(PROJ, "dualarm", "build_current", "dualarm_par_out.txt")
RC = os.path.join(HERE, "rc_validation.csv")

PAIRS = [(i, i + 1) for i in range(0, 16, 2)]
SIGMA_RING = 0.062          # percent, sim/spice/mc
SIGMA_LO, SIGMA_HI = 0.051, 0.080   # its sampling interval


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def hbin(p):
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def lumped():
    d = {int(m.group(1)): float(m.group(2)) / 1e6 for m in
         re.finditer(r"^f(\d+)\s*=\s*([0-9.eE+-]+)", open(PAR).read(), re.M)}
    return [d[i] for i in sorted(d)]


def rc():
    rows = {int(r["ro"]): float(r["rc_MHz"]) for r in csv.DictReader(open(RC))}
    return [rows[i] for i in sorted(rows)]


def deltas(f):
    """Routing-induced separation of each pair, percent of the arm mean."""
    m = st.mean(f)
    return [(f[a] - f[b]) / m * 100.0 for a, b in PAIRS]


def score(dl, sigma_ring):
    sp = sigma_ring * math.sqrt(2.0)
    out = []
    for d in dl:
        p = phi(d / sp)                  # P(bit reads as the routing predicts)
        out.append((d, p, hbin(p), max(p, 1 - p)))
    return out


def main():
    fl, fr = lumped(), rc()
    dl, dr = deltas(fl), deltas(fr)

    print("Arm A, eight adjacent pairs, separation in percent of the arm mean.")
    print("Entropy is across dies. Attacker accuracy is the chance the sign")
    print("predicted from the design database is the one the die returns.\n")
    print("  pair    lumped     full RC    |delta|/sigma   entropy   accuracy")
    agree = 0
    for (a, b), d1, d2, (_, _, h, acc) in zip(PAIRS, dl, dr, score(dr, SIGMA_RING)):
        same = (d1 > 0) == (d2 > 0)
        agree += same
        print("  %2d/%-2d %+8.3f%%  %+8.3f%%   %10.1f   %7.3f   %6.1f%%%s"
              % (a, b, d1, d2, abs(d2) / (SIGMA_RING * math.sqrt(2)), h,
                 acc * 100, "" if same else "   sign differs"))

    rows = score(dr, SIGMA_RING)
    ent = sum(r[2] for r in rows)
    exp_right = sum(r[3] for r in rows)
    dead = sum(1 for r in rows if r[2] < 0.01)

    print("\n  %d of 8 pairs get the same sign from the cheap lumped model and the"
          % agree)
    print("  full RC network, so a coarse prediction already agrees with a careful")
    print("  one on most bits.")

    print("\nTotals for Arm A, using the %.3f%% per-ring mismatch estimate:"
          % SIGMA_RING)
    print("  across-die entropy      %.2f bits out of 8" % ent)
    print("  bits effectively fixed  %d of 8 (entropy under 0.01)" % dead)
    print("  expected bits guessed   %.2f of 8 from public design files alone"
          % exp_right)

    lo = score(dr, SIGMA_HI)   # larger mismatch, more entropy survives
    hi = score(dr, SIGMA_LO)
    print("  the mismatch estimate carries a sampling interval, so entropy runs")
    print("  %.2f to %.2f bits and guessed bits run %.2f to %.2f."
          % (sum(r[2] for r in hi), sum(r[2] for r in lo),
             sum(r[3] for r in lo), sum(r[3] for r in hi)))

    print("\nArm B, by construction: every pair has zero routing offset, so each")
    print("  bit is a coin flip decided by mismatch. 8.00 bits of 8, and the")
    print("  design database predicts none of them.")

    print("\nThe caveat that matters. Both arms are simulated, and the routing")
    print("deltas above are model output rather than measurement. A die that")
    print("disagrees with them refutes this, which is the point of taping it out.")


if __name__ == "__main__":
    main()
