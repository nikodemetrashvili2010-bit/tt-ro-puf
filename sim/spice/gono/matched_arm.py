#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Does matching remove the exploitable structure, or only shrink it?

Section 6 asks whether Arm A's layout term can be predicted and finds that two
numbers out of the SPEF get 89.5% of it. Section 8 reports that Arm B's sixteen
instances spread 0.0025% peak to peak at tt against Arm A's 5.84%. Those are
answers to different questions and the second one is not, on its own, a
countermeasure claim. A term can be four orders of magnitude smaller and still
be a fingerprint; what makes a fingerprint useful is that somebody can compute
it, not that it is large.

So this runs Section 6's question against Arm B, and then Section 7's.

`predictable_bits.py` currently disposes of Arm B in one sentence: sixteen
copies of one macro have the same internal layout, so the routing offset is zero
and all eight bits are coin flips. That is an assumption, and it is the
convenient one. It is also not quite true, because the instances are not
identical at the top level -- each carries its own enable route and its own
output route, and those span 1.0 to 12.8 fF and 2.9 to 29.5 fF respectively.
The per-instance run of hardware item 8 simulated all sixteen with the routes
they actually have, at three corners, so the assumption can be replaced with a
measurement.

Four things get asked of that data:

  is it a loading effect     a passive route can add capacitance and nothing
                             else, and adding capacitance to a ring cannot make
                             it faster. Count how many instances read faster
                             than the reference ring, which carries no top-level
                             route at all. If a good fraction do, the spread is
                             not the routes.
  is it predictable          the same leave-one-out scoring Section 6 uses, on
                             the same feature families, plus position. Arm B
                             sits on a regular 4x4 grid, which is the geometry
                             the literature's positional correction was built
                             for, so if a surface is ever going to help it
                             should help here.
  is it stable               a fingerprint keeps its sign. Arm A's eight pairs
                             agree 8 of 8 between the lumped and the full RC
                             model. Ask the same of Arm B across corners.
  what is it worth in bits   entropy and attacker accuracy, exactly as
                             predictable_bits.py computes them for Arm A, with
                             the measured deltas in place of the assumed zero.

The verdict at the end carries the answer. The fourth number is the one that
matters and the first three explain why it comes out where it does.

29 October: --build release asks the same of run 83's routes, which until
then only had the first question asked of them. It reads armb3/, the
release DEF, and works Arm A's corrector out from the release SPEF instead
of quoting the baseline's 89.5%. One answer was new. At tt the enable
route's capacitance goes with frequency at r = -0.805, which survives Holm
over both routes and all three corners, where nothing on the baseline's
routes survived its correction. armb_residual.py took it apart at tt: it
is the solver's, and so is the spread it sits in. ss and ff are the same
kind of deck and were not taken apart. The release text says so and quotes
the runs; the baseline's output is what it was, word for word.

Run: python3 matched_arm.py
     python3 matched_arm.py --build release
     python3 matched_arm.py --selftest    (planted faults, no logs needed)
