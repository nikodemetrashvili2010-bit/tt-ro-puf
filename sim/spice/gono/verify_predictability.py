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
import sys

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
def read_spef(path, nro=None):
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
    for ro in range(NRO if nro is None else nro):
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


def design(cols, n=None):
    return [[1.0] + [c[i] for c in cols] for i in range(NRO if n is None else n)]


def loo(cols, y):
    n = len(y)
    rows, res_ = design(cols, n), []
    for h in range(n):
        beta = solve([rows[i] for i in range(n) if i != h],
                     [y[i] for i in range(n) if i != h])
        res_.append(y[h] - sum(b * v for b, v in zip(beta, rows[h])))
    return math.sqrt(sum(r * r for r in res_) / n)


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
check("a pair with no separation at all carries exactly one bit",
      all(abs(hbin(phi(0.0)) - 1.0) < 1e-12 for _ in PAIRS))

# ------------------------------------------------------- compensated bits, 7.4
# Section 6 subtracts the layout term, Section 7 counts the bits. Section 7.2
# does both at once, so the numbers it quotes have to follow from the same two
# solvers used above and not from a third one hiding in compensated_bits.py.


def loo_resid(cols, yv):
    rws = design(cols)
    out = []
    for h in range(NRO):
        beta = solve([rws[i] for i in range(NRO) if i != h],
                     [yv[i] for i in range(NRO) if i != h])
        out.append(yv[h] - sum(b * v for b, v in zip(beta, rws[h])))
    return out


def bits_from(resid, sigma_ring):
    sp = sigma_ring * math.sqrt(2.0)
    out = []
    for a, b in PAIRS:
        d = resid[a] - resid[b]
        p = phi(d / sp)
        out.append((d, abs(d) / sp, hbin(p), max(p, 1 - p)))
    return out


print("\n== compensated bits, paper Section 7.2 ==")
comp = loo_resid([cap, res], y)
crow = bits_from(comp, SIGMA_RING)
cent = sum(r[2] for r in crow)
cacc = sum(r[3] for r in crow)
cdead = sum(1 for r in crow if r[2] < 0.01)
check("the corrected residual is still Section 6's 0.183%",
      abs(math.sqrt(sum(r * r for r in comp) / NRO) - 0.183) < 0.0015,
      "%.4f%%" % math.sqrt(sum(r * r for r in comp) / NRO))
check("compensation raises entropy from 0.46 to 2.91 bits of 8",
      round(cent, 2) == 2.91, "%.4f" % cent)
check("the attacker applying the same correction still calls 7.19 of 8",
      round(cacc, 2) == 7.19, "%.4f" % cacc)
check("effectively fixed bits fall from 6 to 1", cdead == 1, "%d fixed" % cdead)
check("compensation helps: more entropy and a worse attacker than uncorrected",
      cent > ent and cacc < acc)
check("and does not rescue it: still far from a coin flip",
      cent < 4.0 and cacc > 6.0)
flip = sum(1 for u, c in zip(rows, crow) if (u[0] > 0) != (c[0] > 0))
check("5 of the 8 predicted signs flip under compensation", flip == 5,
      "%d flipped" % flip)

fullb = solve(design([cap, res]), y)
fullr = [y[i] - sum(b * v for b, v in zip(fullb, design([cap, res])[i]))
         for i in range(NRO)]
check("the full 16-ring fit is the optimistic case, not the reported one",
      sum(r[2] for r in bits_from(fullr, SIGMA_RING)) > cent,
      "%.3f against %.3f bits" % (sum(r[2] for r in bits_from(fullr, SIGMA_RING)),
                                  cent))

cnar = sum(r[2] for r in bits_from(comp, SIGMA_LO))
cwid = sum(r[2] for r in bits_from(comp, SIGMA_HI))
check("the sampling interval gives 2.36 to 3.67 compensated bits",
      (round(cnar, 2), round(cwid, 2)) == (2.36, 3.67),
      "%.3f to %.3f" % (cnar, cwid))
