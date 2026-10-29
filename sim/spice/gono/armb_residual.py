#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Where Arm B's leftover on the release routes comes from.

matched_arm.py asks Section 8.2's questions of the sixteen instances, and
on run 83's routes one answer came back that the baseline never gave: at tt
the enable route's capacitance goes with frequency, r = -0.805, p = 0.0002,
heavier routes slower. The enable sits at the supply the whole time a ring
runs, so a route on it has nothing to pull with. Either the circuit does
something I did not expect or the solver does. This file is how I told the
two apart, on 29 October, and it keeps every run it needed.

The archived tt deck holds all eighteen rings, control, reference and the
sixteen, in one transient at ngspice's default tolerance. Four things were
run against it, all at tt:

  rt3     the archived deck again, with one line added to write the
          waveforms. Its log comes back the archive's to the digit, so the
          setup is the one that made armb3/
  rt4     the same with reltol ten times tighter, 1e-4
  null3   sixteen copies of instance 0 in place of the sixteen, routes and
  null4   all, each enabled 37 ps after the one before, at both tolerances.
          One circuit sixteen times: whatever spreads them is the solver
  alone/  one ring per deck, the reference or one instance with its routes,
          at three settings, each tighter than the last in tolerance and in
          the largest step the solver may take

What came back. In rt3 the correlation holds in every window from the
second rise to the 44th, and each instance keeps its own offset period
after period, so it is not the start. At 1e-4 it is gone, r = -0.059, and
the sixteen come out in another order altogether, r = +0.22 between the two
runs. The copies spread 4.3 ppm and 1.8 where the sixteen spread 32.6 and
27.1. So the solver puts one circuit in the same place wherever it starts
it, and different circuits in different places, by tens of ppm, in an order
that changes with the tolerance.

Alone, the heaviest output route, k08's 45.4 fF, sits 2.33 ppm under the
reference at the first setting, 0.034 at the second and 0.006 at the third,
and the heaviest enable route, k14's, 0.76 and then 0.020. That is the
routes' own effect: nothing a counter can see. Every per-instance number the
shared deck gives, on either build, is the solver's.

cross reads a wave file into the rising crossings, interpolated the way the
deck's meas lines do it, and check holds every crossing file to its log's
own trig and targ times. The wave files run to 46 MB and stay out of the
repository; the crossings carry everything the report reads.

Run:
    python3 armb_residual.py make DIR       every deck, from the archived one
    python3 armb_residual.py cross WAVE CSV [RING]
    python3 armb_residual.py check          the archive against itself
    python3 armb_residual.py                the report and its claims
    python3 armb_residual.py --selftest
