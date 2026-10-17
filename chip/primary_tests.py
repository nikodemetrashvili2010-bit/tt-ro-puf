#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The two primary tests, as chip/PREREG_AMENDMENT.json names them.

Written on 18 October 2026 with no die read. The amendment records this
file's SHA-256, so chip/hash_stability.py H02 fails the gate the day a byte
of it changes. If it has to change, that is a new amendment with a date and
a reason, the same as the preregistration it amends.

M1 is the exact one-sided binomial on Arm A's scored pairs: n pairs that did
not abstain, k of them predicted right, p the chance of k or more right out
of n at one half each. Integer arithmetic, so 6 of 6 is exactly 1/64.

M4 is Arm C's standard deviation over Arm A's, over the 16 ring means of
each arm at the nominal cell of the first die read. Its interval comes from
a permutation test, inverted. Each arm is centred on its own median first.
For a ratio r, Arm C's centred values are divided by r and pooled with Arm
A's, and the 32 are shuffled between the two arms, 16 and 16, with a
generator seeded once. p(r) is the share of shuffles, the observed split
counted as one of them, whose ratio is at or under the observed one. It
assumes only that the two arms, centred, differ in scale and not in shape.

The interval is every r whose p(r) is above the level Holm gives M4, and it
is clear of 1 exactly when p(1) is at or under that level. Its upper end is
found by bisection on r, with the same shuffles at every r, so p(r) is one
function of r and not a fresh draw each time it is asked.

Holm over the two primaries: the smaller p is tested at 0.025, the other at
0.05 if the first passed.

    python3 primary_tests.py --selftest
    python3 primary_tests.py --m1 N K
    python3 primary_tests.py --m4 A.csv C.csv [--level 0.025]

A.csv and C.csv hold one ring mean a line, sixteen lines each.
"""

import argparse
import math
import random
import sys

SHUFFLES = 100000
SEED = 20261018
ALPHA = 0.05
N_RING = 16


def m1_p(n, k):
    """P(X >= k) for X binomial(n, 1/2), exactly, as a float."""
    if not 0 <= k <= n:
        raise ValueError("k must be between 0 and n")
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def holm(pvals, alpha=ALPHA):
    """Holm's step-down over a dict of name -> p. name -> (level, passed)."""
    order = sorted(pvals, key=lambda name: (pvals[name], name))
    out = {}
    still = True
    for i, name in enumerate(order):
        level = alpha / (len(order) - i)
        still = still and pvals[name] <= level
        out[name] = (level, still)
    return out


