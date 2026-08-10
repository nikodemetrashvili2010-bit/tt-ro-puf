#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Independent re-derivation of item D, the Arm B per-instance result at corners.

`verify_instance.py` does this job for tt and does it in detail, 37 checks
against the routed netlist and the SPEF. This script is the corner half. It
imports nothing from that file, from the analyzer or from the generator, and
reads the three archived logs directly with its own parser and its own Pearson.

It is deliberately not a copy of the tt verifier with two more tables bolted
on. Running the numbers after the two corner runs showed why. At ss the spread
across the sixteen instances is 1.3e-6 of the mean, and the log's own two ways
of stating a frequency, the `f_` line and twenty periods divided into `tp_`,
disagree at 1.6e-7. That is eight times of headroom. The spread is real, it is
above the noise in the log, but its third significant figure depends on which
definition you read, so this script will not assert that figure. What it
asserts is what survives: the spread is far under the 0.01 percent written down
before the runs, far under one count of the on-chip counter, and orders below
Arm A at the same corner. Those hold at every corner with margin to spare.

The cross-corner checks are the part that could not exist before item D. A
single corner cannot tell a real effect from solver noise. Three can, and two
of the checks below are exactly that test.

Run:
    python3 verify_instance_corners.py
    python3 verify_instance_corners.py --selftest
"""
import argparse
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

NRO = 16
EDGES = 20                 # the deck measures from edge 5 to edge 25
WINDOW, FREF = 1000, 25e6  # the counter window the RTL uses

LOGS = {
    "tt": "armb_instances_out.txt",
    "ss": "armb_instances_ss_out.txt",
    "ff": "armb_instances_ff_out.txt",
}

# The Arm A control every other deck in this project lands on, per corner.
ARCHIVED_CTRL = {"tt": 633.640, "ss": 323.140, "ff": 987.948}

# Arm A's own peak-to-peak layout spread at each corner. tt is the distributed
# RC figure from item 7; ss and ff have no distributed Arm A run, so they use
# the lumped corner decks, which are the smaller numbers and therefore make the
# comparison stricter rather than easier.
ARM_A_PP = {"tt": 5.84, "ss": 5.459, "ff": 5.559}

# Written down in armb_corner_run_steps.md before either corner was run.
PREDICTED_CEILING = 0.01

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS  " + name + (("   [" + detail + "]") if detail else ""))
    else:
        fail += 1
        print("FAIL  " + name + (("   [" + detail + "]") if detail else ""))


def pearson(xs, ys):
    """Written out rather than imported, so it cannot share a bug with anything."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy)