"""

import argparse
import csv
import math
import os
import re
import shutil
import statistics as st
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyze_instance as inst   # noqa: E402  (log reader and Pearson)
import matched_arm as ma          # noqa: E402  (the t test and Holm)

NRO = 16
SRC = os.path.join(HERE, "armb3", "armb_instances.spice")
PARASITICS = os.path.join(HERE, "armb3", "instance_parasitics.csv")
ARCH = os.path.join(HERE, "armb3", "tol")
DECK = "armb_instances.spice"
LOG = "armb_instances_out.txt"
CROSS = "crossings.csv"
WAVE = "armb_wave.txt"
# The archived run, and the same deck with the solver held ten times
# tighter. Nothing else changes but the line that writes the waveforms.
RUNS = (("rt3", None), ("rt4", 1e-4))
# And sixteen copies of one instance, the same circuit sixteen times, each
# started a little later, at both tolerances: what the solver alone spreads.
NULLS = (("null3", None), ("null4", 1e-4))
STAGGER_PS = 37.0
# And one ring alone in a deck, the reference or an instance with its
# routes, at three settings, each with the tolerance ten times tighter and
# the step cap at least halved: reltol and the largest step in ps.
SETTINGS = {"s1": (1e-5, 0.25), "s2": (1e-6, 0.1), "s3": (1e-7, 0.05)}
ALONE = (("r", "s1"), ("k02", "s1"), ("k08", "s1"), ("k11", "s1"),
         ("k14", "s1"), ("r", "s2"), ("k08", "s2"), ("k14", "s2"),
         ("r", "s3"), ("k08", "s3"))
NAMES = ["c", "r"] + ["k%02d" % k for k in range(NRO)]
VECS = ["v(c_out)", "v(r_out)"] + ["v(k%02d_omac)" % k for k in range(NRO)]
HALF = 0.9                  # half the tt supply, where the deck's meas cross
W1 = (5, 25)                # the deck's own window, rises 5 to 25
W2 = (25, 40)               # the later one, rises 25 to 40
TRIG_TOL_PS = 0.02          # the log prints seven digits, 0.01 ps here
GAP_PPM = 0.1               # what alone at the tightest setting has to beat


# ------------------------------------------------------------------ decks

def make_deck(text, reltol):
    """The archived deck, one line to write the waveforms and, for the
    tighter run, one line for the tolerance. Each insertion is counted."""
    lines = text.split("\n")
    save = [i for i, ln in enumerate(lines) if ln.startswith(".save ")]
    quit_ = [i for i, ln in enumerate(lines) if ln == "quit"]
    if len(save) != 1 or len(quit_) != 1:
        raise SystemExit("armb_residual: the archived deck has %d .save and "
                         "%d quit lines, expected one of each"
                         % (len(save), len(quit_)))
    lines.insert(quit_[0], "wrdata %s %s" % (WAVE, " ".join(VECS)))
    if reltol:
        lines.insert(save[0], ".options reltol=%g" % reltol)
    return "\n".join(lines)


def make_null(text, reltol, stagger_ps=STAGGER_PS):
    """Sixteen copies of instance 0, routes and all, each enabled
    stagger_ps later than the one before. The copies are the same circuit,
    so whatever spreads them is the solver."""
    lines = text.split("\n")
    head = [i for i, ln in enumerate(lines)
            if ln.startswith("* --- instance ")]
    if len(head) != NRO:
        raise SystemExit("armb_residual: %d instance blocks in the deck, "
                         "expected %d" % (len(head), NRO))
    end = [i for i, ln in enumerate(lines) if ln.startswith(".save ")][0]
    while not lines[end - 1].strip():
        end -= 1
    block = lines[head[0] + 1:head[1]]
    while block and not block[-1].strip():
        block.pop()
    drv = [j for j, ln in enumerate(block) if ln.startswith("Xk00_drv EN ")]
    if len(drv) != 1:
        raise SystemExit("armb_residual: instance 0's driver is not on EN")
    body = []
    for k in range(NRO):
        late = 2.0 + k * stagger_ps * 1e-3
        body.append("* --- copy %d of instance 0, enabled %g ps late ---"
                    % (k, k * stagger_ps))
        body.append("Ven%02d EN%02d 0 PULSE(0 1.8 %.4fn 50p 50p 1 2)"
                    % (k, k, late))
        for j, ln in enumerate(block):
            ln = ln.replace("k00_", "k%02d_" % k)
            if j == drv[0]:
                ln = ln.replace(" EN ", " EN%02d " % k, 1)
            body.append(ln)
        body.append("")
    out = lines[:head[0]] + body + lines[end:]
    out[0] = out[0] + ", null: sixteen copies of instance 0"
    return make_deck("\n".join(out), reltol)


def make_single(text, ring, reltol, tmax_ps):
    """One ring alone, the reference or one instance with its routes, with
    nothing else in the deck to share the solver's steps, and the step
    capped at tmax_ps as well as the tolerance set."""
    lines = text.split("\n")
    ctl = [i for i, ln in enumerate(lines) if ln.startswith("* --- control")]
    heads = [i for i, ln in enumerate(lines)
             if ln.startswith("* --- reference") or
             ln.startswith("* --- instance ")]
    save = [i for i, ln in enumerate(lines) if ln.startswith(".save ")]
    if len(ctl) != 1 or len(heads) != NRO + 1 or len(save) != 1:
        raise SystemExit("armb_residual: the archived deck is not laid out "
                         "the way make_single expects")
    pick = 0 if ring == "r" else 1 + int(ring[1:])
    stop = heads[pick + 1] if pick + 1 < len(heads) else save[0]
    block = lines[heads[pick]:stop]
    while block and not block[-1].strip():
        block.pop()
    tag = "r" if ring == "r" else ring
    outs = ["r_out"] if ring == "r" else ["%s_omac" % ring, "%s_orx" % ring]
    want = re.compile(r"\b(tp|tq|hi|hx|dr|df|sm|sr|f)_%s\b" % tag)
    ctrl = [ln for ln in lines[save[0]:] if
            (ln.startswith("meas ") or ln.startswith("let ") or
             ln.startswith("print ")) and want.search(ln)]
    who = ("the reference" if ring == "r"
           else "instance %d with its routes" % (pick - 1))
    out = ["* Arm B, one ring alone: %s, from %s"
           % (who, os.path.relpath(SRC, HERE).replace(os.sep, "/"))]
    out += [ln for ln in lines[1:ctl[0]] if not ln.startswith("* control ")]
    out += block + [""]
    out += [".save " + " ".join("v(%s)" % o for o in outs),
            ".options reltol=%g" % reltol,
            ".tran 1p 80n 0 %gp" % tmax_ps,
            ".control", "run"] + ctrl
    out += ["wrdata %s v(%s)" % (WAVE, outs[0]), "quit", ".endc", ".end"]
    return "\n".join(out)


def cmd_make(out):
    text = open(SRC, encoding="utf-8").read()
    for name, reltol in RUNS:
        d = os.path.join(out, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, DECK), "w", encoding="utf-8",
                  newline="") as fh:
            fh.write(make_deck(text, reltol))
        print("wrote %s" % os.path.join(d, DECK))
    for name, reltol in NULLS:
        d = os.path.join(out, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, DECK), "w", encoding="utf-8",
                  newline="") as fh:
            fh.write(make_null(text, reltol))
        print("wrote %s" % os.path.join(d, DECK))
    for ring, setting in ALONE:
        d = os.path.join(out, "alone", "%s_%s" % (ring, setting))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, DECK), "w", encoding="utf-8",
                  newline="") as fh:
            fh.write(make_single(text, ring, *SETTINGS[setting]))
        print("wrote %s" % os.path.join(d, DECK))
    return 0


# -------------------------------------------------------------- crossings

def crossings(path, val=HALF, names=NAMES):
    """Rising crossings of every ring's output, interpolated the way the
    deck's own meas lines do it: the first sample at or above the level
    after one below it, and a straight line between the two."""
    out = dict((n, []) for n in names)
    prev_t = prev_v = None
    with open(path) as fh:
        for line in fh:
            p = line.split()
            if len(p) != 2 * len(names):
                continue
            t = float(p[0])
            vs = [float(p[2 * j + 1]) for j in range(len(names))]
            if prev_v is not None:
                for j, n in enumerate(names):
                    a, b = prev_v[j], vs[j]
                    if a < val <= b:
                        out[n].append(prev_t + (val - a) * (t - prev_t)
                                      / (b - a))
            prev_t, prev_v = t, vs
    return out


def write_crossings(cr, path, names=NAMES):
    with open(path, "w", newline="\n", encoding="utf-8") as fh:
        fh.write("ring,rise,t_ps\n")
        for n in names:
            for i, t in enumerate(cr[n], 1):
                fh.write("%s,%d,%.4f\n" % (n, i, t * 1e12))


def read_crossings(path):
    out = dict((n, []) for n in NAMES)
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["ring"]].append((int(row["rise"]), float(row["t_ps"])))
    for n in out:
        out[n] = [t for _, t in sorted(out[n])]
    return out


def cmd_cross(wave, out, ring=None):
    names = [ring] if ring else NAMES
    cr = crossings(wave, names=names)
    write_crossings(cr, out, names)
    print("%s: %s" % (out, ", ".join("%s %d" % (n, len(cr[n]))
                                     for n in names)))
    return 0


# ------------------------------------------------------------------- logs

def trig_targ(path):
    """tp_X = value targ= t25 trig= t5, for every ring, in ps."""
    txt = open(path, errors="ignore").read()
    out = {}
    pat = r"^tp_(\w+)\s*=\s*(\S+)\s+targ=\s*(\S+)\s+trig=\s*(\S+)"
    for m in re.finditer(pat, txt, re.M):
        out[m.group(1)] = (float(m.group(4)) * 1e12, float(m.group(3)) * 1e12)
    return out


def finished(path):
    try:
        lines = open(path, errors="ignore").read().rstrip("\n").split("\n")
    except OSError:
        return False
    return bool(lines) and lines[-1].startswith("ngspice-") \
        and lines[-1].endswith(" done")


def load_run(root, name):
    d = os.path.join(root, name)
    return dict(name=name, dir=d,
                vals=inst.read_log(os.path.join(d, LOG)),
                tt=trig_targ(os.path.join(d, LOG)),
                cross=read_crossings(os.path.join(d, CROSS)))


def load_alone(root, ring, setting):
    d = os.path.join(root, "alone", "%s_%s" % (ring, setting))
    return dict(name="%s_%s" % (ring, setting), dir=d, ring=ring,
                tt=trig_targ(os.path.join(d, LOG)),
                cross=read_crossings(os.path.join(d, CROSS))[ring])


def features():
    rows = dict((int(r["instance"]), r) for r in
                csv.DictReader(open(PARASITICS, newline="")))
    if sorted(rows) != list(range(NRO)):
        raise SystemExit("%s does not describe sixteen instances" % PARASITICS)
    return ([float(rows[k]["en_cap_fF"]) for k in range(NRO)],
            [float(rows[k]["out_cap_fF"]) for k in range(NRO)])


# --------------------------------------------------------------- numbers

def tol_label(x):
    """1e-4 rather than 0.0001 or 1e-04."""
    m, e = ("%.0e" % x).split("e")
    return "%se%d" % (m, int(e))


def window(ts, a, b):
    """Mean frequency between rise a and rise b, MHz, ts in ps."""
    return (b - a) / (ts[b - 1] - ts[a - 1]) * 1e6


def ppm(vals, ref):
    return [(v - ref) / ref * 1e6 for v in vals]


def stats(run, w, enc, ouc):
    cr = run["cross"]
    fr = window(cr["r"], *w)
    fk = [window(cr["k%02d" % k], *w) for k in range(NRO)]
    m = st.mean(fk)
    cen = ppm(fk, m)
    r_en, r_out = inst.pearson(enc, cen), inst.pearson(ouc, cen)
    return dict(ref=fr, f=fk, mean=m, ptp=max(cen) - min(cen),
                sd=st.pstdev(cen), above=sum(1 for v in fk if v > fr),
                r_en=r_en, p_en=ma.t_two_sided(r_en, NRO),
                r_out=r_out, p_out=ma.t_two_sided(r_out, NRO))


def periods(ts):
    return [b - a for a, b in zip(ts, ts[1:])]


def cycle_noise(run, first=2):
    """Per ring, the scatter of single periods about that ring's own mean,
    from the second period on, in ppm. Then the scatter across the rings
    of their means, the part that stays put from cycle to cycle."""
    cr = run["cross"]
    n = min(len(cr["k%02d" % k]) for k in range(NRO)) - 1
    per = [periods(cr["k%02d" % k])[first - 1:n] for k in range(NRO)]
    own = [st.pstdev(ppm(p, st.mean(p))) for p in per]
    means = [st.mean(p) for p in per]
    fixed = st.pstdev(ppm(means, st.mean(means)))
    return dict(own=st.mean(own), fixed=fixed, cycles=len(per[0]))


def bits(f):
    """Matched_arm's arithmetic, on one set of sixteen frequencies."""
    cen = ma.cp.centred(f)
    d = [cen[a] - cen[b] for a, b in ma.PAIRS]
    sp = ma.SIGMA_RING * math.sqrt(2.0)
    ent = sum(ma.hbin(ma.phi(x / sp)) for x in d)
    gue = sum(max(ma.phi(x / sp), 1 - ma.phi(x / sp)) for x in d)
    return ent, gue


