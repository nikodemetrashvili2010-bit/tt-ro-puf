#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Read the per-instance Arm B run, hardware item 8.

The deck from gen_instance_decks.py puts eighteen rings in one file: a control
with no capacitance, a reference carrying only the macro's own extraction, and
the sixteen real instances carrying their own enable and output routes on top of
that same reference model. This turns that log into the answer to one question,
whether the sixteen copies of Arm B really behave as one number once they are
wired into the chip.

Nothing below can be read until four things hold, so all four are tested here.

The control ring has to return the frequency every other control deck in this
project returns at that corner. Landing there is what says the deck was built
right, and not merely built consistently with itself.

Eighteen rings went in, so eighteen results have to come out. When ngspice
cannot make a measurement it leaves the name out of the log altogether. An absent
name is a ring that never started, not a ring reading zero.

A route has to show one period at both of its ends. Resistors and capacitors
delay an edge, they do not retime it. Two different periods mean the measurement
is not reading what it claims to.

Last, the widths have to close. Whatever high level the route gains has to match
the fall delay minus the rise delay, which is arithmetic and not physics. That
check is here because item 2 shipped a wrong number for two days by comparing a
high level against a low one.

Then the result. The spread across the sixteen instances goes against two numbers
already in the repository. Both are written down here before the run rather than
chosen after it.

  5.84%   Arm A's dispersion from the distributed-RC decks, item 7. If Arm B's
          per-instance spread reached anything like this, the two arms would no
          longer be measuring different things and the experiment would be over.
  0.062%  the per-ring mismatch sigma from the Monte Carlo work, which is the
          real entropy the PUF is supposed to live on. Ten times that, 0.62%, is
          the level above which integration spread would be worth reporting as a
          limitation rather than a footnote.

Usage:
    python3 analyze_instance.py --log /tmp/inst/armb_instances_out.txt \\
        --csv /tmp/inst/instance_parasitics.csv
    python3 analyze_instance.py --selftest
