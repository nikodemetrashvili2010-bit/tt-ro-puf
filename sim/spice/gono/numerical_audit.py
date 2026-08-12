#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Do arithmetic, precision or sample size change any conclusion in the paper?

Every result in Sections 6 and 7 is a least-squares fit and a normal integral
run over sixteen numbers. That is a small enough calculation to be wrong in
quiet ways, and none of the existing checks look at the calculation itself. They
check that the inputs are the right inputs and that the outputs match what the
prose says. Both would pass on a badly conditioned solve.

Five things get audited here, in the order that they would embarrass me.

  1  The solver. compensation.py forms the normal equations, which squares the
     condition number of the design matrix. For the quadratic position surface,
     built from raw micrometre coordinates and their squares, that lands near
     the edge of double precision. This refits everything with Householder QR,
     which never forms X'X, and refits the position surfaces on centred and on
     standardised coordinates. If the position result is a conditioning artefact
     it will move.

  2  Input precision. rc_validation.csv stores frequencies to two decimals. This
     redraws every ring inside its rounding interval a few thousand times and
     asks whether the totals move and whether any bit changes sign.

  3  The numerical floor of the simulation itself. The lumped decks are handed
     one capacitance per net and nothing else varies, so a capacitance fit
     against them is recovering its own input and whatever residual survives
     bounds the per-ring numerical error plus the nonlinearity of frequency in
     capacitance. That is a measured ceiling, and the results have to sit well
     above it. Worth doing because the two frequency sets do not share a
     timestep: gen_dualarm_decks.py writes .tran 5p and gen_rc_decks.py writes
     .tran 1p.

  4  Selection. Section 6 reports the best of six correctors, chosen after
     seeing how each did. Leave-one-out does not charge for that choice. A
     nested loop does: the outer fold holds out a ring, the inner fold picks the
     corrector from the other fifteen, and the winner is scored on the ring
     neither of them saw.

  5  Sample size. Eight pairs is a very small response and the entropy total is
     a sum over all eight. Resampling the pairs says how much of the headline
     belongs to this block and how much to the sample, which turns out to matter
     more than anything above.

Stdlib only, same as the rest of the suite, and every random draw is seeded so
two runs agree. Ends by asserting the conclusions it reaches, so that a future
change which breaks one of them fails here.

Run: python3 numerical_audit.py
"""

import math
import os
import random
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import compensation as cp  # noqa: E402
import compensated_bits as cb  # noqa: E402

NRO = 16
SIGMA = cb.SIGMA_RING
ROUND_HALF = 0.005      # rc_validation.csv carries two decimals of MHz
DRAWS = 4000
BOOT = 20000

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS  " + name + (("   [%s]" % detail) if detail else ""))
    else:
        fail += 1
        print("FAIL  " + name + (("   [%s]" % detail) if detail else ""))


# --------------------------------------------------------------- linear algebra
def qr_lstsq(X, y):
    """Least squares by Householder QR. Never forms X'X, so the solve sees the
    condition number of X rather than its square. Written out rather than
    imported so that it shares no code with compensation.py's solver."""
    m, n = len(X), len(X[0])
    A = [row[:] for row in X]
    b = list(y)
    for k in range(n):
        norm = math.sqrt(sum(A[i][k] ** 2 for i in range(k, m)))
        if norm == 0.0:
            continue
        if A[k][k] > 0:
            norm = -norm
        v = [0.0] * m
        for i in range(k, m):
            v[i] = A[i][k]
        v[k] -= norm
        vtv = sum(v[i] ** 2 for i in range(k, m))
        if vtv == 0.0:
            continue
        for j in range(k, n):
            s = sum(v[i] * A[i][j] for i in range(k, m)) * 2.0 / vtv
            for i in range(k, m):
                A[i][j] -= s * v[i]
        s = sum(v[i] * b[i] for i in range(k, m)) * 2.0 / vtv
        for i in range(k, m):
            b[i] -= s * v[i]
    beta = [0.0] * n
    for i in range(n - 1, -1, -1):
        acc = b[i] - sum(A[i][j] * beta[j] for j in range(i + 1, n))
        beta[i] = acc / A[i][i]
    return beta, [abs(A[i][i]) for i in range(n)]