# ------------------------------------------------------------------ check

def cmd_check(root=ARCH):
    """The archive against itself: decks, logs, crossings."""
    bad, n = [], 0
    src = open(SRC, encoding="utf-8").read()
    archived = inst.read_log(os.path.join(HERE, "armb3", LOG))
    nulls = set(name for name, _ in NULLS)
    for name, reltol in RUNS + NULLS:
        d = os.path.join(root, name)
        n += 1
        deck = open(os.path.join(d, DECK), encoding="utf-8").read()
        if name in nulls:
            if deck != make_null(src, reltol):
                bad.append("%s/%s is not sixteen copies of armb3's instance "
                           "0 as make_null writes them" % (name, DECK))
        elif deck != make_deck(src, reltol):
            bad.append("%s/%s is not armb3's deck with its line%s added"
                       % (name, DECK, "s" if reltol else ""))
        n += 1
        if not finished(os.path.join(d, LOG)):
            bad.append("%s/%s does not end the way a finished run ends"
                       % (name, LOG))
            continue
        run = load_run(root, name)
        n += 1
        short = [r for r in NAMES if len(run["cross"][r]) < W2[1]]
        if short:
            bad.append("%s: %s cross fewer than %d times"
                       % (name, ", ".join(short), W2[1]))
            continue
        n += 1
        worst, where = 0.0, ""
        for r in NAMES:
            trig, targ = run["tt"][r]
            for got, want in ((run["cross"][r][W1[0] - 1], trig),
                              (run["cross"][r][W1[1] - 1], targ)):
                if abs(got - want) > worst:
                    worst, where = abs(got - want), r
        if worst > TRIG_TOL_PS:
            bad.append("%s: crossing %.4f ps off the log's own meas on %s"
                       % (name, worst, where))
        print("  %s  rises %d and %d of all 18 rings within %.4f ps of the "
              "log's meas" % (name, W1[0], W1[1], worst))
        if reltol is None and name not in nulls:
            n += 1
            diff = sorted(k for k in set(archived) | set(run["vals"])
                          if archived.get(k) != run["vals"].get(k))
            if diff:
                bad.append("%s: %d values differ from armb3's log, %s"
                           % (name, len(diff), ", ".join(diff[:4])))
            else:
                print("  %s  all %d values of its log are armb3's, to the "
                      "digit" % (name, len(archived)))
    for ring, setting in ALONE:
        name = "%s_%s" % (ring, setting)
        d = os.path.join(root, "alone", name)
        n += 1
        deck = open(os.path.join(d, DECK), encoding="utf-8").read()
        if deck != make_single(src, ring, *SETTINGS[setting]):
            bad.append("alone/%s/%s is not what make_single writes"
                       % (name, DECK))
        n += 1
        if not finished(os.path.join(d, LOG)):
            bad.append("alone/%s/%s does not end the way a finished run "
                       "ends" % (name, LOG))
            continue
        run = load_alone(root, ring, setting)
        n += 1
        tag = "r" if ring == "r" else ring
        trig, targ = run["tt"][tag]
        if len(run["cross"]) < W2[1]:
            bad.append("alone/%s crosses %d times" % (name, len(run["cross"])))
            continue
        worst = max(abs(run["cross"][W1[0] - 1] - trig),
                    abs(run["cross"][W1[1] - 1] - targ))
        if worst > TRIG_TOL_PS:
            bad.append("alone/%s: crossing %.4f ps off the log's own meas"
                       % (name, worst))
    print("  alone  %d one-ring runs, each deck as written, each finished, "
          "rises %d and %d at the log's meas" % (len(ALONE), W1[0], W1[1]))
    for m in bad:
        print("FAIL: " + m)
    print("%d of %d checks pass" % (n - len(bad), n))
    return 1 if bad else 0