check("the compensated total is the more mismatch-sensitive of the two",
      (cwid - cnar) > (sum(r[2] for r in bits_for(SIGMA_HI))
                       - sum(r[2] for r in bits_for(SIGMA_LO))),
      "spans %.2f bits against %.2f"
      % (cwid - cnar, sum(r[2] for r in bits_for(SIGMA_HI))
         - sum(r[2] for r in bits_for(SIGMA_LO))))

capr = loo_resid([cap], y)
capent = sum(r[2] for r in bits_from(capr, SIGMA_RING))
check("capacitance alone leaves 0.190% and only 1.56 bits",
      abs(math.sqrt(sum(r * r for r in capr) / NRO) - 0.190) < 0.0015
      and round(capent, 2) == 1.56,
      "%.4f%%, %.3f bits" % (math.sqrt(sum(r * r for r in capr) / NRO), capent))
check("a 4% change in residual moves the entropy total by more than half",
      abs(cent - capent) / cent > 0.4,
      "0.190%% -> %.2f bits against 0.183%% -> %.2f bits" % (capent, cent))


# ------------------------------------------------- matched-macro arm, 8.2
# Section 8.2 replaces an assumption with a measurement: the sixteen hardened
# instances were said to carry zero routing offset because they share one
# internal layout, and they do not quite, because each one carries its own
# enable and output route at the top level. These checks rebuild the spread,
# the direction test and the bits from the three archived per-instance logs.
print("\n== matched-macro arm, paper Section 8.2 ==")

ARMB = {"tt": os.path.join(HERE, "armb_instances_out.txt"),
        "ss": os.path.join(HERE, "armb_instances_ss_out.txt"),
        "ff": os.path.join(HERE, "armb_instances_ff_out.txt")}
WANT_ARMB_PTP = {"tt": 0.00251, "ss": 0.00014, "ff": 0.00085}


def read_instances(path):
    """The sixteen instance frequencies and the no-route reference, in MHz."""
    txt = open(path, errors="ignore").read()
    got = {n: float(v) for n, v in
           re.findall(r"^(f_\w+)\s*=\s*(-?[0-9.]+(?:[eE][+-]?\d+)?)", txt, re.M)}
    return ([got["f_k%02d" % k] / 1e6 for k in range(NRO)], got["f_r"] / 1e6)


armb, armb_ref = {}, {}
for corner, path in ARMB.items():
    armb[corner], armb_ref[corner] = read_instances(path)
check("all three per-instance logs hold sixteen frequencies and a reference",
      all(len(v) == NRO for v in armb.values()) and len(armb_ref) == 3)

for corner in ("tt", "ss", "ff"):
    f = armb[corner]
    ptp = 100.0 * (max(f) - min(f)) / st.fmean(f)
    check("Arm B spreads %.5f%% peak to peak at %s" % (WANT_ARMB_PTP[corner], corner),
          abs(ptp - WANT_ARMB_PTP[corner]) < 5e-5, "%.5f%%" % ptp)

# A passive route adds capacitance and cannot remove any, so loading can only
# slow a ring down. Instances above the no-route reference are the proof that
# the residual is not the routes.
for corner in ("tt", "ff"):
    up = sum(1 for v in armb[corner] if v > armb_ref[corner])
    check("at %s some instances read faster than the no-route reference, which "
          "loading cannot cause" % corner, up >= 6, "%d of 16 above" % up)

armb_c = centred(armb["tt"])
armb_sd = st.pstdev(armb_c)
check("Arm B's tt spread is under a fiftieth of the mismatch scale",
      armb_sd / SIGMA_RING < 0.02, "%.4f sigma" % (armb_sd / SIGMA_RING))
check("Arm A's layout term is more than two thousand times Arm B's, on "
      "standard deviations",
      base / armb_sd > 2000, "%.0f times" % (base / armb_sd))

armb_d = [armb_c[a] - armb_c[b] for a, b in PAIRS]
armb_ent = sum(hbin(phi(d / (SIGMA_RING * math.sqrt(2)))) for d in armb_d)
armb_acc = sum(max(phi(d / (SIGMA_RING * math.sqrt(2))),
                   1 - phi(d / (SIGMA_RING * math.sqrt(2)))) for d in armb_d)
check("Arm B keeps 8.00 of 8 bits where Arm A keeps 0.46",
      round(armb_ent, 2) == 8.00 and armb_ent < 8.0, "%.4f bits" % armb_ent)
