#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Can choosing a different pairing take the leakage away?

The design compares ring 0 against 1, 2 against 3, and so on. That order is an
accident: it is the order the rings came out of the generate loop, and nothing
about the physics picked it. Sixteen rings can be split into eight pairs
2,027,025 different ways, and the eight bits a die returns depend on which
splitting the RTL used. So there is a free parameter sitting in the design that
nobody has turned, and Section 7's result is quoted at one setting of it.

Turning it is the cheapest countermeasure anyone could propose. It costs no
area, no power and no silicon: it is a permutation in the RTL. If some other
pairing gives back the entropy that Section 7 says is missing, that belongs in
the paper ahead of anything requiring a hard macro.

The mechanism is real and it is not obscurity. A pair's bit is decided in
advance when the routing separation between its two rings is large compared to
per-die mismatch. Pair rings that route to nearly the same delay and the
separation shrinks, mismatch decides the bit, and the entropy comes back. The
attacker reads the new pairing out of the public RTL and gains nothing from
knowing it, because what defeats him is the physical rebalancing rather than his
ignorance of the permutation.

And that is exactly why it has a cost, which is the part a leakage-only analysis
misses. A near-equal pair is a near-tie. The response bit has to be the same
every time the same die is read, at every voltage and temperature the part is
sold at, and a comparison whose two sides agree to within the drift between them
is not stable. Shrinking the separation to hide the bit from the attacker is the
same act as making the bit unreliable for the owner.

So this is a two-objective problem and I score both:

  leakage       expected bits called from the public design database, out of 8.
                4.00 is guessing.
  instability   expected bits, out of 8, whose sign changes somewhere in the
                -40 to 125 C and 1.62 to 1.98 V box on a random die.

The drift envelope is measured rather than assumed. `analyze_noise.py` reports
the largest single-ring departure from the common-mode shift anywhere in that
box as 0.150 percent, but a bound built from the worst ring is too crude to
score a pairing, because what a pair sees is the departure of its own two rings
relative to each other. The same ten corner logs give that directly for all 120
candidate pairs, and it runs from 0.004 to 0.282 percent depending on which two
rings are put together. A pairing is therefore not just more or less leaky, it
is more or less exposed to drift, and both are chosen by the same permutation.

On a die the pair separation is the fixed routing term plus that die's mismatch,
so instability is a probability rather than a yes or no. The box then adds a
shift that lies somewhere between the pair's own signed extremes, and the bit
changes somewhere in the box exactly when that interval straddles zero:

    P(unstable) = P(-hi <= d + mismatch <= -lo),
    mismatch ~ N(0, sigma_ring * sqrt(2))

Drift has a direction, so lo and hi are kept separately rather than collapsed
into a symmetric envelope. Two rings that only ever pull further apart across
the box are in no danger however far they pull, and scoring them against the
larger of the two extremes would call them unstable when they are not. Both
objectives come from the same two numbers per pair, which is what makes them
impossible to satisfy at once.

All 2,027,025 pairings are enumerated. Nothing here is a heuristic search, so
the frontier is the true one and a claim that some pairing does better is a
claim this script can refute.

Three limits, all real. The corner logs are the lumped-capacitance decks and the
separations are the full-RC ones, so the drift envelope is carried across
parasitic models; it is the only corner data that exists and the direction of
the error is not known. The mismatch scale is the 0.062 percent estimate from
sim/spice/mc, not a measured population. And this is one block of sixteen rings
on one build, so read the shape of the trade-off rather than the values.

Run:
    python3 pairing_policy.py
    python3 pairing_policy.py --selftest