# ----------------------------------------------------------------- report

def cmd_report(root=ARCH, out=print):
    enc, ouc = features()
    names = [n for n, _ in RUNS + NULLS]
    tol = dict(RUNS + NULLS)
    runs = dict((n, load_run(root, n)) for n in names)
    win = dict((n, stats(runs[n], W1, enc, ouc)) for n in names)
    late = dict((n, stats(runs[n], W2, enc, ouc)) for n in names)
    cyc = dict((n, cycle_noise(runs[n])) for n in names)

    out("Arm B's sixteen on the release routes, tt, at the archived tolerance")
    out("and ten times tighter; then sixteen copies of instance 0, one")
    out("circuit sixteen times, started %g ps apart, at both. Rises %d to %d,"
        % (STAGGER_PS, W1[0], W1[1]))
    out("the deck's own window. ppm of the sixteen's mean.\n")
    out("  run     reltol   reference MHz   spread   sd    above the   "
        "enable route")
    out("                                   ppm      ppm   reference   "
        "r       p")
    for n in names:
        w = win[n]
        out("  %-6s  %-6s   %12.5f   %6.1f   %4.1f   %2d of 16    %+.3f  %.4f"
            % (n, tol_label(tol[n] or 1e-3), w["ref"], w["ptp"], w["sd"],
               w["above"], w["r_en"], w["p_en"]))
    out("\n  The same from rise %d to %d, after the window:" % W2)
    for n in names:
        w = late[n]
        out("  %-6s  spread %5.1f ppm, sd %4.1f, enable route r = %+.3f"
            % (n, w["ptp"], w["sd"], w["r_en"]))

    out("\nOne period at a time. How far a ring's single periods scatter")
    out("about its own mean, and how far the sixteen means sit apart, the")
    out("part that stays put from one cycle to the next:\n")
    for n in names:
        c = cyc[n]
        out("  %-6s  %4.1f ppm a period, %4.1f ppm between rings, %d periods"
            % (n, c["own"], c["fixed"], c["cycles"]))

    a, b = win["rt3"], win["rt4"]
    ca, cb = ppm(a["f"], a["mean"]), ppm(b["f"], b["mean"])
    r = inst.pearson(ca, cb)
    shift = [(y - x) / x * 1e6 for x, y in zip(a["f"], b["f"])]
    out("\nTen times tighter, every ring moves: the reference %+.1f ppm, the"
        % ((b["ref"] - a["ref"]) / a["ref"] * 1e6))
    out("sixteen %+.1f to %+.1f. Which instance sits where does not carry"
        % (min(shift), max(shift)))
    out("over: the sixteen at 1e-3 against the sixteen at 1e-4, r = %+.3f,"
        % r)
    out("p = %.3f." % ma.t_two_sided(r, NRO))

    out("\nBits, matched_arm.py's arithmetic on each set of sixteen:\n")
    for n in names:
        e, g = bits(win[n]["f"])
        out("  %-6s  entropy %.4f of 8, a reader calls %.4f" % (n, e, g))

    alone = dict(((ring, st_), load_alone(root, ring, st_))
                 for ring, st_ in ALONE)
    out("\nOne ring alone in a deck, with nothing to share the solver's steps")
    out("with, at three settings. Each instance against the reference run")
    out("alone at the same setting, ppm, rises %d to %d and %d to %d:\n"
        % (W1 + W2))
    out("  setting  reltol  step cap  instance   %d to %d   %d to %d"
        % (W1 + W2))
    gaps = {}
    for setting in sorted(SETTINGS):
        rt, cap = SETTINGS[setting]
        ref = alone[("r", setting)]["cross"]
        first = True
        for ring, st_ in ALONE:
            if st_ != setting or ring == "r":
                continue
            ts = alone[(ring, setting)]["cross"]
            g1 = ppm([window(ts, *W1)], window(ref, *W1))[0]
            g2 = ppm([window(ts, *W2)], window(ref, *W2))[0]
            gaps[(ring, setting)] = (g1, g2)
            out("  %-7s  %-6s  %-8s  %-8s  %+7.2f   %+7.2f"
                % (setting if first else "", tol_label(rt) if first else "",
                   ("%g ps" % cap) if first else "", ring, g1, g2))
            first = False
    r1 = window(alone[("r", "s1")]["cross"], *W1)
    r2 = window(alone[("r", "s2")]["cross"], *W1)
    r3 = window(alone[("r", "s3")]["cross"], *W1)
    out("\n  The reference alone reads %.5f MHz at s1, %+.1f ppm on that at"
        % (r1, ppm([r2], r1)[0]))
    out("  s2 and %+.1f at s3." % ppm([r3], r1)[0])
    return dict(win=win, late=late, cyc=cyc, carry=r, shift=shift, gaps=gaps)