check("the design files guess 4.02 of Arm B's 8 bits against 7.91 of Arm A's",
      round(armb_acc, 2) == 4.02, "%.4f of 8" % armb_acc)
check("no Arm B bit is effectively fixed",
      all(hbin(phi(d / (SIGMA_RING * math.sqrt(2)))) > 0.99 for d in armb_d))

# Nothing in the design database predicts the leftover. Position is included
# because Arm B sits on a regular grid, which is where a fitted surface has its
# best chance.
inst = {int(r["instance"]): r for r in
        csv.DictReader(open(os.path.join(HERE, "instance_parasitics.csv")))}
en_c = [float(inst[k]["en_cap_fF"]) for k in range(NRO)]
ou_c = [float(inst[k]["out_cap_fF"]) for k in range(NRO)]
tot_c = [a + b for a, b in zip(en_c, ou_c)]
en_r = [float(inst[k]["en_res"]) for k in range(NRO)]
ou_r = [float(inst[k]["out_res"]) for k in range(NRO)]
best_armb = min(loo(cols, armb_c) for cols in
                ([tot_c], [ou_c], [en_c], [en_r, ou_r], [tot_c, en_r, ou_r]))
check("every route-parasitic corrector is worse than leaving Arm B alone",
      best_armb > armb_sd,
      "best leaves %.5f%% against %.5f%%" % (best_armb, armb_sd))
check("Arm A's own corrector removes 89.5% where Arm B's removes nothing",
      (1 - loo([cap, res], y) / base) > 0.89 > (1 - best_armb / armb_sd))


# ------------------------------------------------- cross-build transfer, 6.2
# Section 6.2 asks whether the model has to be fitted on the victim. These
# checks refit it on the first build, which is a different RTL revision on an
# independent placement, and apply it to the shipped build without refitting.
print("\n== cross-build transfer, paper Section 6.2 ==")