"""

import argparse
import csv
import math
import os
import re
import statistics as st
import sys

NRO = 16

# Control frequency of a ring with no parasitics, per corner, from the archived
# go/no-go logs. The transient timestep moves these by about 0.2%, so the check
# is a tolerance and not an equality.
CONTROL_MHZ = {"tt": 633.640, "ss": 323.140, "ff": 987.948}
CONTROL_TOL = 0.01

ARM_A_DISPERSION = 5.84      # item 7, distributed RC, peak to peak
MISMATCH_SIGMA = 0.062       # Monte Carlo, per-ring, percent
FLAG_LEVEL = 10 * MISMATCH_SIGMA

PERIOD_TOL_PS = 1.0          # a passive route cannot move a period at all
IDENTITY_TOL_PS = 2.0        # two interpolated meas values, so allow a picosecond each


def read_log(path):
    """Every meas and print value in an ngspice log, keyed by name.

    ngspice writes a meas result as `name  =  value targ= .. trig= ..` and a
    printed vector as `name = value`, so one pattern anchored at the start of the
    line reads both.
    """
    txt = open(path, errors="ignore").read()
    out = {}
    for name, val in re.findall(r'^(\w+)\s*=\s*(-?[0-9.]+(?:[eE][+-]?\d+)?)', txt, re.M):
        out[name] = float(val)
    return out


def read_csv(path):
    rows = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            rows[int(row["instance"])] = row
    return rows


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def analyse(vals, corner, loads=None):
    """Return (report lines, failures, flags, numbers)."""
    lines, fail, flag = [], [], []
    ps = 1e12

    # A measurement ngspice could not make is absent from the log rather than
    # zero, so every name this report needs is checked up front. Reading on with
    # a name missing would either crash or, worse, quietly drop a ring.
    need = ["f_c", "f_r", "tp_c", "tp_r"]
    for k in range(NRO):
        t = "k%02d" % k
        need += ["%s_%s" % (p, t) for p in
                 ("f", "tp", "tq", "hi", "hx", "dr", "df", "sm", "sr")]
    missing = [n for n in need if n not in vals]
    if missing:
        rings = sorted({n.split("_", 1)[1] for n in missing})
        fail.append("%d measurement(s) are absent from the log, covering ring(s) %s. "
                    "A ring with no result did not oscillate, or the transient was "
                    "too short to hold the edges the measurement asks for. Missing: %s"
                    % (len(missing), ", ".join(rings),
                       ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else "")))
        return lines, fail, flag, {}

    ctrl = vals["f_c"] / 1e6
    ref = vals["f_r"] / 1e6
    want = CONTROL_MHZ[corner]
    lines.append("control ring, no capacitance anywhere: %.3f MHz "
                 "(archived %s control %.3f)" % (ctrl, corner, want))
    if abs(ctrl - want) / want > CONTROL_TOL:
        fail.append("the control ring reads %.3f MHz where every other %s control "
                    "deck in this project returns %.3f. The deck is not comparable "
                    "to the rest of the flow, so nothing below can be read."
                    % (ctrl, corner, want))
    lines.append("reference ring, macro extraction only: %.3f MHz" % ref)
    lines.append("")

    freqs, rows = [], []
    for k in range(NRO):
        t = "k%02d" % k
        f = vals["f_%s" % t] / 1e6
        freqs.append(f)
        tp, tq = vals["tp_%s" % t] * ps, vals["tq_%s" % t] * ps
        hi, hx = vals["hi_%s" % t] * ps, vals["hx_%s" % t] * ps
        dr, df = vals["dr_%s" % t] * ps, vals["df_%s" % t] * ps
        sm, sr = vals["sm_%s" % t] * ps, vals["sr_%s" % t] * ps
        rows.append(dict(k=k, f=f, tp=tp, tq=tq, hi=hi, hx=hx, dr=dr, df=df,
                         sm=sm, sr=sr))

        if abs(tq - tp) > PERIOD_TOL_PS:
            fail.append("instance %d: the period is %.1f ps at the macro pin and "
                        "%.1f ps at the far end of its output route. A resistor and "
                        "capacitor network cannot change a period, so this "
                        "measurement is not reading what it claims to."
                        % (k, tp, tq))
        widened = hx - hi
        by_delay = df - dr
        if abs(widened - by_delay) > IDENTITY_TOL_PS:
            fail.append("instance %d: the high level grows by %.1f ps along the "
                        "route while the fall lags the rise by %.1f ps. Those are "
                        "the same quantity, so one of the two is measured on the "
                        "wrong edge." % (k, widened, by_delay))
        period = tp / 20.0
        if max(dr, df) > 0.25 * period:
            fail.append("instance %d: the route delay reaches %.1f ps against a "
                        "%.1f ps period, which is far past a routing delay and "
                        "means the edges being compared are not the same edge."
                        % (k, max(dr, df), period))

    mean = st.mean(freqs)
    ptp = 100 * (max(freqs) - min(freqs)) / mean
    sd = 100 * st.pstdev(freqs) / mean
    off = 100 * (mean - ref) / ref

    lines.append("the sixteen instances")
    lines.append("  %-4s %10s %9s %9s %9s %9s %9s" %
                 ("inst", "MHz", "vs ref %", "route ps", "asym ps", "slew in", "slew out"))
    for r in rows:
        lines.append("  %-4d %10.3f %9.4f %9.1f %9.1f %9.1f %9.1f"
                     % (r["k"], r["f"], 100 * (r["f"] - ref) / ref,
                        r["dr"], r["df"] - r["dr"], r["sm"], r["sr"]))
    lines.append("")
    lines.append("frequency across the sixteen: %.3f to %.3f MHz, mean %.3f"
                 % (min(freqs), max(freqs), mean))
    lines.append("peak to peak %.4f%%, standard deviation %.4f%%, mean sits %.4f%% "
                 "off the reference" % (ptp, sd, off))
    if ptp:
        lines.append("Arm A on this build spreads %.2f%% peak to peak with the same "
                     "distributed-RC treatment of its routes, so integration spread "
                     "is %.0f times smaller"
                     % (ARM_A_DISPERSION, ARM_A_DISPERSION / ptp))
    else:
        lines.append("the sixteen agree to every digit the measurement resolves, "
                     "against Arm A's %.2f%% on this build" % ARM_A_DISPERSION)

    drs = [r["dr"] for r in rows]
    srs = [r["sr"] for r in rows]
    lines.append("")
    lines.append("route delay %.1f to %.1f ps, receiver edge %.1f to %.1f ps"
                 % (min(drs), max(drs), min(srs), max(srs)))

    if loads:
        cap = [float(loads[r["k"]]["out_cap_fF"]) for r in rows]

        def corr(name, ys):
            r = pearson(cap, ys)
            if math.isnan(r):
                return "%s does not vary, so no correlation is defined" % name
            return "%s r = %+.3f" % (name, r)

        lines.append("output route capacitance against " + ", ".join(
            [corr("frequency", freqs), corr("route delay", drs),
             corr("receiver edge", srs)]))

    if ptp >= ARM_A_DISPERSION:
        fail.append("the sixteen instances spread %.3f%%, which is not below Arm A's "
                    "%.2f%%. Integration would then be doing what the layout does "
                    "and the two arms would no longer measure different things."
                    % (ptp, ARM_A_DISPERSION))
    elif ptp > FLAG_LEVEL:
        flag.append("the sixteen instances spread %.3f%%, above the %.3f%% level "
                    "that is ten times the per-ring mismatch sigma. Not fatal, but "
                    "it belongs in the paper as a limitation rather than a footnote."
                    % (ptp, FLAG_LEVEL))

    return lines, fail, flag, dict(ctrl=ctrl, ref=ref, ptp=ptp, sd=sd, rows=rows)


# ------------------------------------------------------------------- self test

def synth(**tweak):
    """A synthetic log with the shape ngspice writes, optionally broken on purpose."""
    period_ps = 1755.0
    v = {"f_c": 633.640e6, "f_r": 569.500e6,
         "tp_c": 20.0 / 633.640e6, "tp_r": 20.0 / 569.500e6,
         "hi_c": period_ps / 2 * 1e-12, "hi_r": period_ps / 2 * 1e-12}
    lines = []
    for k in range(NRO):
        t = "k%02d" % k
        f = 569.500e6 * (1 + (k - 7.5) * tweak.get("slope", 0.0))
        tp = 20.0 / f
        dr = 2.0 + 0.3 * k
        df = dr + 1.5
        hi = period_ps / 2 * 1e-12
        hx = hi + (df - dr) * 1e-12
        v["f_%s" % t] = f
        v["tp_%s" % t] = tp
        v["tq_%s" % t] = tp
        v["hi_%s" % t] = hi
        v["hx_%s" % t] = hx
        v["dr_%s" % t] = dr * 1e-12
        v["df_%s" % t] = df * 1e-12
        v["sm_%s" % t] = 90e-12
        v["sr_%s" % t] = 95e-12
    for key, val in tweak.get("set", {}).items():
        v[key] = val
    for key in tweak.get("drop", []):
        v.pop(key, None)
    for name, val in v.items():
        if name.startswith("f_"):
            lines.append("%s = %.6e" % (name, val))
        else:
            lines.append("%-20s=  %.6e targ=  1.0e-08 trig=  1.0e-08" % (name, val))
    return "\n".join(lines) + "\n"


def selftest():
    import tempfile
    cases = [
        ("a clean run", {}, "pass"),
        ("a ring that never started", dict(drop=["f_k09", "tp_k09"]), "fail"),
        ("a control ring off by five percent",
         dict(set={"f_c": 633.640e6 * 1.05}), "fail"),
        ("a period that changed along a passive route",
         dict(set={"tq_k03": 20.0 / 569.5e6 + 40e-12}), "fail"),
        ("a high level compared against a low, item 2's mistake",
         dict(set={"hx_k11": 900e-12}), "fail"),
        ("a route delay the size of a quarter period, so a lost edge",
         dict(set={"dr_k02": 500e-12, "df_k02": 501.5e-12}), "fail"),
        ("a spread that erases the difference between the arms",
         dict(slope=0.006), "fail"),
        ("a spread in the band worth reporting", dict(slope=0.0006), "flag"),
    ]
    ok = True
    for name, tweak, want in cases:
        fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        fh.write(synth(**tweak))
        fh.close()
        _, fail, flag, _ = analyse(read_log(fh.name), "tt")
        os.unlink(fh.name)
        got = "fail" if fail else ("flag" if flag else "pass")
        mark = "ok  " if got == want else "WRONG"
        if got != want:
            ok = False
        print("  %s %-58s expected %-4s got %s" % (mark, name, want, got))
        if got != want:
            for m in fail + flag:
                print("        " + m)
    print("selftest: %s" % ("all 8 planted cases behaved" if ok else "SOMETHING IS WRONG"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", help="ngspice log from armb_instances.spice")
    ap.add_argument("--csv", help="instance_parasitics.csv from the generator")
    ap.add_argument("--corner", default="tt", choices=sorted(CONTROL_MHZ))
    ap.add_argument("--selftest", action="store_true",
                    help="run the planted-fault cases and exit; needs no log, no "
                         "PDK and no ngspice")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.log:
        ap.error("--log is required unless --selftest is given")

    loads = read_csv(args.csv) if args.csv else None
    lines, fail, flag, _ = analyse(read_log(args.log), args.corner, loads)
    for line in lines:
        print(line)
    print()
    for m in flag:
        print("FLAG: " + m)
    for m in fail:
        print("FAIL: " + m)
    if fail:
        return 1
    print("PASS: the control is where it should be, every ring ran, every route "
          "preserved its period, and the widths close.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