def claims(res, out=print):
    """What the write-up says, held to the numbers. A rerun that moves
    any of them fails here rather than leaving the text behind."""
    w, bad = res["win"], []

    def want(ok, text):
        out("  %s %s" % ("ok  " if ok else "FAIL", text))
        if not ok:
            bad.append(text)

    out("\nWhat the write-up rests on:\n")
    want(w["rt3"]["p_en"] < 0.01, "the archived run has the enable route "
         "against frequency, p = %.4f" % w["rt3"]["p_en"])
    want(w["rt4"]["p_en"] > 0.05, "ten times tighter it is gone, p = %.3f"
         % w["rt4"]["p_en"])
    want(abs(res["carry"]) < 0.5, "and the sixteen come out in another "
         "order, r = %+.3f" % res["carry"])
    for a, b in (("null3", "rt3"), ("null4", "rt4")):
        want(w[a]["ptp"] < 0.25 * w[b]["ptp"], "%s, one circuit sixteen "
             "times, spreads %.1f ppm against %s's %.1f"
             % (a, w[a]["ptp"], b, w[b]["ptp"]))
    g = res["gaps"]
    for ring in ("k08", "k14"):
        steps = [st_ for st_ in sorted(SETTINGS) if (ring, st_) in g]
        mags = [abs(g[(ring, st_)][0]) for st_ in steps]
        want(all(b < a for a, b in zip(mags, mags[1:])), "alone, %s's gap "
             "to the reference shrinks at every tighter setting, %s ppm"
             % (ring, ", ".join("%.3f" % m for m in mags)))
        want(mags[-1] < GAP_PPM, "and ends under %g ppm" % GAP_PPM)
    return bad