def design(cols, idx):
    return [[1.0] + [c[i] for c in cols] for i in idx]


def qr_loo(cols, y):
    out = []
    for h in range(len(y)):
        keep = [i for i in range(len(y)) if i != h]
        beta, _ = qr_lstsq(design(cols, keep), [y[i] for i in keep])
        row = design(cols, [h])[0]
        out.append(y[h] - sum(b * v for b, v in zip(beta, row)))
    return out


def col_spread(cols):
    """Ratio of the largest to the smallest column norm of the design matrix.
    This is what makes the normal equations dangerous: X'X multiplies these
    together, so a design whose columns differ by 10^k in length hands the solve
    a matrix spanning 10^2k. It is not the condition number and is not claimed
    to be one; it is the part of the conditioning that comes from scaling, and
    it is the part that a stdlib script can compute honestly."""
    X = design(cols, range(NRO))
    norms = [math.sqrt(sum(row[j] ** 2 for row in X)) for j in range(len(X[0]))]
    return max(norms) / min(norms)


def qr_diag_spread(cols):
    """Ratio of largest to smallest |R_ii| from the Householder QR. Each column
    is orthogonalised against the ones column before its diagonal is taken, so
    this reports the conditioning the QR path actually works with rather than
    the conditioning of the raw matrix."""
    _, diag = qr_lstsq(design(cols, range(NRO)), [0.0] * NRO)
    return max(diag) / min(diag)


def pearson(a, b):
    ma, mb = st.fmean(a), st.fmean(b)
    return (sum((x - ma) * (yy - mb) for x, yy in zip(a, b))
            / math.sqrt(sum((x - ma) ** 2 for x in a)
                        * sum((yy - mb) ** 2 for yy in b)))


def fisher_ci(r, alpha=0.05):
    """Interval on a correlation through Fisher's z transform."""
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(NRO - 3)
    c = st.NormalDist().inv_cdf(1 - alpha / 2)
    return math.tanh(z - c * se), math.tanh(z + c * se)


def pval(r):
    z = abs(0.5 * math.log((1 + r) / (1 - r))) * math.sqrt(NRO - 3)
    return 2 * (1 - st.NormalDist().cdf(z))


def scale(v):
    m = st.fmean(v)
    s = st.pstdev(v)
    return [(x - m) / s for x in v]


def centre(v):
    m = st.fmean(v)
    return [x - m for x in v]


def quad_of(x, yy):
    return [x, yy, [a * a for a in x], [a * a for a in yy],
            [a * b for a, b in zip(x, yy)]]