"""

import argparse
import csv
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import analyze_instance as inst   # noqa: E402  (log reader and Pearson, reused)
import compensation as cp       # noqa: E402  (the solver and the scoring, reused)

NRO = 16
PAIRS = [(i, i + 1) for i in range(0, NRO, 2)]
SIGMA_RING = 0.062                   # percent, sim/spice/mc
SIGMA_LO, SIGMA_HI = 0.051, 0.080    # its sampling interval

CORNERS = ("tt", "ss", "ff")
LOGS = {"tt": "armb_instances_out.txt",
        "ss": "armb_instances_ss_out.txt",
        "ff": "armb_instances_ff_out.txt"}
DEF = os.path.join(PROJ, "dualarm", "build_current",
                   "tt_um_nikodemetrashvili20_ro_puf.def")
PARASITICS = os.path.join(HERE, "instance_parasitics.csv")

# Section 8's published per-instance spreads. If a log is swapped these move and
# every number below is about a different run.
WANT_PTP = {"tt": 0.0025, "ss": 0.0001, "ff": 0.0009}
PTP_TOL = 0.0002

# Arm A, for the comparison lines. Section 6 and Section 7.1.
ARM_A_SD = 1.739
ARM_A_LOO = 0.183
ARM_A_ENTROPY = 0.46
ARM_A_GUESSED = 7.91

# The release build, run 83, with the sixteen run on its own routes on 22
# September in armb3/. The spreads are Section 8.1's for that run, and Arm
# A's bits are Section 7.4's. Arm A's leave-one-out figure on that die is
# not quoted anywhere, so it is worked out here from the release SPEF and
# the full RC table rather than written in.
REL = os.path.join(PROJ, "dualarm", "build_armc")
BUILDS = {
    "baseline": dict(logs=HERE, defn=DEF, parasitics=PARASITICS,
                     want_ptp=WANT_PTP, entropy=ARM_A_ENTROPY,
                     guessed=ARM_A_GUESSED, fixed=6),
    "release": dict(logs=os.path.join(HERE, "armb3"),
                    defn=os.path.join(REL, os.path.basename(DEF)),
                    parasitics=os.path.join(HERE, "armb3",
                                            "instance_parasitics.csv"),
                    want_ptp={"tt": 0.0033, "ss": 0.0001, "ff": 0.0019},
                    entropy=0.07, guessed=7.99, fixed=7,
                    spef=os.path.join(
                        REL, "tt_um_nikodemetrashvili20_ro_puf.nom.spef"),
                    rc=os.path.join(HERE, "rc_validation_3arm.csv")),
}


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def hbin(p):
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def t_two_sided(r, n):
    """p for a Pearson r against zero, n points, from the t distribution.

    Computed from the incomplete beta by its continued fraction rather than
    pulled from a table, so the whole file stays stdlib.
    """
    if abs(r) >= 1.0:
        return 0.0
    df = n - 2
    t = abs(r) * math.sqrt(df / (1.0 - r * r))
    x = df / (df + t * t)
    return betainc(0.5 * df, 0.5, x)


def betainc(a, b, x):
    """Regularised incomplete beta I_x(a, b), Lentz's continued fraction."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbeta) * _cf(a, b, x) / a
    return 1.0 - math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + b * math.log1p(-x) + a * math.log(x)) * _cf(b, a, 1.0 - x) / b