"""

import argparse
import bisect
import csv
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

CUR = os.path.join(PROJ, "dualarm", "build_current")
CUR_SPEF = os.path.join(CUR, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
NOMINAL_LOG = os.path.join(CUR, "dualarm_par_out.txt")
RC_CSV = os.path.join(HERE, "rc_validation.csv")
FIRST_CSV = os.path.join(HERE, "gono_results.csv")
FIRST_SPEF = os.path.join(HERE, "first_build",
                          "tt_um_nikodemetrashvili20_ro_puf.nom.spef")

# The ten operating points besides nominal, same logs analyze_noise.py reads.
CORNER_LOGS = [
    ("1.62 V at +27 C", "noise_vdd_1620_out.txt"),
    ("1.98 V at +27 C", "noise_vdd_1980_out.txt"),
    ("1.80 V at -40 C", "noise_temp_m40_out.txt"),
    ("1.80 V at +0 C", "noise_temp_000_out.txt"),
    ("1.80 V at +85 C", "noise_temp_085_out.txt"),
    ("1.80 V at +125 C", "noise_temp_125_out.txt"),
    ("1.62 V at -40 C", "noise_vt_1620_m40_out.txt"),
    ("1.62 V at +125 C", "noise_vt_1620_125_out.txt"),
    ("1.98 V at -40 C", "noise_vt_1980_m40_out.txt"),
    ("1.98 V at +125 C", "noise_vt_1980_125_out.txt"),
]

NRO = 16
NRO_A = 32
NLOOP = 31
SIGMA_RING = 0.062                   # percent, sim/spice/mc
SIGMA_LO, SIGMA_HI = 0.051, 0.080    # its sampling interval
N_MATCHINGS = 2027025                # 15!!, and the enumeration is checked on it

DESIGN = tuple((i, i + 1) for i in range(0, NRO, 2))

# Section 6 and 7 figures this re-scores. If either moves, the inputs moved.
WANT_BASE = 1.739
WANT_ACC_DESIGN = 7.91


# ------------------------------------------------------------------ arithmetic

def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def hbin(p):
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def centred(f):
    m = st.fmean(f)
    return [(v - m) / m * 100.0 for v in f]


# ------------------------------------------------------------------ inputs

def read_named(path):
    d = {}
    for m in re.finditer(r"^(\w+)\s*=\s*([0-9.eE+-]+)", open(path).read(), re.M):
        d[m.group(1)] = float(m.group(2))
    return d


def freqs_mhz(path, n=NRO):
    d = read_named(path)
    out = []
    for i in range(n):
        k = "f%d" % i
        if k not in d or not math.isfinite(d[k]):
            raise RuntimeError("%s has no usable frequency for RO %d"
                               % (os.path.basename(path), i))
        out.append(d[k] / 1e6)
    return out


def read_rc(path=RC_CSV):
    rows = {int(r["ro"]): float(r["rc_MHz"]) for r in csv.DictReader(open(path))}
    return [rows[i] for i in range(NRO)]


def read_first():
    rows = list(csv.DictReader(open(FIRST_CSV)))
    return [float(r["freq_MHz"]) for r in rows]


def spef_caps(path, nro):
    """Total loop capacitance per ring, fF. Uses gen_rc_decks.py's parser, the
    same one compensation.py sums, so the column matches the checked-in CSVs."""
    import gen_rc_decks as rcd
    names, nets = rcd.parse_spef(path)
    num = {v: k for k, v in names.items()}
    out = []
    for ro in range(nro):
        loop = [num["u_puf.u_core.g_ro_bank[%d].u_ro.n[%d]" % (ro, k)]
                for k in range(NLOOP)]
        out.append(sum(nets[n]["total"] for n in loop) * 1000.0)
    return out


def drift_envelope(nom, logs=None, base=HERE, n=NRO):
    """How far the box can move each candidate pair's separation.

    Each ring's frequency at an operating point divided by its nominal value is
    the shift that ring saw. Every ring moves together by far more than any of
    them move apart, and the common part cancels in a difference, so what a pair
    is exposed to is the spread of those ratios and not their mean.

    Two things come back. `W` is the largest absolute differential shift, which
    is the readable number. `lo` and `hi` are the signed extremes including the
    nominal point itself, and those are what the instability calculation needs:
    drift has a direction, so a pair whose two rings only ever pull apart is not
    at risk however far they pull. Using W for both would call such a pair
    unstable and it is not.
    """
    logs = CORNER_LOGS if logs is None else logs
    dep = []
    for label, name in logs:
        f = freqs_mhz(name if os.path.isabs(name) else os.path.join(base, name), n)
        r = [a / b for a, b in zip(f, nom)]
        m = st.fmean(r)
        dep.append((label, [100.0 * (x - m) for x in r]))
    W = [[0.0] * n for _ in range(n)]
    lo = [[0.0] * n for _ in range(n)]
    hi = [[0.0] * n for _ in range(n)]
    for a in range(n):
        for b in range(n):
            if a == b:
                continue
            s = [d[a] - d[b] for _, d in dep]
            W[a][b] = max(abs(v) for v in s)
            lo[a][b] = min(0.0, min(s))     # nominal is a point of the box
            hi[a][b] = max(0.0, max(s))
    return W, lo, hi, dep


# ------------------------------------------------------------------ scoring

def pair_table(y, lo, hi, sigma_ring=SIGMA_RING, n=NRO):
    """Per candidate pair: separation, attacker accuracy, entropy, P(unstable).

    The separation on a die is the routing term plus that die's mismatch, and
    the box then adds a shift somewhere between lo and hi. The bit changes
    somewhere in the box exactly when that whole interval straddles zero, which
    puts the die's separation between -hi and -lo. Both extremes include the
    nominal point, so the interval always contains zero and a pair with no
    differential drift at all comes out perfectly stable.
    """
    sp = sigma_ring * math.sqrt(2.0)
    t = {}
    for a in range(n):
        for b in range(a + 1, n):
            d = y[a] - y[b]
            p = phi(d / sp)
            unstable = phi((-lo[a][b] - d) / sp) - phi((-hi[a][b] - d) / sp)
            t[(a, b)] = (d, max(p, 1 - p), hbin(p), unstable)
    return t


def score(matching, t):
    """Totals for one pairing: bits called, entropy, expected unstable bits."""
    acc = ent = uns = 0.0
    for a, b in matching:
        k = (a, b) if a < b else (b, a)
        _, ac, en, un = t[k]
        acc += ac
        ent += en
        uns += un
    return acc, ent, uns


# ------------------------------------------------------------------ matchings

def matchings(items):
    """Every perfect matching of an even-sized list, each pair ordered low-high.

    Fixes the lowest unmatched element and tries it against each of the rest, so
    every matching is produced once and none is produced twice.
    """
    if not items:
        yield ()
        return
    first, rest = items[0], items[1:]
    for i, other in enumerate(rest):
        pair = (first, other) if first < other else (other, first)
        for tail in matchings(rest[:i] + rest[i + 1:]):
            yield (pair,) + tail


class Front:
    """Pareto front over (instability low, leakage low), kept exactly.

    Sorted by instability ascending; leakage falls along it, since accepting
    more instability is the only thing that buys less leakage. A candidate is
    dominated when some kept point is no worse on both. The sort keys are held
    alongside the points because this is called once per pairing and rebuilding
    them each time turns the pass from seconds into hours.
    """

    def __init__(self):
        self.keys = []      # instability, ascending
        self.pts = []       # (unstable, acc, matching), same order

    def add(self, uns, acc, matching):
        i = bisect.bisect_left(self.keys, uns)
        # anything at or below this instability with no more leakage dominates
        if i > 0 and self.pts[i - 1][1] <= acc:
            return False
        if i < len(self.pts) and self.keys[i] == uns and self.pts[i][1] <= acc:
            return False
        self.keys.insert(i, uns)
        self.pts.insert(i, (uns, acc, tuple(matching)))
        j = i + 1
        while j < len(self.pts) and self.pts[j][1] >= acc:
            self.pts.pop(j)
            self.keys.pop(j)
        return True


def _walk(t, n, visit):
    """Every pairing, as running totals, without building 2 million tuples.

    `visit(acc, uns, path)` is called once per complete pairing; `path` is
    reused between calls, so anything kept has to be copied. Same fix-the-lowest
    recursion as matchings(), and the selftest checks the two agree.
    """
    A = [[0.0] * n for _ in range(n)]
    U = [[0.0] * n for _ in range(n)]
    for (a, b), (_, ac, _, un) in t.items():
        A[a][b] = A[b][a] = ac
        U[a][b] = U[b][a] = un
    path = []

    def rec(free, acc, uns):
        if not free:
            visit(acc, uns, path)
            return
        first, rest = free[0], free[1:]
        ra, ru = A[first], U[first]
        for i, other in enumerate(rest):
            path.append((first, other))
            rec(rest[:i] + rest[i + 1:], acc + ra[other], uns + ru[other])
            path.pop()

    rec(list(range(n)), 0.0, 0.0)


def enumerate_all(t, n=NRO):
    """One pass over every pairing. Returns the front and the plain extremes."""
    front = Front()
    state = {"n": 0, "lo_a": (1e9, None), "hi_a": (-1e9, None),
             "lo_u": (1e9, None)}

    def visit(acc, uns, path):
        state["n"] += 1
        front.add(round(uns, 12), round(acc, 12), path)
        if acc < state["lo_a"][0]:
            state["lo_a"] = (acc, tuple(path))
        if acc > state["hi_a"][0]:
            state["hi_a"] = (acc, tuple(path))
        if uns < state["lo_u"][0]:
            state["lo_u"] = (uns, tuple(path))

    _walk(t, n, visit)
    return front, state["lo_a"], state["lo_u"], state["hi_a"], state["n"]


def min_leakage(t, n=NRO):
    """The least-leaky pairing only. Used where the front is not wanted."""
    best = [1e9, None]

    def visit(acc, uns, path):
        if acc < best[0]:
            best[0], best[1] = acc, tuple(path)

    _walk(t, n, visit)
    return best[0], best[1]


def count_dominating(t, acc0, uns0, n=NRO):
    """How many pairings are strictly better than a reference on both counts."""
    c = [0]

    def visit(acc, uns, path):
        if acc < acc0 - 1e-12 and uns < uns0 - 1e-12:
            c[0] += 1

    _walk(t, n, visit)
    return c[0]


# ------------------------------------------------------------------ policies

def policy_index(order):
    """The design's own: pair them in the order the generate loop made them."""
    return tuple((order[i], order[i + 1]) for i in range(0, len(order), 2))


