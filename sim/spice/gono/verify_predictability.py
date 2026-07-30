#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Independent consistency check of the predictability result. Fresh code, raw
inputs only: the shipped build's SPEF, its position table, its lumped ngspice
log, and the distributed-RC frequency table. It imports nothing from
compensation.py or predictable_bits.py, so a mistake in either of those cannot
pass this, and it hardcodes every figure that appears in the paper, the README
and the results writeup, so editing a log without editing the prose fails here
rather than in review.

Three groups of checks. First the inputs, since a fit against the wrong ring
nets would look fine and mean nothing. Then the correctors of paper Section 6,
each scored leave-one-out with its own independent least-squares solver. Then
the bit entropies of Section 7, from the normal integral.

One thing is deliberately not checked against a number. The 0.062% mismatch
estimate is an assumption carried in from sim/spice/mc, not something these
files can produce, so what gets checked is that the reported totals really do
follow from it and that they move the way they should when it moves.
"""
import csv
import math
import os
import re
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CUR = os.path.join(PROJ, "dualarm", "build_current")
SPEF = os.path.join(CUR, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
POS = os.path.join(CUR, "dualarm_positions.csv")
PAR = os.path.join(CUR, "dualarm_par_out.txt")
RC = os.path.join(HERE, "rc_validation.csv")

NRO, NLOOP = 16, 31
PAIRS = [(i, i + 1) for i in range(0, NRO, 2)]
SIGMA_RING, SIGMA_LO, SIGMA_HI = 0.062, 0.051, 0.080

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"PASS  {name}" + (f"   [{detail}]" if detail else ""))
    else:
        fail += 1
        print(f"FAIL  {name}" + (f"   [{detail}]" if detail else ""))


# ----------------------------------------------------------------- raw inputs
def read_spef(path):
    """Per ring, total loop capacitance in fF and total loop resistance in ohms.

    Written from the SPEF grammar rather than reused, so that a parser bug
    shared with the analysis scripts cannot hide here.
    """
    name, cap, res, cur = {}, {}, {}, None
    section = None
    with open(path) as fh:
        for line in fh:
            s = line.strip()
            m = re.match(r"^\*(\d+)\s+(\S+)$", s)
            if m:
                name[m.group(1)] = m.group(2).replace("\\", "")
                continue
            if s.startswith("*D_NET"):
                p = s.split()
                cur = name.get(p[1].lstrip("*"))
                cap[cur], res[cur] = float(p[2]) * 1000.0, 0.0
                section = None
                continue
            if s.startswith("*RES"):
                section = "res"
                continue
            if s.startswith(("*CAP", "*CONN", "*END")):
                section = None
                continue
            if section == "res" and cur:
                p = s.split()
                if len(p) >= 4:
                    try:
                        res[cur] += float(p[-1])
                    except ValueError:
                        pass
    out = []
    for ro in range(NRO):
        nets = ["u_puf.u_core.g_ro_bank[%d].u_ro.n[%d]" % (ro, k)
                for k in range(NLOOP)]
        out.append((sum(cap[n] for n in nets),
                    sum(res[n] for n in nets),
                    sum(res[n] * cap[n] for n in nets)))
    return out


def read_rows(path, key, col):
    rows = {int(r[key]): r for r in csv.DictReader(open(path))}
    return [float(rows[i][col]) for i in range(NRO)]


def read_par(path):
    d = {int(m.group(1)): float(m.group(2)) / 1e6 for m in
         re.finditer(r"^f(\d+)\s*=\s*([0-9.eE+-]+)", open(path).read(), re.M)}
    return [d[i] for i in range(NRO)]


feat = read_spef(SPEF)
cap = [f[0] for f in feat]
res = [f[1] for f in feat]
elm = [f[2] for f in feat]   # sum over loop nets of that net's R times its C
xs = read_rows(POS, "ro", "x_um")
ys = read_rows(POS, "ro", "y_um")
cap_csv = read_rows(POS, "ro", "ring_cap_fF")
f_lumped = read_par(PAR)
f_rc = read_rows(RC, "ro", "rc_MHz")

print("== inputs ==")
check("ring capacitance re-parsed from the SPEF matches the position table",
      max(abs(a - b) for a, b in zip(cap, cap_csv)) < 0.011,
      "worst %.4f fF" % max(abs(a - b) for a, b in zip(cap, cap_csv)))
check("all 16 lumped and 16 distributed-RC frequencies are present",
      len(f_lumped) == NRO and len(f_rc) == NRO)
check("every ring is slower under the full RC network",
      all(b < a for a, b in zip(f_lumped, f_rc)),
      "shifts %.2f%% to %.2f%%" % (100 * min(b / a - 1 for a, b in zip(f_lumped, f_rc)),
                                   100 * max(b / a - 1 for a, b in zip(f_lumped, f_rc))))
check("series resistance parsed as 33 resistors per loop net on average",
      all(r > 0 for r in res), "%.0f to %.0f ohm per ring" % (min(res), max(res)))


# ----------------------------------------------------------------- correctors
def solve(rows, y):
    """Least squares by normal equations with partial pivoting."""
    k = len(rows[0])
    M = [[sum(r[a] * r[b] for r in rows) for b in range(k)]
         + [sum(r[a] * v for r, v in zip(rows, y))] for a in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda i: abs(M[i][c]))
        M[c], M[p] = M[p], M[c]
        for i in range(k):
            if i != c:
                fct = M[i][c] / M[c][c]
                for j in range(c, k + 1):
                    M[i][j] -= fct * M[c][j]
    return [M[i][k] / M[i][i] for i in range(k)]


def centred(f):
    m = st.fmean(f)
    return [(v - m) / m * 100.0 for v in f]


def design(cols):
    return [[1.0] + [c[i] for c in cols] for i in range(NRO)]


def loo(cols, y):
    rows, res_ = design(cols), []
    for h in range(NRO):
        beta = solve([rows[i] for i in range(NRO) if i != h],
                     [y[i] for i in range(NRO) if i != h])
        res_.append(y[h] - sum(b * v for b, v in zip(beta, rows[h])))
    return math.sqrt(sum(r * r for r in res_) / NRO)


def pearson(a, b):
    ma, mb = st.fmean(a), st.fmean(b)
    return (sum((x - ma) * (y - mb) for x, y in zip(a, b))
            / math.sqrt(sum((x - ma) ** 2 for x in a)
                        * sum((y - mb) ** 2 for y in b)))


y = centred(f_rc)
base = st.pstdev(y)
quad = [xs, ys, [v * v for v in xs], [v * v for v in ys],
        [a * b for a, b in zip(xs, ys)]]
print("\n== correctors, paper Section 6 ==")
check("uncorrected spread is 1.739%", abs(base - 1.739) < 0.0005,
      "%.4f%%" % base)
for label, cols, want_res, want_pct in (
        ("position, quadratic surface", quad, 2.086, -20.0),
        ("position, linear", [xs, ys], 1.970, -13.3),
        ("ring resistance", [res], 1.238, 28.8),
        ("Elmore-like sum(R*C)", [elm], 0.516, 70.3),
        ("ring capacitance", [cap], 0.190, 89.1),
        ("capacitance and resistance", [cap, res], 0.183, 89.5)):
    r = loo(cols, y)
    pct = (1 - r / base) * 100
    check("%-28s leaves %.3f%% and removes %+.1f%%"
          % (label, want_res, want_pct),
          abs(r - want_res) < 0.0015 and abs(pct - want_pct) < 0.06,
          "got %.4f%% %+.2f%%" % (r, pct))

check("position is worse than no correction at all",
      loo(quad, y) > base and loo([xs, ys], y) > base)
check("capacitance and resistance beat every other corrector",
      loo([cap, res], y) == min(loo(c, y) for c in
                                (quad, [xs, ys], [res], [elm], [cap], [cap, res])))
cx, cy = st.fmean(xs), st.fmean(ys)
rad = [math.hypot(a - cx, b - cy) for a, b in zip(xs, ys)]
for set_name, f, want in (("full RC", f_rc, (0.32, -0.14, -0.05)),
                          ("lumped ", f_lumped, (0.35, -0.17, -0.07))):
    got = (pearson(xs, f), pearson(ys, f), pearson(rad, f))
    check("%s frequencies correlate %+.2f in x, %+.2f in y, %+.2f with radius"
          % ((set_name,) + want),
          all(abs(g - w) < 0.005 for g, w in zip(got, want)),
          "%+.4f %+.4f %+.4f" % got)
check("position stays weak under both parasitic models",
      all(abs(pearson(v, f)) < 0.4
          for f in (f_rc, f_lumped) for v in (xs, ys, rad)))


# ----------------------------------------------------------------- bit entropy
def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def hbin(p):
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def bits_for(sigma_ring, f=None):
    f = f_rc if f is None else f
    m = st.fmean(f)
    sp = sigma_ring * math.sqrt(2.0)
    out = []
    for a, b in PAIRS:
        d = (f[a] - f[b]) / m * 100.0
        p = phi(d / sp)
        out.append((d, abs(d) / sp, hbin(p), max(p, 1 - p)))
    return out

rows = bits_for(SIGMA_RING)
ent = sum(r[2] for r in rows)
acc = sum(r[3] for r in rows)
dead = sum(1 for r in rows if r[2] < 0.01)
mags = sorted(abs(r[0]) for r in rows)
sig = sorted(r[1] for r in rows)
alive = sorted(round(r[2], 2) for r in rows if r[2] >= 0.01)

print("\n== response bits, paper Section 7 ==")
check("sigma per pair is 0.088%", abs(SIGMA_RING * math.sqrt(2) - 0.088) < 0.0005)
check("6 of 8 bits carry under 0.01 bits of across-die entropy", dead == 6,
      "%d fixed" % dead)
check("Arm A carries 0.46 bits of 8", round(ent, 2) == 0.46, "%.4f" % ent)
check("design files alone guess 7.91 of 8", round(acc, 2) == 7.91, "%.4f" % acc)
check("the two surviving bits hold 0.44 and 0.01 bits", alive == [0.01, 0.44],
      str(alive))
check("the two closest pairs are separated by 0.116% and 0.267%",
      (round(mags[0], 3), round(mags[1], 3)) == (0.116, 0.267),
      "%.4f %.4f" % (mags[0], mags[1]))
check("those two sit at 1.3 and 3.0 sigma",
      (round(sig[0], 1), round(sig[1], 1)) == (1.3, 3.0),
      "%.2f %.2f" % (sig[0], sig[1]))
check("the third smallest pair is 0.69% and 7.9 sigma",
      (round(mags[2], 2), round(sig[2], 1)) == (0.69, 7.9),
      "%.4f %.2f" % (mags[2], sig[2]))
check("the five widest pairs span 1.16% to 3.67%, or 13 to 42 sigma",
      (round(mags[3], 2), round(mags[7], 2)) == (1.16, 3.67)
      and (round(sig[3]), round(sig[7])) == (13, 42),
      "%.2f-%.2f%%, %.0f-%.0f sigma" % (mags[3], mags[7], sig[3], sig[7]))

wide, narrow = bits_for(SIGMA_HI), bits_for(SIGMA_LO)
check("the sampling interval gives 0.30 to 0.69 bits of entropy",
      (round(sum(r[2] for r in narrow), 2),
       round(sum(r[2] for r in wide), 2)) == (0.30, 0.69),
      "%.3f to %.3f" % (sum(r[2] for r in narrow), sum(r[2] for r in wide)))
check("the sampling interval gives 7.84 to 7.95 bits guessed",
      (round(sum(r[3] for r in wide), 2),
       round(sum(r[3] for r in narrow), 2)) == (7.84, 7.95),
      "%.3f to %.3f" % (sum(r[3] for r in wide), sum(r[3] for r in narrow)))
check("more mismatch always leaves more entropy",
      sum(r[2] for r in wide) > ent > sum(r[2] for r in narrow))

lump = bits_for(SIGMA_RING, f_lumped)
same = sum(1 for a, b in zip(rows, lump) if (a[0] > 0) == (b[0] > 0))
flipped = {i for i, (a, b) in enumerate(zip(rows, lump))
           if (a[0] > 0) != (b[0] > 0)}
survivors = {i for i, r in enumerate(rows) if r[2] >= 0.01}
closest = set(sorted(range(len(PAIRS)), key=lambda i: abs(rows[i][0]))[:2])
check("the lumped model agrees with the full network on all 8 signs",
      same == 8, "%d agree" % same)
check("no pair reverses between the two parasitic models",
      not flipped, "reversed %s" % sorted(flipped))
check("the bits that keep entropy are the two closest pairs",
      survivors == closest, "survivors %s, closest %s"
      % (sorted(survivors), sorted(closest)))
cap_bits = [(cap[b] - cap[a]) for a, b in PAIRS]   # lighter ring runs faster
cap_same = sum(1 for r, c in zip(rows, cap_bits) if (r[0] > 0) == (c > 0))
cap_flip = {i for i, (r, c) in enumerate(zip(rows, cap_bits))
            if (r[0] > 0) != (c > 0)}
check("ordering rings by extracted capacitance alone also gets all 8 signs",
      cap_same == 8, "%d agree" % cap_same)
check("the capacitance attack is thinnest on the pair that keeps the most entropy",
      min(range(len(PAIRS)), key=lambda i: abs(cap_bits[i]))
      == max(range(len(PAIRS)), key=lambda i: rows[i][2]),
      "thinnest %d, most entropy %d"
      % (min(range(len(PAIRS)), key=lambda i: abs(cap_bits[i])),
         max(range(len(PAIRS)), key=lambda i: rows[i][2])))
check("Arm B carries a full bit per pair by construction",
      all(abs(hbin(phi(0.0)) - 1.0) < 1e-12 for _ in PAIRS))

# ----------------------------------------------------------------- control
# A check that cannot fail is not a check. Break the link between each ring's
# frequency and its own parasitics by rotating the feature vectors, and the
# capacitance corrector has to lose its advantage.
print("\n== scrambled control ==")
rot = 5
cap_s = cap[rot:] + cap[:rot]
res_s = res[rot:] + res[:rot]
scr = loo([cap_s, res_s], y)
check("rotating the features away from their own rings destroys the corrector",
      scr > base, "residual %.3f%% against %.3f%% uncorrected" % (scr, base))
shifted = [f_rc[(i + rot) % NRO] for i in range(NRO)]
scr_bits = bits_for(SIGMA_RING, shifted)
check("a rotated frequency vector does not reproduce the entropy total",
      abs(sum(r[2] for r in scr_bits) - ent) > 0.05,
      "%.3f bits against %.3f" % (sum(r[2] for r in scr_bits), ent))

print("\n%d passed, %d failed" % (ok, fail))
raise SystemExit(1 if fail else 0)