def _cf(a, b, x, itmax=300, eps=3e-16):
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        for num in (m * (b - m) * x / ((qam + m2) * (a + m2)),
                    -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1.0 + num * d
            if abs(d) < tiny:
                d = tiny
            c = 1.0 + num / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            h *= d * c
        if abs(d * c - 1.0) < eps:
            break
    return h


def holm(pairs):
    """Holm-Bonferroni. pairs is [(label, p)], returns [(label, p, p_adj)]."""
    order = sorted(pairs, key=lambda kv: kv[1])
    out, running = [], 0.0
    for i, (label, p) in enumerate(order):
        adj = min(1.0, max(running, p * (len(order) - i)))
        running = adj
        out.append((label, p, adj))
    return out


# ---------------------------------------------------------------- inputs

def macro_positions(path):
    """Placement centroid of each hardened instance, in micrometres.

    The DEF gives the lower-left corner in database units. Every instance is the
    same macro, so a constant offset to the centre would shift all sixteen by the
    same amount and change no fit; the corner is used as it stands.
    """
    pos = {}
    for line in open(path):
        t = line.split()
        if len(t) < 8 or t[0] != "-" or not t[1].startswith("u_rob"):
            continue
        if t[2] != "ro_macro_hard":
            continue
        i = t.index("(")
        pos[int(t[1][5:])] = (int(t[i + 1]) / 1000.0, int(t[i + 2]) / 1000.0)
    if sorted(pos) != list(range(NRO)):
        raise SystemExit("the DEF does not hold sixteen hardened instances, "
                         "found %d" % len(pos))
    return pos


def read_corner(corner, logs=HERE):
    vals = inst.read_log(os.path.join(logs, LOGS[corner]))
    missing = [k for k in range(NRO) if "f_k%02d" % k not in vals]
    if missing or "f_r" not in vals:
        raise SystemExit("%s log is missing %d of the eighteen frequencies; a "
                         "ring that did not oscillate is absent from the log "
                         "rather than zero" % (corner, len(missing) + 1))
    f = [vals["f_k%02d" % k] / 1e6 for k in range(NRO)]
    return f, vals["f_r"] / 1e6, vals["f_c"] / 1e6


def by_period(logs, corner):
    """The sixteen from the period, 20 / tp_kNN, as the corner verifier
    reads them, and the log's own f_kNN, unscaled."""
    vals = inst.read_log(os.path.join(logs, LOGS[corner]))
    return ([20.0 / vals["tp_k%02d" % k] for k in range(NRO)],
            [vals["f_k%02d" % k] for k in range(NRO)])


def arm_a_loo(spef, rc):
    """Section 6's two-feature corrector on one build's Arm A, scored
    leave-one-out against its full RC frequencies, as spread removed."""
    feats = cp.spef_features(spef, NRO)
    rows = list(csv.DictReader(open(rc, newline="")))
    if [int(r["ro"]) for r in rows] != list(range(NRO)):
        raise SystemExit("%s does not list rings 0 to 15 in order" % rc)
    worst = max(abs(f[0] - float(r["ring_cap_fF"]))
                for f, r in zip(feats, rows))
    if worst > 0.011:
        raise SystemExit("the SPEF's loop capacitance is %.4f fF off the RC "
                         "table, so these are not the same nets" % worst)
    c = cp.centred([float(r["rc_MHz"]) for r in rows])
    cols = [[f[0] for f in feats], [f[1] for f in feats]]
    return (1.0 - cp.loo_rms(cols, c) / st.pstdev(c)) * 100.0


# ---------------------------------------------------------------- the report

def baseline_correlations(ouc, cent, out):
    # The one raw correlation that reaches nominal significance on its own is
    # output route capacitance against frequency at ff, which
    # verify_instance_corners.py already records. It is declared here with the
    # other two corners rather than quoted alone.
    out("\nThe one correlation that clears its own t test is output route")
    out("capacitance against frequency at ff. Declared across all three corners:\n")
    raw = []
    for c in CORNERS:
        r = inst.pearson(ouc, cent[c])
        raw.append(("output capacitance against frequency at %s" % c,
                    t_two_sided(r, NRO)))
        out("  %-46s r = %+.3f, p = %.3f"
            % ("output capacitance against frequency at %s" % c, r,
               t_two_sided(r, NRO)))
    out("")
    for label, p, adj in holm(raw):
        out("  %-46s Holm-adjusted = %.3f%s"
            % (label, adj, "" if adj >= 0.05 else "   SIGNIFICANT"))
    out("  At ss the period-derived frequency gives +0.065 instead of +0.053 for")
    out("  the same reason; neither is distinguishable from zero.")
    out("  It does not survive the correction, its sign disagrees with the other")
    out("  two corners, and the effect size behind it is under a fifth of one")
    out("  counter count across the whole 2.89 to 29.46 fF span. Reported anyway,")
    out("  because reading one corner's insignificance as an answer is the")
    out("  mistake that made this table three corners wide in the first place.")


def release_correlations(enc, ouc, cent, rel, out):
    """The release routes' block. Both route capacitances, every corner,
    Holm over the six; then what the tolerance runs in armb3/tol say."""
    fail = []
    out("\nOn these routes the correlation that clears its own t test is the")
    out("enable route's capacitance at tt, not the output's. Both declared, "
        "at")
    out("all three corners:\n")
    raw, r_en = [], {}
    for name, xs in (("enable", enc), ("output", ouc)):
        for c in CORNERS:
            r = inst.pearson(xs, cent[c])
            if name == "enable":
                r_en[c] = r
            label = "%s capacitance against frequency at %s" % (name, c)
            raw.append((label, t_two_sided(r, NRO)))
            out("  %-46s r = %+.3f, p = %.4f"
                % (label, r, t_two_sided(r, NRO)))
    out("")
    sig = []
    for label, p, adj in holm(raw):
        out("  %-46s Holm-adjusted = %.4f%s"
            % (label, adj, "" if adj >= 0.05 else "   SIGNIFICANT"))
        if adj < 0.05:
            sig.append(label)
    want = ["enable capacitance against frequency at tt"]
    if sig != want:
        fail.append("the significant correlations are %s, where the text "
                    "below is written for the enable route at tt alone"
                    % (", ".join(sig) or "none"))
    slope = r_en["tt"] * st.pstdev(cent["tt"]) / st.pstdev(enc) * 1e4
    out("  A heavier enable route goes with a slower ring, %.1f ppm a fF at"
        % abs(slope))
    out("  tt. The enable sits at the supply the whole time a ring runs, so a")
    out("  route on it has nothing to pull with, and at ff the same sign is")
    out("  r = %+.3f. armb_residual.py ran the tt deck again:" % r_en["ff"])
    for line in rel.get("tol_lines", []):
        out("  " + line)
    return fail


def tolerance_runs():
    """What armb_residual.py's archived runs say, as the release text
    quotes it. Imported here and not at the top, because that file reads
    this one for its arithmetic."""
    import armb_residual as ar
    sink = []
    res = ar.cmd_report(out=sink.append)
    w, g = res["win"], res["gaps"]
    tight = max((s_, r_) for r_, s_ in g if r_ == "k08")
    lines = [
        "- ten times tighter the same correlation is r = %+.3f, and the"
        % w["rt4"]["r_en"],
        "  sixteen come out in another order, r = %+.3f between the runs"
        % res["carry"],
        "- sixteen copies of instance 0 in their place spread %.1f ppm,"
        % w["null3"]["ptp"],
        "  where the sixteen spread %.1f" % w["rt3"]["ptp"],
        "- alone and solved tightly, the heaviest output route sits %.3f ppm"
        % abs(g[("k08", tight[0])][0]),
        "  under the reference and the heaviest enable route %.3f"
        % abs(g[("k14", "s2")][0]),
        "So the correlation is the solver's, and so is the spread it sits in."]
    s2 = max(abs(v[0]) for (r_, s_), v in g.items() if s_ == "s2")
    return dict(tol_lines=lines, alone=abs(g[("k08", tight[0])][0]),
                bound=(s2, abs(g[("k08", tight[0])][0])))


def sci(x):
    """1.6e-7 rather than 1.6e-07."""
    m, e = ("%.1e" % x).split("e")
    return "%se%d" % (m, int(e))


def report(freqs, refs, feats, pos, out=print, build="baseline", rel=None):
    """rel carries what only the release build's text needs: the two
    readings of frequency, and Arm A's corrector on that die."""
    fail = []
    setup = BUILDS[build]
    x = [pos[k][0] for k in range(NRO)]
    y = [pos[k][1] for k in range(NRO)]
    enc = [feats[k]["en_cap"] for k in range(NRO)]
    ouc = [feats[k]["out_cap"] for k in range(NRO)]
    tot = [a + b for a, b in zip(enc, ouc)]
    enr = [feats[k]["en_res"] for k in range(NRO)]
    our = [feats[k]["out_res"] for k in range(NRO)]

    if build == "baseline":
        out("Sixteen instances of one hardened macro, each carrying the "
            "enable and")
        out("output route it has at the top level. Spread is across the "
            "sixteen.")
    else:
        out("Sixteen instances of one hardened macro, each carrying the "
            "enable and")
        out("output route run 83 drew for it. Spread is across the sixteen.")
    agree = "1.6e-7" if rel is None else sci(rel["agree"])
    ss_spread = "1.3e-6" if rel is None else sci(rel["ss_spread"])
    out("Frequency is the deck's own f_kNN, the same one analyze_instance.py")
    out("reads. verify_instance_corners.py derives it from the period instead;")
    out("the two agree to %s, which only matters at ss where the spread"
        % agree)
    out("itself is %s, and the ss column below is the one to read loosely.\n"
        % ss_spread)
    out("  corner   peak to peak   std dev   vs mismatch   faster than the")
    out("                                                  no-route reference")
    cent, deltas, up = {}, {}, {}
    for c in CORNERS:
        f, ref = freqs[c], refs[c]
        m = st.mean(f)
        ptp = 100.0 * (max(f) - min(f)) / m
        cent[c] = cp.centred(f)
        deltas[c] = [cent[c][a] - cent[c][b] for a, b in PAIRS]
        sd = st.pstdev(cent[c])
        faster = sum(1 for v in f if v > ref)
        up[c] = faster
        out("  %-6s   %10.5f%%  %8.5f%%   %9.4fx   %2d of 16"
            % (c, ptp, sd, sd / SIGMA_RING, faster))
        want = setup["want_ptp"][c]
        if abs(ptp - want) > PTP_TOL:
            fail.append("%s spreads %.5f%% where Section 8 reports %.4f%%. The "
                        "log is not the archived run." % (c, ptp, want))
    out("")
    out("A route is passive. It can add capacitance and it cannot remove any, so")
    out("every instance should sit at or below the reference ring, which carries")
    if up["tt"] > NRO // 2 and up["ff"] > NRO // 2:
        out("no top-level route at all. At tt and ff most of them sit above "
            "it. That")
        out("rules out loading as the source of the spread before any fit is "
            "tried.")
        if rel is not None and "alone" in rel:
            out("On these routes armb_residual.py says what it is instead, "
                "at tt. Run")
            out("alone and solved tightly, the heaviest route sits %.3f ppm "
                "under the"
                % rel["alone"])
            out("reference, the side a passive route should push, and the "
                "rest is the")
            out("solver's.")
    else:
        out("no top-level route at all. %d of 16 sit above it at tt and %d at"
            % (up["tt"], up["ff"]))
        out("ff, which is not most, so this does not rule loading out on its "
            "own.")
        fail.append("the direction check no longer carries the argument: %d "
                    "and %d of 16 above the reference" % (up["tt"], up["ff"]))

    out("\nPredictability, leave-one-out, same scoring as Section 6.")
    out("A positive number is spread removed; a negative one means the corrector")
    out("did more harm than leaving the data alone.\n")
    fams = (("position, quadratic surface", lambda: cp.quad(x, y)),
            ("position, linear", lambda: [x, y]),
            ("total route capacitance", lambda: [tot]),
            ("output route capacitance", lambda: [ouc]),
            ("enable route capacitance", lambda: [enc]),
            ("route resistance", lambda: [enr, our]),
            ("capacitance and resistance", lambda: [tot, enr, our]))
    out("  %-30s %8s %8s %8s" % ("corrector", "tt", "ss", "ff"))
    grid = {}
    for label, cols in fams:
        cells = []
        for c in CORNERS:
            base = st.pstdev(cent[c])
            # Sixteen identical readings leave nothing to remove and nothing to
            # divide by. That is a pass, not a corrector worth scoring.
            v = None if base == 0.0 else (
                1.0 - cp.loo_rms(cols(), cent[c]) / base) * 100.0
            if v is not None:
                grid[(label, c)] = v
            cells.append("     --" if v is None else "%+7.1f%%" % v)
        out("  %-30s %s %s %s" % (label, *cells))
    if build == "baseline":
        out("\n  Arm A, the same two-feature model on the same scoring: "
            "+89.5%.")
    else:
        out("\n  Arm A on the same die, the same two-feature model on the "
            "same")
        out("  scoring: %+.1f%%." % rel["arm_a_loo"])
    if not grid:
        out("  Every reading is identical, so there is no spread to score.")
        pos_cells, best_key = [], None
    else:
        pos_cells = [k for k, v in grid.items() if v > 0]
        best_key = max(grid, key=grid.get)
    if best_key is not None:
        out("  %d of the %d cells are positive at all, the best of them %+.1f%%, and"
            % (len(pos_cells), len(grid), grid[best_key]))
    if build != "baseline" and len(pos_cells) == 1:
        (label, corner), = pos_cells
        out("  that one is the %s at %s." % (label, corner))
        out("  Nothing helps at the other two corners, and the cell that")
        out("  scores is the solver's, as the next block shows.")
    elif pos_cells and len({c for _, c in pos_cells}) == 1:
        only = pos_cells[0][1]
        out("  every one of them falls at %s. No corrector helps at more than one"
            % only)
        out("  corner, which is what fitting noise on sixteen points looks like.")
    elif pos_cells:
        out("  they are scattered across correctors and corners rather than")
        out("  agreeing, which is what fitting noise on sixteen points looks like.")
    if build == "baseline":
        out("  Nothing in the design database predicts this residual.")

    if build == "baseline":
        baseline_correlations(ouc, cent, out)
    else:
        fail += release_correlations(enc, ouc, cent, rel, out)

    out("\nStability. A deterministic term keeps its sign when the corner moves.")
    out("Arm A's eight pairs agree 8 of 8 between the lumped and the full RC")
    out("model, which are further apart than two corners of one model.\n")
    corr = []
    for a, b in (("tt", "ss"), ("tt", "ff"), ("ss", "ff")):
        agree = sum(1 for u, v in zip(deltas[a], deltas[b]) if (u > 0) == (v > 0))
        r = inst.pearson(cent[a], cent[b])
        p = t_two_sided(r, NRO)
        corr.append(("%s against %s" % (a, b), p))
        out("  %-14s pair signs %d of 8    per-instance r = %+.3f, p = %.3f"
            % ("%s vs %s" % (a, b), agree, r, p))
    out("")
    for label, p, adj in holm(corr):
        out("  %-18s p = %.3f   Holm-adjusted over the three = %.3f%s"
            % (label, p, adj, "" if adj >= 0.05 else "   SIGNIFICANT"))
    out("  Declared as three comparisons because three is how many were run.")

    out("\nBits. Same arithmetic as predictable_bits.py, with the measured pair")
    out("separations in place of the zero that file assumes.\n")
    out("  corner   entropy of 8   bits guessed of 8   fixed bits")
    for c in CORNERS:
        sp = SIGMA_RING * math.sqrt(2.0)
        rows = [(hbin(phi(d / sp)), max(phi(d / sp), 1 - phi(d / sp)))
                for d in deltas[c]]
        ent = sum(r[0] for r in rows)
        gue = sum(r[1] for r in rows)
        dead = sum(1 for r in rows if r[0] < 0.01)
        out("  %-6s   %10.4f     %13.4f     %5d" % (c, ent, gue, dead))
        if c == "tt":
            lo = sum(max(phi(d / (SIGMA_LO * math.sqrt(2))),
                         1 - phi(d / (SIGMA_LO * math.sqrt(2))))
                     for d in deltas[c])
            hi = sum(max(phi(d / (SIGMA_HI * math.sqrt(2))),
                         1 - phi(d / (SIGMA_HI * math.sqrt(2))))
                     for d in deltas[c])
            tt_ent, tt_gue, tt_int = ent, gue, (min(lo, hi), max(lo, hi))
    out("  Arm A  %10.2f     %13.2f     %5d"
        % (setup["entropy"], setup["guessed"], setup["fixed"]))
    out("\n  Across the mismatch sampling interval the tt guess rate runs %.2f to"
        % tt_int[0])
    out("  %.2f of 8. Four of 8 is what a coin gets." % tt_int[1])

    out("\nVerdict.")
    out("Matching does not leave a smaller version of the layout term. It leaves")
    out("something that is not the layout term at all: not caused by the routes,")
    out("not predicted by them or by position, and not stable enough across")
    out("corners to be a fingerprint. Taken at face value as if it were")
    out("deterministic, which is the most generous reading available, it hands a")
    out("reader of the design files %.2f of 8 bits against %.2f for guessing, and"
        % (tt_gue, 4.0))
    out("leaves %.4f of the 8 bits of entropy intact. Arm A on the same scale is"
        % tt_ent)
    out("%.2f and %.2f." % (setup["guessed"], setup["entropy"]))
    out("")
    out("What this does not establish. Every figure here is nominal-device")
    out("simulation of one layout, so it bounds the contribution of top-level")
    out("integration and says nothing about fabricated mismatch, supply or")
    out("temperature on a die. And the spread it bounds is small enough that the")
    out("floor underneath it is the transient solver rather than the circuit,")
    if build == "baseline":
        out("which is why the direction check above is the load-bearing one "
            "and the")
        out("correlations are not.")
    else:
        out("and on these routes at tt that is shown rather than argued: "
            "the sixteen's")
        out("spread, the instances above the reference and the enable route's")
        out("correlation all move with the solver's tolerance, and the routes")
        out("themselves move a ring by %.3f ppm at the second setting and"
            % rel["bound"][0])
        out("%.3f at the third." % rel["bound"][1])
    return fail


def gather(build="baseline"):
    setup = BUILDS[build]
    freqs, refs = {}, {}
    for c in CORNERS:
        freqs[c], refs[c], _ = read_corner(c, setup["logs"])
    feats = {}
    for row in csv.DictReader(open(setup["parasitics"], newline="")):
        feats[int(row["instance"])] = dict(
            en_cap=float(row["en_cap_fF"]), out_cap=float(row["out_cap_fF"]),
            en_res=float(row["en_res"]), out_res=float(row["out_res"]))
    if sorted(feats) != list(range(NRO)):
        raise SystemExit("instance_parasitics.csv does not describe sixteen "
                         "instances")
    # The two readings of frequency: how far apart they come, and the ss
    # spread by the period, which is the one the corner verifier quotes.
    agree = 0.0
    for c in CORNERS:
        per, own = by_period(setup["logs"], c)
        agree = max(agree, max(abs(a - b) / b for a, b in zip(per, own)))
        if c == "ss":
            ss_spread = (max(per) - min(per)) / st.mean(per)
    rel = dict(agree=agree, ss_spread=ss_spread)
    if build == "release":
        rel["arm_a_loo"] = arm_a_loo(setup["spef"], setup["rc"])
        rel.update(tolerance_runs())
    return freqs, refs, feats, macro_positions(setup["defn"]), rel


# ------------------------------------------------------------------- self test

def selftest():
    """Plant the results this script exists to detect and check it detects them.

    The cases are the two ways the answer could be wrong. If the routes really
    did load the rings, the capacitance corrector has to find it and the
    direction check has to stop reporting instances above the reference. If the
    spread were large enough to matter, the bits have to collapse.
    """
    ref = 570.6359
    pos = {k: (60.0 * (k % 4), 48.0 * (k // 4)) for k in range(NRO)}
    feats = {k: dict(en_cap=1.0 + 0.8 * k, out_cap=3.0 + 1.7 * k,
                     en_res=1 + k % 3, out_res=1 + k % 4) for k in range(NRO)}
    ok = True

    def run(mk):
        freqs = {c: mk(c) for c in CORNERS}
        lines = []
        report(freqs, {c: ref for c in CORNERS}, feats, pos, out=lines.append)
        return "\n".join(lines)

    # 1. a genuine load: frequency falls with total route capacitance.
    def loaded(c):
        return [ref * (1 - 1e-5 * (feats[k]["en_cap"] + feats[k]["out_cap"]))
                for k in range(NRO)]
    txt = run(loaded)
    got = [ln for ln in txt.splitlines() if "total route capacitance" in ln]
    strong = got and all(float(v.rstrip("%")) > 50
                         for v in got[0].split()[-3:])
    print("  %s a real capacitive load is found by the capacitance corrector"
          % ("ok   " if strong else "WRONG"))
    ok &= bool(strong)
    below = "16 of 16" not in txt and " 0 of 16" in txt
    print("  %s a real capacitive load leaves every instance below the reference"
          % ("ok   " if below else "WRONG"))
    ok &= below

    # 2. pair separations ten times the mismatch scale: the bits have to go.
    # The pairs are what decide a bit, so the pattern alternates rather than
    # ramping. A ramp of the same total width leaves neighbours close together
    # and would not test anything.
    def wide(c):
        return [ref * (1 + 0.0062 * (1 if k % 2 == 0 else -1)) for k in range(NRO)]
    txt = run(wide)
    line = [ln for ln in txt.splitlines() if ln.startswith("  tt  ")][-1]
    ent = float(line.split()[1])
    print("  %s a spread ten times the mismatch scale collapses the entropy "
          "(%.2f of 8)" % ("ok   " if ent < 1.0 else "WRONG", ent))
    ok &= ent < 1.0

    # 3. identical instances: entropy has to be the full eight bits.
    txt = run(lambda c: [ref] * NRO)
    line = [ln for ln in txt.splitlines() if ln.startswith("  tt  ")][-1]
    ent, gue = float(line.split()[1]), float(line.split()[2])
    exact = abs(ent - 8.0) < 1e-9 and abs(gue - 4.0) < 1e-9
    print("  %s sixteen identical instances give exactly 8.00 and 4.00"
          % ("ok   " if exact else "WRONG"))
    ok &= exact

    print("selftest: %s" % ("all four planted cases behaved" if ok
                            else "SOMETHING IS WRONG"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true",
                    help="run the planted cases and exit; needs no logs, no "
                         "PDK and no ngspice")
    ap.add_argument("--build", default="baseline", choices=sorted(BUILDS),
                    help="whose routes: the two-arm baseline the paper's "
                         "Section 8.2 table comes from (default), or run 83's "
                         "in armb3/")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()

    freqs, refs, feats, pos, rel = gather(args.build)
    fail = report(freqs, refs, feats, pos, build=args.build, rel=rel)
    if fail:
        print()
        for m in fail:
            print("FAIL: " + m)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