# --------------------------------------------------------------- selftest

def _synth_run(root, name, period_ps, offsets_ppm, noise_ps=0.0, seed=1):
    """A fake run: a log with tp lines and a crossings file, rings rising
    every period_ps * (1 + offset), started a few ps apart."""
    import random
    rnd = random.Random(seed)
    d = os.path.join(root, name)
    os.makedirs(d)
    cr = {}
    for j, n in enumerate(NAMES):
        p = period_ps * (1.0 + offsets_ppm[j] * 1e-6)
        t0 = 1000.0 + 3.0 * j
        cr[n] = [t0 + i * p + rnd.gauss(0.0, noise_ps) for i in range(44)]
    with open(os.path.join(d, LOG), "w") as fh:
        for n in NAMES:
            a, b = cr[n][W1[0] - 1], cr[n][W1[1] - 1]
            fh.write("tp_%s = %.6e targ= %.6e trig= %.6e\n"
                     % (n, (b - a) * 1e-12, b * 1e-12, a * 1e-12))
        for n in NAMES:
            a, b = cr[n][W1[0] - 1], cr[n][W1[1] - 1]
            fh.write("f_%s = %.6e\n" % (n, 20.0 / ((b - a) * 1e-12)))
        fh.write("ngspice-42 done\n")
    write_crossings(dict((n, [t * 1e-12 for t in cr[n]]) for n in NAMES),
                    os.path.join(d, CROSS))
    return d