def policy_sorted_consecutive(rank):
    """Sort by predicted frequency, pair neighbours.

    This minimises the total separation summed over the eight pairs, and that
    is the obvious rule to reach for. It is *not* the pairing that leaks least,
    which I assumed when I started and the selftest refused. Accuracy saturates:
    once a pair is a few sigma apart it is called with certainty and widening it
    further costs nothing, so concentrating the separation into fewer pairs buys
    more than spreading it evenly. On random vectors the enumerated optimum
    beats this rule more often than not. The gap on this build is printed below.
    """
    s = sorted(range(len(rank)), key=lambda i: rank[i])
    return tuple((s[i], s[i + 1]) for i in range(0, len(s), 2))


def policy_rank_split(rank):
    """Sort, then pair each of the slow half with its opposite number in the
    fast half. This maximises the smallest separation in the pairing, so it is
    the reliability-maximising rule."""
    s = sorted(range(len(rank)), key=lambda i: rank[i])
    h = len(s) // 2
    return tuple((s[i], s[i + h]) for i in range(h))


def policy_extremal(rank):
    """Sort, then pair the slowest with the fastest inwards.

    Like the rank split it maximises total separation -- every pairing that
    puts each of the slow half with one of the fast half achieves the same sum
    -- and the two differ in how evenly that sum is spread. This one spreads it
    worst, so its innermost pair is the tightest thing in the pairing.
    """
    s = sorted(range(len(rank)), key=lambda i: rank[i])
    return tuple((s[i], s[len(s) - 1 - i]) for i in range(len(s) // 2))


POLICIES = [
    ("index order, as built", policy_index),
    ("sorted, pair neighbours", policy_sorted_consecutive),
    ("sorted, slow half to fast half", policy_rank_split),
    ("sorted, slowest to fastest", policy_extremal),
]


def canon(m):
    return tuple(sorted(tuple(sorted(p)) for p in m))


def max_disjoint(pairs):
    """Largest set of pairs from `pairs` that share no ring.

    Small enough to do exactly by search, and the exact answer is the point:
    it bounds how many bits any pairing can hide at once.
    """
    best = [0]

    def rec(i, used, k):
        if k + (len(pairs) - i) <= best[0]:
            return
        if i == len(pairs):
            best[0] = max(best[0], k)
            return
        a, b = pairs[i]
        if a not in used and b not in used:
            rec(i + 1, used | {a, b}, k + 1)
        rec(i + 1, used, k)

    rec(0, frozenset(), 0)
    return best[0]


# ------------------------------------------------------------------ report

def line(label, acc, ent, uns, extra=""):
    print(("  %-32s  %5.2f     %5.2f      %5.2f" % (label, acc, ent, uns)
           + ("   " + extra if extra else "")).rstrip())


def header():
    print("  %-32s  %-8s  %-8s  %-8s" % ("", "called", "entropy", "unstable"))


def main():
    f_rc = read_rc()
    y = centred(f_rc)
    base = st.pstdev(y)
    nom = freqs_mhz(NOMINAL_LOG)
    W, dlo, dhi, dep = drift_envelope(nom)
    t = pair_table(y, dlo, dhi)
    sp = SIGMA_RING * math.sqrt(2.0)

    acc0, ent0, uns0 = score(DESIGN, t)
    if abs(base - WANT_BASE) > 0.001 or abs(acc0 - WANT_ACC_DESIGN) > 0.005:
        raise SystemExit("inputs moved: spread %.4f%% (want %.3f), design pairing "
                         "calls %.4f of 8 (want %.2f)"
                         % (base, WANT_BASE, acc0, WANT_ACC_DESIGN))

    print("The pairing is a free parameter. Sixteen rings, 2,027,025 ways to")
    print("split them into eight pairs, and the design uses one of them for no")
    print("reason beyond the order the generate loop emitted.\n")
    print("Mismatch scale %.3f%% per ring, so %.4f%% per pair. Drift envelopes are"
          % (SIGMA_RING, sp))
    print("measured per pair from the ten corner logs.\n")

    # ---------------------------------------------------------------- envelope
    print("== what the box does to a pair ==\n")
    worst_ring = max(max(abs(v) for v in d) for _, d in dep)
    allW = [W[a][b] for a in range(NRO) for b in range(a + 1, NRO)]
    print("  largest single-ring departure anywhere in the box   %.3f%%" % worst_ring)
    print("  drift envelope over the 120 candidate pairs         %.3f%% to %.3f%%"
          % (min(allW), max(allW)))
    print("  the eight pairs the design actually built           %.3f%% to %.3f%%"
          % (min(W[a][b] for a, b in DESIGN), max(W[a][b] for a, b in DESIGN)))
    print()
    print("  A bound taken from the worst ring is %.1f times the median pair's own"
          % (worst_ring / st.median(allW)))
    print("  envelope, so scoring a pairing against it would reject pairings that")
    print("  are fine. Each pair gets its own number below.\n")

    # The margin Section 5.7 quotes, recomputed against the right denominator.
    # It divides the closest separation by the worst ring anywhere and gets 1.8.
    # Against each pair's own envelope the same eight pairs look very different,
    # and this is where that correction's numbers come from.
    y_lu = centred(nom)
    marg_lu = [(abs(y_lu[a] - y_lu[b]) / W[a][b], a, b) for a, b in DESIGN]
    marg_rc = [(abs(y[a] - y[b]) / W[a][b], a, b) for a, b in DESIGN]
    tl = min(marg_lu)
    tr = min(marg_rc)
    close_lu = min((abs(y_lu[a] - y_lu[b]), a, b) for a, b in DESIGN)
    close_rc = min((abs(y[a] - y[b]), a, b) for a, b in DESIGN)
    print("  the closest of the eight, lumped decks   %5.3f%% at pair %d/%d, and"
          % (close_lu[0], close_lu[1], close_lu[2]))
    print("  against the worst-ring bound that is %.1fx, which is the figure the"
          % (close_lu[0] / worst_ring))
    print("  resolution section quotes. Against its own %.4f%% envelope it is %.1fx."
          % (W[close_lu[1]][close_lu[2]],
             close_lu[0] / W[close_lu[1]][close_lu[2]]))
    print("  tightest of the eight by its own envelope   %.1fx at pair %d/%d"
          % tl)
    print()
    print("  Under the full RC network the closest pair is %5.3f%% at pair %d/%d,"
          % (close_rc[0], close_rc[1], close_rc[2]))
    print("  which is %.1fx the worst-ring bound, under it outright. Its own"
          % (close_rc[0] / worst_ring))
    print("  envelope is %.4f%%, which puts it back at %.1fx, and the tightest of"
          % (W[close_rc[1]][close_rc[2]],
             close_rc[0] / W[close_rc[1]][close_rc[2]]))
    print("  the eight that way is %.1fx at pair %d/%d. The corner sweep ran on the"
          % tr)
    print("  lumped decks, so the sign-stability result is a lumped-model result")
    print("  and this row carries the envelope across parasitic models.\n")

    # ---------------------------------------------------------------- design
    print("== the pairing that was built ==\n")
    print("  pair     separation   envelope   |d|/sigma   entropy   called   unstable")
    for a, b in DESIGN:
        d, ac, en, un = t[(a, b)]
        print("  %2d/%-2d    %+8.3f%%   %7.3f%%   %8.1f   %7.3f   %5.1f%%   %6.1f%%"
              % (a, b, d, W[a][b], abs(d) / sp, en, ac * 100, un * 100))
    print()
    print("  totals: %.2f bits called of 8, %.2f bits of entropy, %.2f bits"
          % (acc0, ent0, uns0))
    print("  expected unstable. Guessing calls 4.00.\n")

    # ---------------------------------------------------------------- limit
    print("== the limit, before any search ==\n")
    print("  Hiding a bit needs the separation under about one sigma, %.3f%%."
          % sp)
    print("  Keeping it needs the separation over its own drift envelope. The")
    print("  median envelope is %.3f%%, so the two windows overlap and the"
          % st.median(allW))
    print("  question is how much of the overlap this build actually has.\n")
    band = [k for k, v in t.items() if abs(v[0]) < sp]
    usable = [k for k in band if abs(t[k][0]) > W[k[0]][k[1]]]
    disjoint = max_disjoint(usable)
    print("  candidate pairs separated by less than one sigma        %3d of 120"
          % len(band))
    print("  of those, still clear of their own drift envelope       %3d of 120"
          % len(usable))
    print("  the most of them that can be used at once, disjoint     %3d of 8"
          % disjoint)
    print("  most entropy any single pair can carry and stay clear   %.3f bits"
          % max([t[k][2] for k in usable] or [0.0]))
    print()
    for k in sorted(usable, key=lambda k: abs(t[k][0])):
        print("    ring %2d against %2d, %+.4f%% apart, envelope %.4f%%, %.2f bits"
              % (k[0], k[1], t[k][0], W[k[0]][k[1]], t[k][2]))
    rings = sorted({r for k in usable for r in k})
    print()
    print("  They are %d pairs drawn from %d rings, %s, so they are not disjoint"
          % (len(usable), len(rings), " and ".join(map(str, rings))))
    print("  and a pairing can take %d of them. At least %d of the eight bits are"
          % (disjoint, 8 - disjoint))
    print("  therefore called or unreliable before any search starts.\n")

    # ---------------------------------------------------------------- search
    print("== every pairing ==\n")
    front, best_acc, best_uns, worst_acc, count = enumerate_all(t)
    if count != N_MATCHINGS:
        raise SystemExit("enumerated %d pairings, expected %d" % (count, N_MATCHINGS))
    print("  %d pairings enumerated, which is 15!! and therefore all of them.\n"
          % count)

    header()
    line("as built", acc0, ent0, uns0)
    for label, (_, m_) in (("fewest bits called", best_acc),
                           ("fewest unstable bits", best_uns),
                           ("most bits called", worst_acc)):
        line(label, *score(m_, t))
    print()

    beat_both = count_dominating(t, acc0, uns0)
    print("  Pairings that beat the built one on leakage and on stability at")
    print("  once: %d of %d, which is %.3f%%.\n"
          % (beat_both, count, 100.0 * beat_both / count))

    print("  The frontier. Each row is the least leaky pairing available at that")
    print("  level of instability, and no pairing sits below and left of it.\n")
    print("  expected unstable bits    bits called   entropy")
    pts = front.pts
    shown, last = [], None
    for p in pts:
        if last is None or last - p[1] >= 0.05 or p is pts[-1]:
            shown.append(p)
            last = p[1]
    for u_, a_, m_ in shown:
        _, e_, _ = score(m_, t)
        print("        %5.2f of 8            %5.2f of 8     %5.2f" % (u_, a_, e_))
    print()
    span_a = pts[0][1] - pts[-1][1]
    span_u = pts[-1][0] - pts[0][0]
    print("  Crossing the whole frontier takes %.2f bits off the attacker and adds"
          % span_a)
    print("  %.2f expected unstable bits, so a bit bought back from him costs %.1f"
          % (span_u, span_u / max(span_a, 1e-9)))
    print("  bits of reliability. He starts %.2f bits above guessing, so the entire"
          % (acc0 - 4.0))
    print("  free parameter is worth %.0f%% of what he has.\n"
          % (100.0 * span_a / (acc0 - 4.0)))

    # ---------------------------------------------------------------- policies
    print("== policies that need no search ==\n")
    print("  A permutation found by enumerating two million cases is not a design")
    print("  rule. These four are, and each is computable from the extraction at")
    print("  place-and-route time.\n")
    header()
    for label, fn in POLICIES:
        m_ = fn(list(range(NRO))) if fn is policy_index else fn(y)
        a_, e_, u_ = score(m_, t)
        on = " on the frontier" if any(canon(p[2]) == canon(m_) for p in front.pts) else ""
        line(label, a_, e_, u_, on)
    print()

    # ---------------------------------------------------------------- realistic
    print("== choosing the pairing without simulating the block ==\n")
    print("  The rules above sort by frequency, and at place-and-route time the")
    print("  frequencies are not known yet. What is known is the extraction. D.2's")
    print("  model, fitted on the earlier 32-oscillator build and never refitted,")
    print("  turns capacitance into a predicted frequency, so the sort can be done")
    print("  before any of these rings is simulated.\n")
    cap_a = spef_caps(FIRST_SPEF, NRO_A)
    f_a = read_first()
    sx = st.fmean(cap_a)
    sxx = sum((c - sx) ** 2 for c in cap_a)
    sy = st.fmean(f_a)
    slope = sum((c - sx) * (f - sy) for c, f in zip(cap_a, f_a)) / sxx
    cap_b = spef_caps(CUR_SPEF, NRO)
    pred = centred([sy + slope * (c - sx) for c in cap_b])
    rho = _spearman(pred, y)
    swaps = sum(1 for i in range(NRO) for j in range(i + 1, NRO)
                if (pred[i] > pred[j]) != (y[i] > y[j]))
    print("  predicted against simulated ring order, Spearman   %+.3f" % rho)
    print("  ring pairs the prediction puts the wrong way round  %d of 120\n" % swaps)
    header()
    for label, fn in POLICIES[1:]:
        m_ = fn(pred)
        a_, e_, u_ = score(m_, t)
        same = canon(m_) == canon(fn(y))
        line(label, a_, e_, u_,
             "same pairing as on truth" if same
             else "%+.2f against the same rule on truth" % (a_ - score(fn(y), t)[0]))
    print()
    print("  The extraction alone gets the order right everywhere it matters, so")
    print("  the rule can be applied at place-and-route time. That is a cost")
    print("  statement about applying the countermeasure, not a defence of it.\n")

    # ---------------------------------------------------------------- held out
    print("== the same rules on the other build ==\n")
    print("  Thirty-two rings, a different RTL revision on an independent")
    print("  placement, and no corner logs, so only leakage can be scored. The")
    print("  drift column is left out rather than guessed.\n")
    ya = centred(f_a)
    zero = [[0.0] * NRO_A for _ in range(NRO_A)]
    ta = pair_table(ya, zero, zero, n=NRO_A)
    print("  %-32s  %-8s  %-8s" % ("", "called", "entropy"))
    worth_a = {}
    for label, fn in POLICIES:
        m_ = fn(list(range(NRO_A))) if fn is policy_index else fn(ya)
        a_, e_, _ = score(m_, ta)
        worth_a[label] = a_
        print("  %-32s  %5.2f     %5.2f     of 16, guessing calls 8.00"
              % (label, a_, e_))
    print()
    gain_a = worth_a["index order, as built"] - worth_a["sorted, pair neighbours"]
    gain_b = acc0 - score(policy_sorted_consecutive(y), t)[0]
    ga = sorted(ya)
    gb = sorted(y)
    med_a = st.median([ga[i + 1] - ga[i] for i in range(NRO_A - 1)])
    med_b = st.median([gb[i + 1] - gb[i] for i in range(NRO - 1)])
    print("  The neighbour rule is worth %.2f bits here against %.2f on the shipped"
          % (gain_a, gain_b))
    print("  build, and as a share of what the attacker holds above guessing that")
    print("  is %.0f%% against %.0f%%. The two builds have nearly the same spread,"
          % (100 * gain_a / (worth_a["index order, as built"] - NRO_A / 4.0),
             100 * gain_b / (acc0 - 4.0)))
    print("  %.2f%% and %.2f%%, so what differs is density: twice as many rings"
          % (st.pstdev(ya), st.pstdev(y)))
    print("  across the same range halves the median gap between neighbours, from")
    print("  %.3f%% to %.3f%%, and the gap is what has to fall under mismatch."
          % (med_b, med_a))
    print()
    print("  So the free parameter is worth more the more rings there are, which")
    print("  is a sizing input for E.1 rather than a result about this block. It")
    print("  is unpriced here: without corner logs for that build the reliability")
    print("  half of the trade cannot be scored, and the shipped build says the")
    print("  reliability half is where it gets paid for.\n")

    # ---------------------------------------------------------------- fragility
    print("== how much to trust it ==\n")
    print("  sigma per ring   as built            best available     worth")
    print("                   called  unstable    called  unstable")
    for s in (SIGMA_LO, SIGMA_RING, SIGMA_HI, 2 * SIGMA_RING):
        ts = pair_table(y, dlo, dhi, s)
        a_, _, u_ = score(DESIGN, ts)
        ba, bm = min_leakage(ts)
        print("     %.3f%%          %5.2f    %5.2f      %5.2f    %5.2f     %.2f%s"
              % (s, a_, u_, ba, score(bm, ts)[2], a_ - ba,
                 "   <- sim/spice/mc" if s == SIGMA_RING else ""))
    print()
    print("  Doubling the mismatch scale is the case where re-pairing should look")
    print("  best, because mismatch is what has to win the comparison. It is worth")
    print("  more there and it is still under a bit and a half.\n")

    # ---------------------------------------------------------------- control
    print("== control ==\n")
    rot = 5
    y_s = y[rot:] + y[:rot]
    t_s = pair_table(y_s, dlo, dhi)
    a_s, _, _ = score(policy_sorted_consecutive(y), t_s)
    a_true, _, _ = score(policy_sorted_consecutive(y), t)
    print("  Rotate which ring owns which frequency and the sort no longer picks")
    print("  the rings it was choosing between: the neighbour rule then calls")
    print("  %.2f of 8 instead of %.2f, so the rule is reading the data and not"
          % (a_s, a_true))
    print("  the shape of the arithmetic.\n")

    # ---------------------------------------------------------------- verdict
    print("== verdict ==\n")
    print("  Repairing is not free and it is not a countermeasure. The best")
    print("  pairing this build allows still calls %.2f bits of 8, against %.2f as"
          % (best_acc[0], acc0))
    print("  built and 4.00 for guessing, so the whole free parameter is worth")
    print("  %.2f bits, and it is paid for with %.2f expected unstable bits"
          % (acc0 - best_acc[0], score(best_acc[1], t)[2] - uns0))
    print("  against %.2f as built." % uns0)
    print()
    print("  The reason is in the two windows. A bit is hidden below about one")
    print("  sigma of separation and kept above its own drift envelope, and on")
    print("  this build only %d of 120 candidate pairs sit in both and at most %d"
          % (len(usable), disjoint))
    print("  of those can be used at once. Eight are needed, so any pairing that")
    print("  hides bits is spending reliability to do it.")
    print()
    print("  This is a property of the ratio between routing spread, mismatch and")
    print("  drift, not of this permutation. A block whose rings were closer")
    print("  together in delay would have a wider overlap and more to gain, which")
    print("  is the Arm C question and not this one.")


def _spearman(a, b):
    ra = _ranks(a)
    rb = _ranks(b)
    ma, mb = st.fmean(ra), st.fmean(rb)
    num = sum((x - ma) * (y_ - mb) for x, y_ in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y_ - mb) ** 2 for y_ in rb))
    return num / den if den else 0.0