def read_measurements(path):
    """Every '<name> = <value>' ngspice prints, keyed by name."""
    out = {}
    pat = re.compile(r"^([a-z][a-z0-9_]*)\s*=\s*([-+0-9.eE]+)")
    for line in open(path, errors="replace"):
        m = pat.match(line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def read_out_caps(path):
    rows = [r.split(",") for r in open(path).read().strip().splitlines()]
    head = rows[0]
    caps = {}
    for r in rows[1:]:
        d = dict(zip(head, r))
        caps[int(d["instance"])] = float(d["out_cap_fF"])
    return [caps[k] for k in range(NRO)]


def reduce_log(m):
    """Everything the checks below need, derived once from one log."""
    tags = ["c", "r"] + ["k%02d" % k for k in range(NRO)]
    d = {}
    d["tags"] = tags
    d["n_freq"] = len([k for k in m if k.startswith("f_")])
    d["finite"] = all(math.isfinite(v) for v in m.values())
    # A log with a ring missing must reach its own check below rather than
    # crash here, so everything derived is taken over what is actually present.
    present = [t for t in tags if ("f_" + t) in m and ("tp_" + t) in m]
    d["missing"] = [t for t in tags if t not in present]
    # The two ways this log states a frequency. Their disagreement is the
    # resolution floor every other number here has to be read against.
    d["selfcons"] = max(abs(EDGES / m["tp_" + t] - m["f_" + t]) / m["f_" + t]
                        for t in present)
    d["fc"] = EDGES / m["tp_c"] / 1e6
    d["fr"] = EDGES / m["tp_r"] / 1e6
    fk = [EDGES / m["tp_k%02d" % k] / 1e6 for k in range(NRO)
          if ("k%02d" % k) not in d["missing"]]
    d["fk"] = fk
    d["mean"] = st.fmean(fk)
    d["pp"] = 100.0 * (max(fk) - min(fk)) / d["mean"]
    d["delay"] = [m["dr_k%02d" % k] * 1e12 for k in range(NRO)]
    d["slew"] = ([m["sm_k%02d" % k] * 1e12 for k in range(NRO)]
                 + [m["sr_k%02d" % k] * 1e12 for k in range(NRO)])
    # Every output route has to hand back the period it was given, or the
    # frequency comparison downstream is meaningless.
    d["route_kept_period"] = [
        k for k in range(NRO)
        if abs(m["tp_k%02d" % k] - m["tq_k%02d" % k]) / m["tp_k%02d" % k] > 1e-6]
    return d


def run(logdir, csvpath):
    caps = read_out_caps(csvpath)
    D = {}
    for corner, name in LOGS.items():
        D[corner] = reduce_log(read_measurements(os.path.join(logdir, name)))
        n = len(D[corner]["fk"])
        D[corner]["r_f"] = pearson(caps[:n], D[corner]["fk"])
        D[corner]["r_d"] = pearson(caps[:len(D[corner]["delay"])], D[corner]["delay"])

    print("== each corner's log is complete and self-consistent ==")
    for c in ("ss", "tt", "ff"):
        d = D[c]
        check("%s: all 18 rings reported a frequency" % c,
              d["n_freq"] == 18 and not d["missing"],
              "%d present, missing %s" % (d["n_freq"], d["missing"] or "none"))
        check("%s: no measurement came back as a failed ngspice result" % c,
              d["finite"])
        check("%s: every output route handed back the period it was given" % c,
              not d["route_kept_period"], str(d["route_kept_period"]))
        check("%s: the control lands on the archived control within one percent" % c,
              abs(d["fc"] - ARCHIVED_CTRL[c]) / ARCHIVED_CTRL[c] < 0.01,
              "%.3f against %.3f, %+.3f%%"
              % (d["fc"], ARCHIVED_CTRL[c], 100 * (d["fc"] - ARCHIVED_CTRL[c])
                 / ARCHIVED_CTRL[c]))

    print("\n== how much of the spread is real, corner by corner ==")
    for c in ("ss", "tt", "ff"):
        d = D[c]
        headroom = (d["pp"] / 100.0) / d["selfcons"]
        check("%s: the spread sits above the log's own resolution, so it is not "
              "print rounding" % c, headroom > 5.0,
              "spread %.2e, log agrees with itself to %.2e, %.1fx headroom"
              % (d["pp"] / 100.0, d["selfcons"], headroom))
    check("ss has the least headroom of the three, so its last digits are the "
          "ones not to quote",
          (D["ss"]["pp"] / 100.0) / D["ss"]["selfcons"]
          == min((D[c]["pp"] / 100.0) / D[c]["selfcons"] for c in D),
          "%.1fx against %.1fx at tt and %.1fx at ff"
          % tuple((D[c]["pp"] / 100.0) / D[c]["selfcons"] for c in ("ss", "tt", "ff")))

    print("\n== the claims that survive that, at every corner ==")
    for c in ("ss", "tt", "ff"):
        d = D[c]
        check("%s: under the %.2f percent written down before the runs" % (c, PREDICTED_CEILING),
              d["pp"] < PREDICTED_CEILING, "%.4f" % d["pp"])
        periods = d["mean"] * 1e6 * WINDOW / FREF
        one_count = 100.0 / periods
        check("%s: the whole spread is smaller than one count of the counter" % c,
              d["pp"] < one_count,
              "%.4f percent against %.4f per count, %.2f counts"
              % (d["pp"], one_count, d["pp"] / one_count))
        check("%s: at least a hundred times under Arm A on the same build" % c,
              ARM_A_PP[c] / d["pp"] > 100, "%.0f times" % (ARM_A_PP[c] / d["pp"]))

    print("\n== what three corners can decide that one could not ==")
    lo = [min(D[c]["delay"]) for c in ("ss", "tt", "ff")]
    hi = [max(D[c]["delay"]) for c in ("ss", "tt", "ff")]
    check("route delay does not move with the corner, because the RC network is "
          "the same bytes at all three", max(hi) - min(hi) < 0.2 and max(lo) - min(lo) < 0.2,
          "%.1f to %.1f at ss, tt, ff" % (min(lo), max(hi)))
    rd = [D[c]["r_d"] for c in ("ss", "tt", "ff")]
    check("and its correlation with route capacitance holds to three decimals "
          "across corners", max(rd) - min(rd) < 0.005,
          "%+.3f %+.3f %+.3f" % tuple(rd))
    rf = [D[c]["r_f"] for c in ("ss", "tt", "ff")]
    check("frequency against route capacitance changes sign between corners, "
          "which is what noise does and a real load does not",
          not (all(x > 0 for x in rf) or all(x < 0 for x in rf)),
          "%+.3f %+.3f %+.3f at ss, tt, ff" % tuple(rf))

    # This started out as three t-tests, one per corner, copied from the tt
    # verifier. ff failed it: t = 2.40 against a 2.145 critical value, so the
    # correlation there is nominally significant at 14 degrees of freedom. I
    # had already told myself the wandering sign settled the question, and it
    # does not. What settles it is size, not significance. The output route
    # sits outside the oscillator loop by construction, so the honest test is
    # how much frequency the correlation would account for if you took it at
    # face value, expressed in the only unit the chip has, one counter count.
    for c in ("ss", "tt", "ff"):
        d = D[c]
        n = NRO
        use = caps[:len(d["fk"])]
        mx, my = st.fmean(use), st.fmean(d["fk"])
        sxy = sum((x - mx) * (y - my) for x, y in zip(use, d["fk"]))
        sxx = sum((x - mx) ** 2 for x in use)
        swing = (sxy / sxx) * (max(use) - min(use))
        periods = d["mean"] * 1e6 * WINDOW / FREF
        counts = abs(swing) / d["mean"] * periods
        t = abs(d["r_f"]) * math.sqrt(n - 2) / math.sqrt(1 - d["r_f"] ** 2)
        check("%s: taken at face value the whole 2.89 to 29.46 fF span buys "
              "under a fifth of one counter count" % c, counts < 0.2,
              "r %+.3f, t %.3f, %.4f counts" % (d["r_f"], t, counts))
    t_ff = abs(D["ff"]["r_f"]) * math.sqrt(NRO - 2) / math.sqrt(1 - D["ff"]["r_f"] ** 2)
    check("ff does reach nominal significance, recorded here so nobody repeats "
          "my mistake of reading one corner's insignificance as an answer",
          t_ff > 2.1448, "t = %.3f against 2.145" % t_ff)
    ratio = [max(D[c]["slew"]) / max(D["tt"]["slew"]) for c in ("ss", "ff")]
    period = [D["tt"]["mean"] / D[c]["mean"] for c in ("ss", "ff")]
    check("receiver slew scales with the devices, not with the ring period",
          all(abs(r - p) > 0.05 for r, p in zip(ratio, period)),
          "slew x%.3f and x%.3f against period x%.3f and x%.3f"
          % (ratio[0], ratio[1], period[0], period[1]))

    print("\n== the control shift, which is where my prediction failed ==")
    shift = {c: (D[c]["fc"] - ARCHIVED_CTRL[c]) / ARCHIVED_CTRL[c] * 100
             for c in D}
    check("ss came in below its archived control, which is the sign I said "
          "would kill the timestep explanation", shift["ss"] < 0,
          "%+.3f percent" % shift["ss"])
    # Fit shift = a + b*f^2 on the two outer corners only and keep tt back.
    f = {c: D[c]["fc"] / 1000.0 for c in D}
    b = (shift["ff"] - shift["ss"]) / (f["ff"] ** 2 - f["ss"] ** 2)
    a = shift["ss"] - b * f["ss"] ** 2
    tt_hat = a + b * f["tt"] ** 2
    check("a square law in frequency fitted on ss and ff alone predicts the "
          "held-out tt shift", abs(tt_hat - shift["tt"]) < 0.01,
          "predicted %+.4f, measured %+.4f, error %+.4f points"
          % (tt_hat, shift["tt"], tt_hat - shift["tt"]))
    check("but the fit does not pass through zero, so part of the shift is not "
          "a timestep effect at all", abs(a) > 0.05,
          "constant term %+.4f percent, square term %+.4f" % (a, b))

    print()
    print("== SUMMARY ==  %d passed, %d failed" % (ok, fail))
    for c in ("ss", "tt", "ff"):
        print("%s  mean %9.3f MHz, spread %.4f percent peak to peak, %.0f times "
              "under Arm A" % (c, D[c]["mean"], D[c]["pp"], ARM_A_PP[c] / D[c]["pp"]))
    return fail == 0


def selftest():
    """Plant a fault for each group and confirm exactly the right check fails."""
    import shutil
    import tempfile
    global ok, fail

    def attempt(mutate, label):
        global ok, fail
        tmp = tempfile.mkdtemp()
        for c, name in LOGS.items():
            shutil.copy(os.path.join(HERE, name), os.path.join(tmp, name))
        csv = os.path.join(tmp, "instance_parasitics.csv")
        shutil.copy(os.path.join(HERE, "instance_parasitics.csv"), csv)
        mutate(tmp, csv)
        ok = fail = 0
        out = io_capture(lambda: run(tmp, csv))
        shutil.rmtree(tmp, ignore_errors=True)
        return fail, out

    def io_capture(fn):
        import contextlib
        import io as _io
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn()
        return buf.getvalue()

    def drop_a_ring(d, csv):
        p = os.path.join(d, LOGS["ss"])
        t = open(p, errors="replace").read()
        open(p, "w").write(re.sub(r"^f_k07\s*=.*$", "", t, flags=re.M))

    def move_the_control(d, csv):
        p = os.path.join(d, LOGS["ff"])
        t = open(p, errors="replace").read()
        m = re.search(r"^tp_c\s*=\s*(\S+)", t, re.M)
        new = float(m.group(1)) * 1.05
        open(p, "w").write(re.sub(r"^tp_c\s*=\s*\S+", "tp_c = %.6e" % new, t,
                                  flags=re.M))

    def widen_the_spread(d, csv):
        p = os.path.join(d, LOGS["ss"])
        t = open(p, errors="replace").read()
        m = re.search(r"^tp_k03\s*=\s*(\S+)", t, re.M)
        new = float(m.group(1)) * 1.02
        open(p, "w").write(re.sub(r"^tp_k03\s*=\s*\S+", "tp_k03 = %.6e" % new, t,
                                  flags=re.M))

    def make_the_correlation_agree(d, csv):
        # Give all three corners the same sign, which is what a real load on the
        # ring would look like. Doing it to one corner only, which is what I
        # tried first, does not test this check at all: ff is strongly positive,
        # so flipping ss still leaves the signs mixed and the check still passes,
        # correctly. A planted fault has to actually produce the thing the check
        # denies.
        caps = read_out_caps(csv)
        for corner in LOGS:
            p = os.path.join(d, LOGS[corner])
            t = open(p, errors="replace").read()
            for k in range(NRO):
                m = re.search(r"^tp_k%02d\s*=\s*(\S+)" % k, t, re.M)
                new = float(m.group(1)) * (1.0 + 3e-7 * (caps[k] - 14.46))
                t = re.sub(r"^tp_k%02d\s*=\s*\S+" % k,
                           "tp_k%02d = %.9e" % (k, new), t, flags=re.M)
            open(p, "w").write(t)

    def break_a_route(d, csv):
        p = os.path.join(d, LOGS["ff"])
        t = open(p, errors="replace").read()
        m = re.search(r"^tq_k05\s*=\s*(\S+)", t, re.M)
        new = float(m.group(1)) * 1.01
        open(p, "w").write(re.sub(r"^tq_k05\s*=\s*\S+", "tq_k05 = %.6e" % new, t,
                                  flags=re.M))

    planted = [
        (drop_a_ring, "a ring missing from the ss log", "all 18 rings"),
        (move_the_control, "the ff control off by five percent", "the control lands"),
        (widen_the_spread, "one ss instance two percent off the rest", "under the 0.01"),
        (make_the_correlation_agree, "ss made to correlate the way tt does",
         "changes sign between corners"),
        (break_a_route, "an ff output route that lost its period",
         "handed back the period"),
    ]
    bad = 0
    for mutate, label, expect in planted:
        nfail, out = attempt(mutate, label)
        caught = any(line.startswith("FAIL") and expect in line
                     for line in out.splitlines())
        status = "ok  " if (nfail > 0 and caught) else "MISS"
        if status == "MISS":
            bad += 1
        print("  %s  %-45s expected the %r check to fail, %d check(s) failed"
              % (status, label, expect, nfail))
    ok = fail = 0
    clean, _ = 0, None
    nfail, _ = attempt(lambda d, c: None, "no fault at all")
    print("  %s  %-45s expected nothing to fail, %d did"
          % ("ok  " if nfail == 0 else "MISS", "the archived logs untouched", nfail))
    if nfail:
        bad += 1
    print("\nselftest: %d planted case(s) behaved wrongly" % bad)
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dir", default=HERE)
    args = ap.parse_args()
    if args.selftest:
        return 0 if selftest() else 1
    good = run(args.dir, os.path.join(args.dir, "instance_parasitics.csv"))
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