def selftest():
    print("self-test of armb_residual")
    ok = True
    enc, _ = features()

    def say(good, text):
        print("  %s %s" % ("ok   " if good else "WRONG", text))
        return good

    # 1. the deck edit: one line each, nothing else moved
    src = "\n".join(["* deck", ".save v(a)", ".tran 1p 80n", ".control",
                     "run", "print f", "quit", ".endc", ".end"])
    a, b = make_deck(src, None), make_deck(src, 1e-4)
    extra_a = set(a.split("\n")) - set(src.split("\n"))
    extra_b = set(b.split("\n")) - set(src.split("\n"))
    ok &= say(len(a.split("\n")) == len(src.split("\n")) + 1
              and len(extra_a) == 1 and list(extra_a)[0].startswith("wrdata")
              and extra_b == extra_a | {".options reltol=0.0001"},
              "the decks are the archived one plus one line, or two")
    try:
        make_deck(src.replace(".save v(a)\n", ""), None)
        ok &= say(False, "a deck without its .save line is refused")
    except SystemExit:
        ok &= say(True, "a deck without its .save line is refused")

    # 2. the null deck is one circuit sixteen times, and a one-ring deck
    # keeps its own ring's lines and nobody else's
    real = open(SRC, encoding="utf-8").read()
    null = make_null(real, None)
    blocks = []
    for k in range(NRO):
        body = [ln.replace("k%02d_" % k, "kXX_").replace("EN%02d " % k,
                                                          "ENXX ")
                for ln in null.split("\n")
                if ln.startswith(("X", "R", "C")) and "k%02d_" % k in ln]
        blocks.append(body)
    late = sorted(float(re.search(r"PULSE\(0 1\.8 (\S+)n", ln).group(1))
                  for ln in null.split("\n") if re.match(r"Ven\d\d ", ln))
    ok &= say(all(b == blocks[0] for b in blocks) and len(blocks[0]) > 60
              and len(late) == NRO
              and abs(late[-1] - late[0] - 15 * STAGGER_PS / 1000) < 1e-9,
              "the null deck is instance 0 sixteen times, %d lines each, "
              "enabled %g ps apart" % (len(blocks[0]), STAGGER_PS))
    one = make_single(real, "k08", 1e-6, 0.1)
    others = [k for k in range(NRO) if k != 8
              and re.search(r"\bk%02d_" % k, one)]
    ok &= say(not others and "r_out" not in one and "c_out" not in one
              and ".tran 1p 80n 0 0.1p" in one
              and one.count("meas tran ") == 8,
              "a one-ring deck holds its own ring and its eight meas lines")

    tmp = tempfile.mkdtemp(prefix="armb_residual.")
    try:
        # 3. crossings out of a wave file, against times set by hand
        wave = os.path.join(tmp, "wave.txt")
        times = [i * 1.0e-12 for i in range(4001)]
        rises = [1000.25e-12, 2750.5e-12, 3500.75e-12]
        with open(wave, "w") as fh:
            for t in times:
                row = []
                for j in range(len(NAMES)):
                    shift = j * 0.1e-12
                    v = 0.0
                    for r in rises:
                        if t >= r + shift - 50e-12:
                            v = min(1.8, max(0.0, (t - (r + shift - 50e-12))
                                             / 100e-12 * 1.8))
                        if t >= r + shift + 300e-12:
                            v = 0.0
                    row += ["%.8e" % t, "%.8e" % v]
                fh.write(" ".join(row) + "\n")
        cr = crossings(wave)
        worst = max(abs(cr[n][i] - (r + j * 0.1e-12))
                    for j, n in enumerate(NAMES) for i, r in enumerate(rises))
        ok &= say(all(len(cr[n]) == 3 for n in NAMES) and worst < 1e-16,
                  "rising crossings land where they were put, %.1e s off"
                  % worst)

        # 4. a planted route term is found, and plain noise is not
        period = 1752.4
        # a longer period for a heavier enable route, which is the sign
        # the archived run shows
        planted = [0.0, 0.0] + [3.6 * (c - st.mean(enc)) for c in enc]
        root = os.path.join(tmp, "planted")
        _synth_run(root, "rt3", period, planted)
        s = stats(load_run(root, "rt3"), W1, enc, enc)
        ok &= say(s["r_en"] < -0.99, "a planted enable-route term comes "
                  "back at r = %+.3f" % s["r_en"])
        root = os.path.join(tmp, "noise")
        _synth_run(root, "rt3", period, [0.0] * len(NAMES), noise_ps=0.02)
        s = stats(load_run(root, "rt3"), W1, enc, enc)
        ok &= say(s["p_en"] > 0.05 and s["sd"] < 2.0,
                  "per-cycle noise alone gives no route term, r = %+.3f, "
                  "%.2f ppm" % (s["r_en"], s["sd"]))
        c = cycle_noise(load_run(root, "rt3"))
        ok &= say(c["own"] > 5 * c["fixed"],
                  "and shows as cycle noise, %.1f ppm, not as a fixed offset, "
                  "%.2f ppm" % (c["own"], c["fixed"]))

        # 5. the claims trip when the numbers they rest on move
        good = dict(win=dict(rt3=dict(p_en=0.0002, ptp=32.0),
                             rt4=dict(p_en=0.8, ptp=27.0),
                             null3=dict(ptp=4.0), null4=dict(ptp=2.0)),
                    carry=0.2,
                    gaps={("k08", "s1"): (-2.3, 0), ("k08", "s2"): (-0.03, 0),
                          ("k08", "s3"): (-0.006, 0),
                          ("k14", "s1"): (-0.8, 0), ("k14", "s2"): (-0.02, 0)})
        sink = []
        ok &= say(not claims(good, out=sink.append),
                  "the archived numbers pass the claims")
        bad = dict(good, win=dict(good["win"], rt4=dict(p_en=0.001,
                                                        ptp=27.0)))
        ok &= say(len(claims(bad, out=sink.append)) == 1,
                  "an enable correlation that survived 1e-4 would fail one")
        grew = dict(good["gaps"])
        grew[("k08", "s3")] = (-0.5, 0)
        bad = dict(good, gaps=grew)
        ok &= say(len(claims(bad, out=sink.append)) == 2,
                  "a gap that grew back at s3 would fail two")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("self-test %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


# ------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="report",
                    choices=("report", "make", "cross", "check"))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--dir", default=ARCH,
                    help="the archive, default armb3/tol")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "make":
        if len(a.args) != 1:
            ap.error("make wants one output directory")
        return cmd_make(a.args[0])
    if a.cmd == "cross":
        if len(a.args) not in (2, 3):
            ap.error("cross wants the wave file, the csv to write and, for "
                     "a one-ring deck, the ring")
        return cmd_cross(*a.args)
    if a.cmd == "check":
        return cmd_check(a.dir)
    bad = claims(cmd_report(a.dir))
    print("\n%s" % ("FAIL: %d of the claims above" % len(bad) if bad else
                    "PASS: every claim above holds on the archived runs"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