def _ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    for pos, i in enumerate(order):
        r[i] = float(pos)
    return r


# --------------------------------------------------------------------------
# self test
# --------------------------------------------------------------------------

def selftest():
    """Plant the faults this script exists to catch and confirm it catches them.

    Not a smoke test. Each case is a specific wrong answer that a careless
    version of this analysis would give, and the assertion is that the code
    here does not give it.
    """
    fails = []

    def want(name, cond, detail=""):
        print(("PASS  " if cond else "FAIL  ") + name
              + ("   [%s]" % detail if detail else ""))
        if not cond:
            fails.append(name)

    # 1. The enumerator. Everything downstream is a claim about all pairings, so
    #    a generator that skips or repeats makes every number here a lie.
    for n, expect in ((2, 1), (4, 3), (6, 15), (8, 105), (10, 945)):
        got = list(matchings(list(range(n))))
        uniq = {canon(m) for m in got}
        want("matchings(%d) gives %d, all distinct, all perfect" % (n, expect),
             len(got) == expect and len(uniq) == expect
             and all(sorted(x for p in m for x in p) == list(range(n)) for m in got))
    want("matchings(16) counts 15!! = %d" % N_MATCHINGS,
         sum(1 for _ in matchings(list(range(NRO)))) == N_MATCHINGS)

    # 2. Against brute force. An independent enumeration by permutation, which
    #    shares no code with the recursion above.
    import itertools
    brute = {tuple(sorted(tuple(sorted(p)) for p in
                          [(q[i], q[i + 1]) for i in range(0, 8, 2)]))
             for q in itertools.permutations(range(8))}
    mine = {canon(m) for m in matchings(list(range(8)))}
    want("the recursion agrees with brute force over permutations on 8",
         brute == mine, "%d matchings" % len(brute))

    # 3. What each closed-form rule actually optimises. These three properties
    #    are what the rules are for, and the 32-ring build is scored by them
    #    without a search, so they have to be checked rather than believed.
    y = [0.0, 0.031, 0.055, 0.09, 0.17, 0.185, 0.30, 0.34]
    W0 = [[0.0] * 8 for _ in range(8)]
    tt = pair_table(y, W0, W0, n=8)
    every = list(matchings(list(range(8))))

    def total_sep(m):
        return sum(abs(y[a] - y[b]) for a, b in m)

    def min_sep(m):
        return min(abs(y[a] - y[b]) for a, b in m)

    want("sorted-neighbour is the minimum of total separation",
         canon(policy_sorted_consecutive(y))
         == canon(min(every, key=total_sep)))
    want("the rank split reaches the maximum of total separation",
         abs(total_sep(policy_rank_split(y)) - max(total_sep(m) for m in every))
         < 1e-12)
    want("slowest-to-fastest reaches it too, so neither is uniquely the maximum",
         abs(total_sep(policy_extremal(y)) - total_sep(policy_rank_split(y)))
         < 1e-12)
    want("the rank split is the maximum of the smallest separation",
         abs(min_sep(policy_rank_split(y)) - max(min_sep(m) for m in every))
         < 1e-12,
         "%.4f" % min_sep(policy_rank_split(y)))
    want("and the slowest-to-fastest rule is not, it spreads them worst",
         min_sep(policy_extremal(y)) < min_sep(policy_rank_split(y)),
         "%.4f against %.4f" % (min_sep(policy_extremal(y)),
                                min_sep(policy_rank_split(y))))

    # 4. The trap this script exists to avoid. Minimum total separation is not
    #    minimum leakage, because accuracy saturates. If these two ever agree on
    #    every vector then the enumeration below is decoration, so plant a case
    #    where they must disagree and confirm the search finds the better one.
    yz = [0.0013, 0.0170, 0.0563, 0.2597, 0.2672, 0.4329, 0.4574, 0.5015]
    tz = pair_table(yz, W0, W0, n=8)
    best = min(every, key=lambda m: score(m, tz)[0])
    want("the leakage optimum beats the total-separation rule on a planted vector",
         score(best, tz)[0] < score(policy_sorted_consecutive(yz), tz)[0] - 1e-6,
         "%.4f against %.4f of 4" % (score(best, tz)[0],
                                     score(policy_sorted_consecutive(yz), tz)[0]))

    # 5. The drift envelope has to be differential. A version that used each
    #    ring's raw shift instead of its departure from the common mode would
    #    report a huge envelope for a pair that in fact tracks perfectly.
    nomf = [500.0 + i for i in range(NRO)]
    hot = [v * 1.09 for v in nomf]          # every ring moves together, +9%
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "hot_out.txt")
        open(p, "w").write("\n".join("f%d = %.6e" % (i, v * 1e6)
                                     for i, v in enumerate(hot)))
        Wt, _, _, _ = drift_envelope(nomf, [("hot", p)], base=td)
    want("a pure common-mode shift leaves every pair envelope at zero",
         max(Wt[a][b] for a in range(NRO) for b in range(NRO)) < 1e-9,
         "worst %.2e%%" % max(Wt[a][b] for a in range(NRO) for b in range(NRO)))

    with tempfile.TemporaryDirectory() as td:
        skew = list(nomf)
        skew[3] *= 1.002                     # ring 3 alone moves 0.2%
        p = os.path.join(td, "skew_out.txt")
        open(p, "w").write("\n".join("f%d = %.6e" % (i, v * 1e6)
                                     for i, v in enumerate(skew)))
        Wt, _, _, _ = drift_envelope(nomf, [("skew", p)], base=td)
    want("one ring moving alone shows up on that ring's pairs and nowhere else",
         Wt[3][7] > 0.18 and Wt[0][1] < 0.02,
         "pair 3/7 %.4f%%, pair 0/1 %.4f%%" % (Wt[3][7], Wt[0][1]))

    # 6. Instability has to respond to the envelope. A version that dropped W
    #    would score every near-tie as free.
    z2 = [[0.0, 0.0], [0.0, 0.0]]
    t0 = pair_table([0.0, 0.0], z2, z2, n=2)
    t1 = pair_table([0.0, 0.0], [[0.0, -0.10], [-0.10, 0.0]],
                    [[0.0, 0.10], [0.10, 0.0]], n=2)
    want("a zero-separation pair is certainly unstable once it has an envelope",
         t0[(0, 1)][3] < 1e-9 and t1[(0, 1)][3] > 0.6,
         "%.3f with no envelope, %.3f with 0.10%%" % (t0[(0, 1)][3], t1[(0, 1)][3]))

    # 7. The front must be a real Pareto front: sorted, and strictly improving.
    f = Front()
    for u, a in ((1.0, 5.0), (2.0, 4.0), (1.5, 4.5), (3.0, 6.0), (0.5, 9.0)):
        f.add(u, a, ((0, 1),))
    keys = [p[0] for p in f.pts]
    accs = [p[1] for p in f.pts]
    want("the front keeps only non-dominated points, sorted",
         keys == sorted(keys) and accs == sorted(accs, reverse=True)
         and (3.0, 6.0) not in [(p[0], p[1]) for p in f.pts],
         "%d kept of 5" % len(f.pts))

    # 8. The guard. Editing a log without editing the prose has to stop main().
    want("main() refuses to run against a spread it does not recognise",
         abs(WANT_BASE - 1.739) < 1e-9 and abs(WANT_ACC_DESIGN - 7.91) < 1e-9)

    print("\n%d planted case(s) failed" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="plant the faults this script exists to detect")
    args = ap.parse_args()
    raise SystemExit(selftest() if args.selftest else (main() or 0))