def main():
    feats = cp.spef_features(cp.CUR_SPEF, NRO)
    C = [f[0] for f in feats]
    R = [f[1] for f in feats]
    E = [f[2] for f in feats]
    xs, ys, f_rc = cp.read_rc()
    f_rc = list(f_rc)
    f_lum = cp.read_shipped_lumped()[2]
    y = cp.centred(f_rc)
    base = st.pstdev(y)

    cands = [("position, quadratic", quad_of(xs, ys)),
             ("position, linear", [xs, ys]),
             ("ring resistance", [R]),
             ("Elmore sum(R*C)", [E]),
             ("ring capacitance", [C]),
             ("capacitance and resistance", [C, R])]

    # ------------------------------------------------------------- 1 solver
    print("== 1. the solver ==\n")
    print("  column spread is max over min column norm of the design matrix.")
    print("  The normal equations multiply those together, so the solve sees")
    print("  roughly its square; the QR path does not form that product.\n")
    print("  %-28s %11s %11s %12s %12s %10s"
          % ("corrector", "col spread", "QR spread", "normal eqns",
             "Householder", "diff"))
    worst = 0.0
    for lbl, cols in cands:
        a = cp.loo_rms(cols, y)
        r = qr_loo(cols, y)
        b = math.sqrt(sum(v * v for v in r) / NRO)
        worst = max(worst, abs(a - b))
        print("  %-28s %11.1e %11.1e %11.6f%% %11.6f%% %10.0e"
              % (lbl, col_spread(cols), qr_diag_spread(cols), a, b, abs(a - b)))
    print()
    check("the two solvers agree to better than 1e-6 points", worst < 1e-6,
          "worst %.1e" % worst)
    check("the quadratic surface is the worst-scaled design in the set",
          col_spread(quad_of(xs, ys)) == max(col_spread(c) for _, c in cands),
          "column spread %.1e, so the normal equations see about %.0e"
          % (col_spread(quad_of(xs, ys)), col_spread(quad_of(xs, ys)) ** 2))

    print("\n  Position refitted on rescaled coordinates. A least-squares fit is")
    print("  invariant to rescaling its columns, so if these move, the answer")
    print("  was arithmetic rather than data.\n")
    print("  %-34s %11s %11s %12s"
          % ("coordinates", "col spread", "QR spread", "leave-one-out"))
    variants = []
    for lbl, x2, y2 in (("raw micrometres, as the repo has it", xs, ys),
                        ("centred on the array", centre(xs), centre(ys)),
                        ("centred and scaled to unit sd", scale(xs), scale(ys))):
        cols = quad_of(x2, y2)
        r = math.sqrt(sum(v * v for v in qr_loo(cols, y)) / NRO)
        variants.append(r)
        print("  %-34s %11.1e %11.1e %11.5f%%"
              % (lbl, col_spread(cols), qr_diag_spread(cols), r))
    print()
    check("rescaling the coordinates changes nothing to five decimals",
          max(variants) - min(variants) < 1e-5,
          "spread %.1e" % (max(variants) - min(variants)))
    check("position is worse than no correction under every conditioning",
          all(v > base for v in variants),
          "%.3f%% to %.3f%% against %.3f%%" % (min(variants), max(variants), base))

    # --------------------------------------------------------- 2 input precision
    print("\n== 2. input precision ==\n")
    pair_round = ROUND_HALF * math.sqrt(2.0) / st.fmean(f_rc) * 100
    print("  frequencies are stored to two decimals, so +-%.4f MHz per ring,"
          % ROUND_HALF)
    print("  which is +-%.4f%% on a pair difference.\n" % pair_round)
    loo_ref = cb.loo_residuals([C, R], y)
    sign_un = [r[0] > 0 for r in cb.score(y, SIGMA)]
    sign_co = [r[0] > 0 for r in cb.score(loo_ref, SIGMA)]
    rnd = random.Random(20260812)
    spread = {k: [] for k in ("eu", "au", "ec", "ac")}
    flips = 0
    for _ in range(DRAWS):
        f = [v + rnd.uniform(-ROUND_HALF, ROUND_HALF) for v in f_rc]
        yy = cp.centred(f)
        rr = cb.loo_residuals([C, R], yy)
        su, sc = cb.score(yy, SIGMA), cb.score(rr, SIGMA)
        tu, tc = cb.totals(su), cb.totals(sc)
        spread["eu"].append(tu[0])
        spread["au"].append(tu[1])
        spread["ec"].append(tc[0])
        spread["ac"].append(tc[1])
        flips += sum(1 for a, b in zip(sign_un, su) if a != (b[0] > 0))
        flips += sum(1 for a, b in zip(sign_co, sc) if a != (b[0] > 0))
    print("  %-26s %8s   %s" % ("quantity", "reported", "range over %d draws" % DRAWS))
    for key, lbl, point in (("eu", "entropy, as built", cb.totals(cb.score(y, SIGMA))[0]),
                            ("au", "guessed, as built", cb.totals(cb.score(y, SIGMA))[1]),
                            ("ec", "entropy, compensated", cb.totals(cb.score(loo_ref, SIGMA))[0]),
                            ("ac", "guessed, compensated", cb.totals(cb.score(loo_ref, SIGMA))[1])):
        v = spread[key]
        print("  %-26s %8.3f   %.3f to %.3f" % (lbl, point, min(v), max(v)))
    print()
    check("rounding moves no total by as much as a tenth of a bit",
          max(max(spread[k]) - min(spread[k]) for k in ("eu", "ec")) < 0.1,
          "worst %.4f bits" % max(max(spread[k]) - min(spread[k])
                                  for k in ("eu", "ec")))
    check("rounding flips no bit in %d draws" % (DRAWS * 16), flips == 0,
          "%d flips" % flips)

    # ------------------------------------------------- 3 the simulation's floor
    print("\n== 3. the numerical floor of the simulation ==\n")
    y_l = cp.centred(f_lum)
    ceiling = math.sqrt(sum(v * v for v in qr_loo([C], y_l)) / NRO)
    resid = math.sqrt(sum(v * v for v in loo_ref) / NRO)
    print("  gen_dualarm_decks.py writes .tran 5p and gen_rc_decks.py .tran 1p,")
    print("  so the two frequency sets do not share a numerical resolution. The")
    print("  lumped set is the one that can be bounded, and it is the coarser.\n")
    print("  ceiling on per-ring numerical error, 5 ps set   %.4f%%" % ceiling)
    print("  on a pair difference                           %.4f%%"
          % (ceiling * math.sqrt(2)))
    print("  compensated residual reported in Section 7.2   %.4f%%   %.1fx clear"
          % (resid, resid / ceiling))
    print("  uncorrected layout spread                      %.4f%%   %.0fx clear"
          % (base, base / ceiling))
    pc = ceiling * math.sqrt(2)
    print()
    for lbl, f in (("lumped, 5 ps", f_lum), ("full RC, 1 ps", f_rc)):
        m = st.fmean(f)
        d = sorted(abs((f[a] - f[b]) / m * 100) for a, b in cb.PAIRS)
        print("  %-14s closest two pairs %.3f%% and %.3f%%, or %.1fx and %.1fx the "
              "pair ceiling" % (lbl, d[0], d[1], d[0] / pc, d[1] / pc))
    print()
    check("the compensated residual is not numerical noise", resid > 3 * ceiling,
          "%.4f%% against a %.4f%% ceiling" % (resid, ceiling))
    check("every pair separation clears the pair ceiling in both models",
          all(abs((f[a] - f[b]) / st.fmean(f) * 100) > pc
              for f in (f_lum, f_rc) for a, b in cb.PAIRS))
    thin = min(abs((f_rc[a] - f_rc[b]) / st.fmean(f_rc) * 100) for a, b in cb.PAIRS)
    check("the closest full-RC pair clears it by less than 3x, so say so",
          thin / pc < 3.0, "%.1fx" % (thin / pc))

    # ------------------------------------------------------------ 4 selection
    print("\n== 4. paying for the choice of corrector ==\n")
    picks, nested = {}, []
    for h in range(NRO):
        pool = [i for i in range(NRO) if i != h]
        best = min(cands, key=lambda kv: math.sqrt(
            sum(v * v for v in [
                y[j] - sum(b * v2 for b, v2 in zip(
                    qr_lstsq(design(kv[1], [i for i in pool if i != j]),
                             [y[i] for i in pool if i != j])[0],
                    design(kv[1], [j])[0]))
                for j in pool]) / len(pool)))
        picks[best[0]] = picks.get(best[0], 0) + 1
        beta, _ = qr_lstsq(design(best[1], pool), [y[i] for i in pool])
        nested.append(y[h] - sum(b * v for b, v in
                                 zip(beta, design(best[1], [h])[0])))
    nested_rms = math.sqrt(sum(v * v for v in nested) / NRO)
    print("  the inner fold chose: "
          + ", ".join("%s x%d" % (k, v) for k, v in picks.items()))
    print("  flat leave-one-out on cap+res    %.4f%%   removes %+.1f%%"
          % (resid, (1 - resid / base) * 100))
    print("  nested, charged for the choice   %.4f%%   removes %+.1f%%"
          % (nested_rms, (1 - nested_rms / base) * 100))
    e_flat = cb.totals(cb.score(loo_ref, SIGMA))
    e_nest = cb.totals(cb.score(nested, SIGMA))
    print("  entropy %.2f -> %.2f of 8, guessed %.2f -> %.2f of 8"
          % (e_flat[0], e_nest[0], e_flat[1], e_nest[1]))
    print()
    check("selection costs under half a point of the removed fraction",
          abs((1 - resid / base) * 100 - (1 - nested_rms / base) * 100) < 0.5,
          "%.2f points" % abs((1 - resid / base) * 100
                              - (1 - nested_rms / base) * 100))
    check("Section 6's headline survives being charged for the choice",
          round((1 - nested_rms / base) * 100) == 89,
          "%.1f%%" % ((1 - nested_rms / base) * 100))
    check("so does Section 7.2's", abs(e_nest[0] - e_flat[0]) < 0.1,
          "%.3f against %.3f bits" % (e_nest[0], e_flat[0]))

    # The correctors are not the only thing looked at more than once. Section 6
    # also reports correlations against x, y and radius under both parasitic
    # models, and Section 5 reports the capacitance correlation. Declare that
    # family and correct it, with intervals rather than bare p-values.
    print("\n  The correlations are a second family. Eight of them, declared here")
    print("  rather than after the fact, Holm-corrected at 0.05, n=%d.\n" % NRO)
    mx, my = st.fmean(xs), st.fmean(ys)
    rad = [math.hypot(a - mx, b - my) for a, b in zip(xs, ys)]
    fam = []
    for mdl, f in (("full RC", f_rc), ("lumped", f_lum)):
        for nm, v in (("x", xs), ("y", ys), ("radius", rad)):
            fam.append(("%s vs %s" % (mdl, nm), pearson(v, f)))
        fam.append(("%s vs ring capacitance" % mdl, pearson(C, f)))
    m = len(fam)
    order = sorted(range(m), key=lambda i: pval(fam[i][1]))
    print("  %-30s %8s %10s %22s  %s"
          % ("test", "r", "raw p", "95% interval on r", "Holm at 0.05"))
    still = True
    rejected = []
    for k, i in enumerate(order):
        nm, r = fam[i]
        p = pval(r)
        if p >= 0.05 / (m - k):
            still = False
        if still:
            rejected.append(nm)
        lo, hi = fisher_ci(r)
        print("  %-30s %+8.4f %10.1e   %+7.3f to %+7.3f  %s"
              % (nm, r, p, lo, hi, "reject" if still else "not rejected"))
    print()
    check("only the capacitance correlations survive the correction",
          sorted(rejected) == sorted(["full RC vs ring capacitance",
                                      "lumped vs ring capacitance"]),
          ", ".join(rejected))
    check("no position correlation is significant even before correcting",
          all(pval(r) > 0.05 for nm, r in fam if "capacitance" not in nm),
          "smallest p %.2f" % min(pval(r) for nm, r in fam
                                  if "capacitance" not in nm))
    widest = max((abs(hi - lo), nm) for nm, r in fam
                 if "capacitance" not in nm
                 for lo, hi in [fisher_ci(r)])
    check("but the position intervals are too wide to call position absent",
          widest[0] > 0.8, "%s spans %.2f" % (widest[1], widest[0]))

    # ------------------------------------------------------------ 5 the sample
    print("\n== 5. eight pairs is the real uncertainty ==\n")
    un = cb.score(y, SIGMA)
    co = cb.score(loo_ref, SIGMA)

    def resample(vals, seed):
        rn = random.Random(seed)
        k = len(vals)
        tot = sorted(sum(rn.choice(vals) for _ in range(k)) for _ in range(BOOT))
        return tot[int(0.025 * BOOT)], tot[int(0.975 * BOOT)]

    print("  The eight pairs are one draw of what this flow produces, so they")
    print("  can be resampled. %d draws, percentile interval:\n" % BOOT)
    print("  %-26s %7s   %s" % ("quantity", "point", "95% over the pairs"))
    out = {}
    for nm, vals, idx, seed in (("entropy, as built", un, 2, 1),
                                ("entropy, compensated", co, 2, 2),
                                ("guessed, as built", un, 3, 3),
                                ("guessed, compensated", co, 3, 4)):
        v = [r[idx] for r in vals]
        lo, hi = resample(v, seed)
        out[nm] = (sum(v), lo, hi)
        print("  %-26s %7.2f   %5.2f to %5.2f" % (nm, sum(v), lo, hi))
    print("\n  against the two other intervals on the same quantity:")
    print("    mismatch sampling interval, compensated entropy   2.36 to 3.67")
    print("    stored input precision, from section 2 above      %.3f wide"
          % (max(spread["ec"]) - min(spread["ec"])))
    print()
    ew = out["entropy, compensated"][2] - out["entropy, compensated"][1]
    check("the pair sample is a wider interval than the mismatch assumption",
          ew > (3.67 - 2.36), "%.2f bits against 1.31" % ew)
    check("the attacker number survives resampling and the entropy does not",
          out["guessed, compensated"][1] > 6.0
          and out["entropy, compensated"][1] < 2.0,
          "guessed >= %.2f, entropy >= %.2f"
          % (out["guessed, compensated"][1], out["entropy, compensated"][1]))
    check("even the worst resample leaves the attacker far above a coin flip",
          out["guessed, compensated"][1] > 5.0,
          "%.2f of 8 against 4.00" % out["guessed, compensated"][1])

    print("\n== what this changes ==\n")
    print("  Nothing in Sections 6 and 7 is an artefact of the arithmetic. The")
    print("  worst-scaled design is the position surface, at a column spread of")
    print("  %.0e which the normal equations turn into about %.0e, and it returns"
          % (col_spread(quad_of(xs, ys)), col_spread(quad_of(xs, ys)) ** 2))
    print("  the same %.5f%% under Householder QR and under two rescalings that"
          % variants[0])
    print("  take the spread down to %.1f. Position fails on the data, not on the"
          % col_spread(quad_of(scale(xs), scale(ys))))
    print("  solver. Stored precision is far better than it needs to be, no bit")
    print("  changes sign under it, and the simulation's own numerical floor")
    print("  sits %.0fx under the smallest figure quoted against it." % (resid / ceiling))
    print()
    print("  What does change is which number to lead with. Across all three")
    print("  sources of uncertainty the attacker figure runs %.2f of 8 at worst"
          % out["guessed, compensated"][1])
    print("  against %.2f reported, and never approaches the %.2f a guess would"
          % (out["guessed, compensated"][0], len(cb.PAIRS) / 2))
    print("  get. The compensated entropy total runs %.2f to %.2f over the same"
          % (out["entropy, compensated"][1], out["entropy, compensated"][2]))
    print("  resample and cannot carry two decimal places. Lead with the attack,")
    print("  report the entropy as an interval, and say which interval it is.")
    print()
    print("  One thing to fix rather than report: the two frequency sets are")
    print("  simulated at different timesteps, 5 ps lumped against 1 ps full RC.")
    print("  Nothing here depends on it, because every claim that matters uses")
    print("  the 1 ps set and the 5 ps floor is measured and small. But the")
    print("  closest full-RC pair clears that floor by only %.1fx, and that is"
          % (thin / pc))
    print("  the pair Section 7.1 says holds most of the surviving entropy.")
    print("  Re-running the lumped decks at 1 ps would retire the question.")

    print("\n%d passed, %d failed" % (ok, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