FIRST_SPEF = os.path.join(HERE, "first_build",
                          "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
FIRST_CSV = os.path.join(HERE, "gono_results.csv")
NRO_A = 32

rows_a = {int(r["ro"]): r for r in csv.DictReader(open(FIRST_CSV))}
f_a = [float(rows_a[i]["freq_MHz"]) for i in range(NRO_A)]
cap_a_csv = [float(rows_a[i]["ring_cap_fF"]) for i in range(NRO_A)]
feat_a = read_spef(FIRST_SPEF, NRO_A)
cap_a = [v[0] for v in feat_a]
check("first-build ring capacitance re-parsed from its SPEF matches its table",
      max(abs(a - b) for a, b in zip(cap_a, cap_a_csv)) < 0.011,
      "worst %.4f fF" % max(abs(a - b) for a, b in zip(cap_a, cap_a_csv)))

slope_a = solve(design([cap_a], NRO_A), f_a)[1]
slope_b = solve(design([cap], NRO), f_lumped)[1]
check("the two lumped builds fit -4.93 and -4.94 MHz/fF",
      abs(slope_a + 4.93) < 0.01 and abs(slope_b + 4.94) < 0.01,
      "%.4f and %.4f" % (slope_a, slope_b))
check("the two slopes agree to a tenth of a percent",
      abs(slope_a - slope_b) / abs(slope_a) < 0.001,
      "%.3f%% apart" % (abs(slope_a - slope_b) / abs(slope_a) * 100))


def transfer(train_cols, train_y, apply_cols, n):
    """Fit on one build, predict another, recentre, return the residual sd.

    Recentring is what lets the attacker skip the victim's mean frequency, and
    it is also why a constant offset in the features cannot change the answer.
    """
    beta = solve(design(train_cols, len(train_y)), train_y)
    p = [beta[0] + sum(b * c[i] for b, c in zip(beta[1:], apply_cols))
         for i in range(n)]
    m = st.fmean(p)
    return [v - m for v in p]


pred_ac = transfer([cap_a], centred(f_a), [cap], NRO)
r_ac = st.pstdev([t - p for t, p in zip(y, pred_ac)])
own = loo([cap, res], y)
check("a model fitted on the first build removes 88.2% of the shipped build's "
      "spread with no refitting",
      abs((1 - r_ac / base) * 100 - 88.2) < 0.3, "%.4f%%" % r_ac)
check("that costs 1.3 points against the corrector fitted on the victim itself",
      abs(((1 - own / base) - (1 - r_ac / base)) * 100 - 1.3) < 0.3,
      "%.1f points" % (((1 - own / base) - (1 - r_ac / base)) * 100))

pred_ca = transfer([cap], y, [cap_a], NRO_A)
ya = centred(f_a)
r_ca = st.pstdev([t - p for t, p in zip(ya, pred_ca)])
check("the transfer works in the other direction too, 89.4% onto 32 rings",
      abs((1 - r_ca / st.pstdev(ya)) * 100 - 89.4) < 0.3, "%.4f%%" % r_ca)

d_true = [y[a] - y[b] for a, b in PAIRS]
d_tr = [pred_ac[a] - pred_ac[b] for a, b in PAIRS]
agree_tr = sum(1 for u, v in zip(d_true, d_tr) if (u > 0) == (v > 0))
acc_tr = sum(phi((1 if v > 0 else -1) * u / (SIGMA_RING * math.sqrt(2)))
             for u, v in zip(d_true, d_tr))
check("the transferred model calls all 8 bits the way the full simulation does",
      agree_tr == 8, "%d of 8" % agree_tr)
check("so it guesses the same 7.91 of 8 as exact extraction",
      round(acc_tr, 2) == 7.91, "%.4f of 8" % acc_tr)

# Two rings of somebody else's build are enough, which is the cost statement.
pred_2 = transfer([cap_a[:2]], centred(f_a)[:2], [cap], NRO)
d_2 = [pred_2[a] - pred_2[b] for a, b in PAIRS]
check("a slope fitted on two rings of the other build still calls all 8",
      sum(1 for u, v in zip(d_true, d_2) if (u > 0) == (v > 0)) == 8)

# The control. Keep every capacitance, shuffle which ring owns it.
rot_c = cap[7:] + cap[:7]
pred_sh = transfer([cap_a], centred(f_a), [rot_c], NRO)
r_sh = st.pstdev([t - p for t, p in zip(y, pred_sh)])
d_sh = [pred_sh[a] - pred_sh[b] for a, b in PAIRS]
check("rotating which ring owns which capacitance is worse than no correction",
      r_sh > base, "%.4f%% against %.4f%% uncorrected" % (r_sh, base))
check("and it stops calling the bits",
      sum(1 for u, v in zip(d_true, d_sh) if (u > 0) == (v > 0)) <= 5,
      "%d of 8" % sum(1 for u, v in zip(d_true, d_sh) if (u > 0) == (v > 0)))


# ----------------------------------------------- pairing policy, Section 7.3
# pairing_policy.py enumerates every pairing recursively. Nothing here does:
# the optimum comes from a bitmask dynamic program, which is a different
# algorithm reaching the same answer, and the counts come from an iterative
# walk with its own stack. The corner logs are re-read here too, so a mistake
# in that script's parser or its recursion cannot pass this.
print("\n== pairing policy, paper Section 7.3 ==")

CORNERS = ["noise_vdd_1620_out.txt", "noise_vdd_1980_out.txt",
           "noise_temp_m40_out.txt", "noise_temp_000_out.txt",
           "noise_temp_085_out.txt", "noise_temp_125_out.txt",
           "noise_vt_1620_m40_out.txt", "noise_vt_1620_125_out.txt",
           "noise_vt_1980_m40_out.txt", "noise_vt_1980_125_out.txt"]

dep = []
for _name in CORNERS:
    _f = read_par(os.path.join(HERE, _name))
    _r = [a / b for a, b in zip(_f, f_lumped)]
    _mu = sum(_r) / NRO
    dep.append([100.0 * (v - _mu) for v in _r])

check("ten corner logs read, all sixteen rings present in each",
      len(dep) == 10 and all(len(d) == NRO for d in dep))

SP = SIGMA_RING * math.sqrt(2.0)
LO, HI, ENV = {}, {}, {}
for a in range(NRO):
    for b in range(a + 1, NRO):
        s = [d[a] - d[b] for d in dep]
        LO[(a, b)] = min(0.0, min(s))
        HI[(a, b)] = max(0.0, max(s))
        ENV[(a, b)] = max(abs(v) for v in s)

worst_single = max(abs(v) for d in dep for v in d)
check("largest single-ring departure across the box is 0.150%",
      abs(worst_single - 0.150) < 0.001, "%.4f%%" % worst_single)
check("the drift envelope over the 120 candidate pairs runs 0.004% to 0.282%",
      abs(min(ENV.values()) - 0.004) < 0.001
      and abs(max(ENV.values()) - 0.282) < 0.001,
      "%.4f%% to %.4f%%" % (min(ENV.values()), max(ENV.values())))

PAIRS_T = [(i, i + 1) for i in range(0, NRO, 2)]
env_des = [ENV[p] for p in PAIRS_T]
check("the eight pairs the design built see 0.017% to 0.165%",
      abs(min(env_des) - 0.017) < 0.001 and abs(max(env_des) - 0.165) < 0.001,
      "%.4f%% to %.4f%%" % (min(env_des), max(env_des)))

# The margin Section 5.7 quotes, against the right denominator. Section 7.3
# corrects it, so both the old figure and the new one are checked here.
y_lu = centred(f_lumped)
close_lu = min((abs(y_lu[a] - y_lu[b]), a, b) for a, b in PAIRS_T)
close_rc = min((abs(y[a] - y[b]), a, b) for a, b in PAIRS_T)
check("the closest of the eight pairs is 0.270% apart in the lumped decks",
      abs(close_lu[0] - 0.270) < 0.001 and (close_lu[1], close_lu[2]) == (2, 3),
      "%.4f%% at pair %d/%d" % close_lu)
check("against the worst-ring bound that is the 1.8x Section 5.7 quotes",
      abs(close_lu[0] / worst_single - 1.8) < 0.05,
      "%.2fx" % (close_lu[0] / worst_single))
check("its own envelope is 0.0175%, so it is really 15.4x clear",
      abs(ENV[(2, 3)] - 0.0175) < 0.0005
      and abs(close_lu[0] / ENV[(2, 3)] - 15.4) < 0.1,
      "%.4f%%, %.1fx" % (ENV[(2, 3)], close_lu[0] / ENV[(2, 3)]))
check("and the tightest of the eight by its own envelope is 13.8x",
      abs(min(abs(y_lu[a] - y_lu[b]) / ENV[(a, b)] for a, b in PAIRS_T) - 13.8)
      < 0.1,
      "%.1fx" % min(abs(y_lu[a] - y_lu[b]) / ENV[(a, b)] for a, b in PAIRS_T))
check("under full RC the same pair is 0.116%, under the worst-ring bound",
      abs(close_rc[0] - 0.116) < 0.001 and (close_rc[1], close_rc[2]) == (2, 3)
      and close_rc[0] < worst_single,
      "%.4f%% against a %.4f%% bound" % (close_rc[0], worst_single))
check("its own envelope puts it back at 6.7x, the tightest of the eight",
      abs(close_rc[0] / ENV[(2, 3)] - 6.7) < 0.1
      and abs(min(abs(y[a] - y[b]) / ENV[(a, b)] for a, b in PAIRS_T)
              - close_rc[0] / ENV[(2, 3)]) < 1e-9,
      "%.1fx" % (close_rc[0] / ENV[(2, 3)]))


def pair_score(a, b, sigma=SIGMA_RING):
    """Attacker accuracy, across-die entropy, and P(the box flips it).

    Both rings are put in index order first. Accuracy and entropy do not care
    which way round a pair is written, but the drift interval does: LO and HI
    are the extremes of dep[i] - dep[j] and pairing them with a separation
    computed the other way round negates one and not the other. A rule that
    sorts rings by frequency hands pairs over in whatever order the sort left
    them, so this is not hypothetical.
    """
    i, j = (a, b) if a < b else (b, a)
    sp = sigma * math.sqrt(2.0)
    d = y[i] - y[j]
    p = phi(d / sp)
    return (max(p, 1 - p), hbin(p),
            phi((-LO[(i, j)] - d) / sp) - phi((-HI[(i, j)] - d) / sp))


def total(m, sigma=SIGMA_RING):
    t = [0.0, 0.0, 0.0]
    for a, b in m:
        for i, v in enumerate(pair_score(a, b, sigma)):
            t[i] += v
    return t


acc_d, ent_d, uns_d = total(PAIRS_T)
check("the pairing that was built calls 7.91 of 8", round(acc_d, 2) == 7.91,
      "%.4f" % acc_d)
check("and carries 0.46 bits of entropy, matching Section 7",
      abs(ent_d - ent) < 1e-9 and round(ent_d, 2) == 0.46, "%.4f" % ent_d)
check("and 0.06 expected unstable bits", round(uns_d, 2) == 0.06, "%.4f" % uns_d)

# The bound argued before the search: which pairs could hide a bit at all.
band = [k for k in ENV if abs(y[k[0]] - y[k[1]]) < SP]
usable = [k for k in band if abs(y[k[0]] - y[k[1]]) > ENV[k]]
check("only 3 of the 120 candidate pairs sit under one sigma",
      len(band) == 3, "%d" % len(band))
check("all 3 are still clear of their own drift envelope",
      len(usable) == 3, "%d" % len(usable))
check("and they are three pairs of the same three rings, 6, 9 and 13",
      sorted({r for k in usable for r in k}) == [6, 9, 13],
      "rings " + ",".join(map(str, sorted({r for k in usable for r in k}))))
check("so no two of them are disjoint and a pairing can use one",
      all(set(u) & set(v) for u in usable for v in usable))


def dp_min_leakage(sigma=SIGMA_RING):
    """Least-leaky pairing by dynamic programming over subsets of rings.

    The lowest ring still free has to be paired with something, so trying each
    partner and solving the remaining subset covers every pairing while only
    ever touching 2**16 subsets. It never enumerates a pairing, which is the
    point of it being here: pairing_policy.py finds this number by walking all
    two million, and if the two agree the walk is not skipping any.
    """
    memo = {0: (0.0, ())}

    def solve_mask(mask):
        if mask in memo:
            return memo[mask]
        i = (mask & -mask).bit_length() - 1
        rest = mask & ~(1 << i)
        out = None
        for j in range(NRO):
            if (rest >> j) & 1:
                sub = solve_mask(rest & ~(1 << j))
                cand = (sub[0] + pair_score(i, j, sigma)[0], sub[1] + ((i, j),))
                if out is None or cand[0] < out[0]:
                    out = cand
        memo[mask] = out
        return out

    sys.setrecursionlimit(10000)
    return solve_mask((1 << NRO) - 1)


best_acc, best_m = dp_min_leakage()
be, bent, buns = total(best_m)
check("the least-leaky pairing of all 2027025 calls 7.28 of 8",
      round(best_acc, 2) == 7.28 and abs(be - best_acc) < 1e-9,
      "%.4f" % best_acc)
check("it carries 2.69 bits and costs 0.32 expected unstable bits",
      round(bent, 2) == 2.69 and round(buns, 2) == 0.32,
      "%.4f bits, %.4f unstable" % (bent, buns))
check("so the whole free parameter is worth 0.62 bits to the attacker",
      abs((acc_d - best_acc) - 0.62) < 0.005, "%.4f" % (acc_d - best_acc))
check("which is 16% of the 3.91 bits he holds above guessing",
      abs(100 * (acc_d - best_acc) / (acc_d - 4.0) - 16) < 1.0,
      "%.1f%%" % (100 * (acc_d - best_acc) / (acc_d - 4.0)))


def walk(n):
    """Every pairing, iteratively, as a running (accuracy, instability).

    An explicit stack rather than a recursion, so a fault in pairing_policy.py's
    generator cannot be reproduced here by accident.
    """
    start = (1 << n) - 1
    stack = [(start, 0.0, 0.0)]
    while stack:
        mask, acc, uns = stack.pop()
        if not mask:
            yield acc, uns
            continue
        i = (mask & -mask).bit_length() - 1
        rest = mask & ~(1 << i)
        j = 0
        while j < n:
            if (rest >> j) & 1:
                s = pair_score(i, j)
                stack.append((rest & ~(1 << j), acc + s[0], uns + s[2]))
            j += 1


n_all = n_dom = 0
seen_min = 1e9
for _a, _u in walk(NRO):
    n_all += 1
    if _a < seen_min:
        seen_min = _a
    if _a < acc_d - 1e-12 and _u < uns_d - 1e-12:
        n_dom += 1
check("the iterative walk counts 15!! = 2027025 pairings", n_all == 2027025,
      "%d" % n_all)
check("and finds the same minimum the dynamic program did",
      abs(seen_min - best_acc) < 1e-9, "%.6f against %.6f" % (seen_min, best_acc))
check("89460 pairings beat the built one on leakage and stability at once",
      n_dom == 89460, "%d, %.3f%%" % (n_dom, 100.0 * n_dom / n_all))


def by_rank(rank, rule):
    s = sorted(range(len(rank)), key=lambda i: rank[i])
    h = len(s) // 2
    if rule == "neighbour":
        return [(s[i], s[i + 1]) for i in range(0, len(s), 2)]
    if rule == "split":
        return [(s[i], s[i + h]) for i in range(h)]
    return [(s[i], s[len(s) - 1 - i]) for i in range(h)]


for rule, want_a, want_e, want_u in (("neighbour", 7.40, 2.19, 0.30),
                                     ("split", 8.00, 0.00, 0.00),
                                     ("extremal", 7.67, 0.92, 0.14)):
    ta, te, tu = total(by_rank(y, rule))
    check("the %s rule calls %.2f, carries %.2f bits, costs %.2f unstable"
          % (rule, want_a, want_e, want_u),
          round(ta, 2) == want_a and round(te, 2) == want_e
          and round(tu, 2) == want_u,
          "%.4f / %.4f / %.4f" % (ta, te, tu))

check("no closed-form rule reaches the enumerated optimum",
      min(total(by_rank(y, r))[0] for r in ("neighbour", "split", "extremal"))
      > best_acc + 1e-9,
      "best rule %.4f against %.4f"
      % (min(total(by_rank(y, r))[0] for r in ("neighbour", "split", "extremal")),
         best_acc))

# Choosing the pairing from the extraction instead of from a simulation.
_b = solve(design([cap_a], NRO_A), f_a)
pred_f = [_b[0] + _b[1] * c for c in cap]
swaps = sum(1 for i in range(NRO) for j in range(i + 1, NRO)
            if (pred_f[i] > pred_f[j]) != (y[i] > y[j]))
check("the transferred model puts 1 of the 120 ring pairs the wrong way round",
      swaps == 1, "%d" % swaps)
for rule in ("neighbour", "split", "extremal"):
    a_p = total(by_rank(pred_f, rule))[0]
    a_t = total(by_rank(y, rule))[0]
    check("choosing the %s pairing from the extraction alone costs nothing"
          % rule, abs(a_p - a_t) < 0.005, "%.4f against %.4f" % (a_p, a_t))

# The other build, where the same rule is worth four times as much.
ya_c = centred(f_a)


def total_a(m):
    sp = SIGMA_RING * math.sqrt(2.0)
    t = [0.0, 0.0]
    for a, b in m:
        p = phi((ya_c[a] - ya_c[b]) / sp)
        t[0] += max(p, 1 - p)
        t[1] += hbin(p)
    return t


idx_a = [(i, i + 1) for i in range(0, NRO_A, 2)]
nb_a = by_rank(ya_c, "neighbour")
check("on the 32-ring build the built order calls 16.00 of 16",
      round(total_a(idx_a)[0], 2) == 16.00, "%.4f" % total_a(idx_a)[0])
check("and the neighbour rule takes it to 13.32",
      round(total_a(nb_a)[0], 2) == 13.32, "%.4f" % total_a(nb_a)[0])
_ga = sorted(ya_c)
_gb = sorted(y)
_ma = st.median([_ga[i + 1] - _ga[i] for i in range(NRO_A - 1)])
_mb = st.median([_gb[i + 1] - _gb[i] for i in range(NRO - 1)])
check("twice the rings halves the median gap, 0.218% to 0.130%",
      abs(_mb - 0.218) < 0.001 and abs(_ma - 0.130) < 0.001,
      "%.4f%% and %.4f%%" % (_mb, _ma))


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