def sd(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def centred(xs):
    m = median(xs)
    return [x - m for x in xs]


def splits(n_a, n_c, shuffles, seed):
    """The shuffles, drawn once from one random.Random(seed). The pooled
    indices, Arm A's in ring order and then Arm C's, are shuffled in place
    again and again and every order is kept. Each is a uniform shuffle
    whatever order it started from, so starting from the last costs
    nothing."""
    rng = random.Random(seed)
    idx = list(range(n_a + n_c))
    out = []
    for _ in range(shuffles):
        rng.shuffle(idx)
        out.append(tuple(idx))
    return out


class M4:
    """The M4 test on one die's two arms, with its shuffles held fixed."""

    def __init__(self, a, c, shuffles=SHUFFLES, seed=SEED):
        if len(a) != N_RING or len(c) != N_RING:
            raise ValueError("M4 wants %d ring means an arm" % N_RING)
        self.a = centred(a)
        self.c = centred(c)
        self.ratio = sd(c) / sd(a)
        self.n = len(self.a)
        self.cuts = splits(len(self.a), len(self.c), shuffles, seed)

    def p(self, r=1.0):
        pool = self.a + [v / r for v in self.c]
        seen = sd(self.c) / r / sd(self.a)
        n = self.n
        at_or_under = 1  # the observed split is one of them
        for cut in self.cuts:
            ra = [pool[i] for i in cut[:n]]
            rc = [pool[i] for i in cut[n:]]
            if sd(rc) / sd(ra) <= seen * (1 + 1e-12):
                at_or_under += 1
        return at_or_under / (len(self.cuts) + 1)

    def upper(self, level, steps=40):
        """The largest r the test does not reject at level, by bisection on
        log r. It starts from the ratio itself, where the observed split
        sits near the middle of the shuffles, and doubles r until one is
        rejected."""
        lo = self.ratio
        if self.p(lo) <= level:
            return lo
        hi = lo * 2
        while self.p(hi) > level:
            lo, hi = hi, hi * 2
            if hi > 1e6 * self.ratio:
                return float("inf")
        for _ in range(steps):
            mid = math.sqrt(lo * hi)
            if self.p(mid) > level:
                lo = mid
            else:
                hi = mid
        return lo


def selftest():
    bad = []

    def check(cid, what, ok, detail=""):
        print("  %-5s %-4s %s%s" % ("ok" if ok else "FAIL", cid, what,
                                    "  (%s)" % detail if detail else ""))
        if not ok:
            bad.append(cid)

    print("primary_tests selftest")
    # M1 against fractions worked by hand, not by the function's own loop.
    check("T01", "6 of 6 is 1/64, 5 of 5 is 1/32, 5 of 6 is 7/64",
          m1_p(6, 6) == 1 / 64 and m1_p(5, 5) == 1 / 32
          and m1_p(6, 5) == 7 / 64, "%.6f %.6f %.6f"
          % (m1_p(6, 6), m1_p(5, 5), m1_p(6, 5)))
    check("T02", "0 of 0 and k of n at k = 0 are certainties",
          m1_p(0, 0) == 1.0 and m1_p(8, 0) == 1.0)
    h = holm({"M1": 0.015625, "M4": 0.03})
    check("T03", "Holm: 0.015625 first at 0.025, 0.03 second at 0.05",
          h == {"M1": (0.025, True), "M4": (0.05, True)}, str(h))
    h = holm({"M1": 0.03125, "M4": 0.04})
    check("T04", "Holm stops at the first that fails",
          h == {"M1": (0.025, False), "M4": (0.05, False)}, str(h))
    h7 = 0.05 / 7
    check("T05", "the frozen family of seven would fail a perfect 6 of 6",
          m1_p(6, 6) > h7, "%.6f against %.6f" % (m1_p(6, 6), h7))

    # Two arms built by formula, no randomness: C a quarter of A's spread.
    a = [570.0 + 6.0 * math.sin(1.7 * i) + 0.4 * i for i in range(N_RING)]
    c = [580.0 + 1.5 * math.cos(2.3 * i) - 0.1 * i for i in range(N_RING)]
    t = M4(a, c, shuffles=2000)
    p1 = t.p(1.0)
    check("T06", "a ratio near a quarter rejects at 1",
          t.ratio < 0.3 and p1 <= 0.025, "ratio %.3f, p(1) %.5f"
          % (t.ratio, p1))
    check("T07", "the observed split counts, so p is never 0",
          p1 >= 1 / 2001, "%.6f" % p1)
    t2 = M4(a, [v + 1000.0 for v in c], shuffles=2000)
    t3 = M4([v * 3.0 for v in a], [v * 3.0 for v in c], shuffles=2000)
    check("T08", "moving one arm, or scaling both, changes nothing",
          t2.p(1.0) == p1 and t3.p(1.0) == p1,
          "%.5f %.5f %.5f" % (p1, t2.p(1.0), t3.p(1.0)))
    same = M4(a, a, shuffles=2000)
    check("T09", "two identical arms are nowhere near rejecting",
          same.p(1.0) > 0.4, "p(1) %.4f" % same.p(1.0))
    check("T10", "the same seed gives the same shuffles and the same p",
          M4(a, c, shuffles=2000).p(1.3) == t.p(1.3)
          and splits(16, 16, 50, SEED) == splits(16, 16, 50, SEED)
          and splits(16, 16, 50, SEED) != splits(16, 16, 50, SEED + 1))
    u = t.upper(0.025)
    check("T11", "the upper end is not rejected and just above it is",
          t.ratio <= u < 1 and t.p(u) > 0.025 and t.p(u * 1.001) <= 0.025,
          "upper %.4f, p %.4f and %.4f" % (u, t.p(u), t.p(u * 1.001)))
    check("T12", "the interval is clear of 1 exactly when p(1) is under",
          (u < 1) == (p1 <= 0.025))
    try:
        M4(a[:15], c)
        check("T13", "fifteen rings are refused", False)
    except ValueError:
        check("T13", "fifteen rings are refused", True)

    print("\n  %s" % ("all %d checks pass" % 13 if not bad
                      else "FAILED: " + ", ".join(bad)))
    return 1 if bad else 0


def read_column(path):
    with open(path, "r", encoding="utf-8") as fh:
        return [float(l) for l in fh if l.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--m1", nargs=2, type=int, metavar=("N", "K"))
    ap.add_argument("--m4", nargs=2, metavar=("A_CSV", "C_CSV"))
    ap.add_argument("--level", type=float, default=0.025)
    ap.add_argument("--shuffles", type=int, default=SHUFFLES)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.m1:
        n, k = a.m1
        print("M1  %d of %d right, p = %.6f" % (k, n, m1_p(n, k)))
        return 0
    if a.m4:
        t = M4(read_column(a.m4[0]), read_column(a.m4[1]),
               shuffles=a.shuffles)
        u = t.upper(a.level)
        print("M4  ratio %.4f, p(1) = %.6f, upper end at %.3f: %.4f"
              % (t.ratio, t.p(1.0), a.level, u))
        print("    %s" % ("clear of 1" if u < 1 else "not clear of 1"))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
