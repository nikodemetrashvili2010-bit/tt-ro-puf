#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Hardware item 5, read: what a resistive supply does to each arm.

The decks come from gen_supply_decks.py, eight series resistances per arm across
four decades. This reads them and answers three questions in order.

First, does the deck do what it claims. If the supply the cells actually see does
not fall as the resistance rises, the resistor is not in the circuit and every
number below is a flat line that means nothing.

Second, does the frequency respond the way the independent supply work says it
should. The 2026-07-29 sweep measured 105.9 percent per volt by moving an ideal
supply. Here the supply moves because the ring's own current drops it, which is a
different mechanism, and the two have to agree. If they do not, one of them is
wrong.

Third, the actual question. The resistances that matter are set by the layout,
not by me, so they are computed here from the shipped DEF and the PDK's own sheet
resistances rather than assumed: 0.48 um met1 rails at 0.125 ohm per square for
Arm A, 2.4 um met4 straps at 0.047 for Arm B, both measured out of
dualarm/build_current. The verdict is then read off the sweep at those
resistances, and because the sweep spans four decades it is still readable if my
geometry is wrong by a factor of ten.

Run:
    python3 analyze_supply.py --dir /tmp/supply
    python3 analyze_supply.py --selftest
"""
import argparse
import math
import os
import re
import sys

OHMS = (0.000001, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0)
SUPPLY = 1.80

# measured independently on 2026-07-29 by moving an ideal supply
PUSH_INDEPENDENT = 105.9      # percent per volt
# what the result has to be compared against
ONE_COUNT = 100.0 / 22826.0   # one counter count, percent of frequency
SIGMA_MISMATCH = 0.062        # per-ring transistor mismatch, percent
ARM_A_SPREAD = 5.84           # Arm A dispersion on this build, percent

# straight out of dualarm/build_current: DEF widths in dbu, tech LEF sheet
# resistances in ohm per square
RSH = {"met1": 0.125, "met4": 0.047}
W_MET1_RAIL_UM = 0.480        # DEF SPECIALNETS met1 width 480 dbu
W_MET4_STRAP_UM = 2.400       # DEF SPECIALNETS met4 width 2400 dbu
MET4_PITCH_UM = 60.0          # validated PDN pitch
CORE_HEIGHT_UM = 220.8        # met4 stripes run y 2.48 to 223.28


def parse_log_text(text, path="a log"):
    """tp, average current, average local supply and frequency from one log.

    The current is the one number here that can come back wrong instead of
    coming back missing, which is how the first run of this sweep wasted an
    evening. A deck whose .save line does not name the supply current leaves
    ngspice with no such vector, and what arrives here is a clean zero rather
    than an error. So a zero is rejected at the door. A ring that is oscillating
    draws tens of microamps, and if this file ever sees one that does not, the
    measurement did not happen and no verdict below it means anything.
    """
    out = {}
    for key in ("tp", "idd", "vlocal"):
        m = re.search(r"^\s*%s\s*=\s*([-+0-9.eE]+)" % key, text, re.M)
        if m:
            out[key] = float(m.group(1))
    m = re.search(r"^f\s*=\s*([-+0-9.eE]+)", text, re.M)
    if m:
        out["f"] = float(m.group(1)) / 1e6
    if len(out) != 4:
        return None
    if not math.isfinite(out["idd"]) or abs(out["idd"]) < 1e-9:
        raise SystemExit(
            "%s reports a supply current of %g A, which no running ring draws. "
            "The measurement did not happen. Check that the deck's .save line "
            "names i(Vdd), since that is what puts vdd#branch in the plot."
            % (path, out["idd"]))
    return out


def read_log(path):
    if not os.path.exists(path):
        return None
    return parse_log_text(open(path, errors="replace").read(), path)


def read_arm(directory, arm):
    rows = []
    for k, ohms in enumerate(OHMS):
        d = read_log(os.path.join(directory, "supply_%s_r%d_out.txt" % (arm, k)))
        if d is None:
            raise SystemExit("supply_%s_r%d_out.txt is missing or incomplete, so "
                             "the sweep has a hole in it" % (arm, k))
        rows.append((ohms, abs(d["idd"]), d["vlocal"], d["f"]))
    return rows


def path_resistance():
    """Worst-case supply path resistance for each arm, from the shipped layout.

    Arm A: a cell can sit half a stripe pitch from the nearest met4 stripe and
    reach it only along the met1 row rail. At the die edge that rail is fed from
    one side, which is the worst case; in the middle of the array it is fed from
    both and the resistance halves.

    Arm B: the macro's power pins are met4 stripes that the parent grid runs
    over. The stripe is fed from the Tiny Tapeout met5 grid above, and the worst
    a macro can sit is the far end of one stripe.
    """
    a = RSH["met1"] * (MET4_PITCH_UM / 2.0) / W_MET1_RAIL_UM
    b = RSH["met4"] * CORE_HEIGHT_UM / W_MET4_STRAP_UM
    return a, b


def interp(rows, ohms):
    """Frequency shift in percent at a resistance between two swept points."""
    f0 = rows[0][3]
    xs = [r[0] for r in rows]
    ys = [100.0 * (r[3] - f0) / f0 for r in rows]
    if ohms <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if ohms <= xs[i]:
            t = (math.log(ohms) - math.log(xs[i - 1])) / \
                (math.log(xs[i]) - math.log(xs[i - 1]))
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def report(rows_a, rows_b):
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print("PASS  " + name + (("   [" + detail + "]") if detail else ""))
        else:
            fail += 1
            print("FAIL  " + name + (("   [" + detail + "]") if detail else ""))

    for arm, rows in (("Arm A, distributed RC ring", rows_a),
                      ("Arm B, macro ring", rows_b)):
        print("\n%s" % arm)
        print("    ohm      current uA   supply at cells V   MHz      shift %")
        f0 = rows[0][3]
        for ohms, idd, vloc, f in rows:
            print("  %8.6g %12.1f %17.4f %9.3f %+10.4f"
                  % (ohms, idd * 1e6, vloc, f, 100.0 * (f - f0) / f0))

    print("\n== is the resistor actually in the circuit ==")
    for arm, rows in (("Arm A", rows_a), ("Arm B", rows_b)):
        drop = rows[0][2] - rows[-1][2]
        check("%s: the supply at the cells falls as the resistance rises" % arm,
              drop > 0.01, "%.4f V across the sweep" % drop)

    print("\n== does Ohm's law close at every point ==")
    for arm, rows in (("Arm A", rows_a), ("Arm B", rows_b)):
        worst, at = 0.0, OHMS[0]
        for ohms, idd, vloc, _ in rows:
            predicted = SUPPLY - idd * ohms
            err = abs(predicted - vloc)
            if err > worst:
                worst, at = err, ohms
        check("%s: measured supply equals 1.8 minus I times R" % arm,
              worst < 0.01, "worst %.4f V at %g ohm" % (worst, at))

    print("\n== does it agree with the independent supply measurement ==")
    for arm, rows in (("Arm A", rows_a), ("Arm B", rows_b)):
        f0, v0 = rows[0][3], rows[0][2]
        pts = [(v0 - vloc, 100.0 * (f0 - f) / f0)
               for ohms, idd, vloc, f in rows if 0.002 < (v0 - vloc) < 0.10]
        if not pts:
            check("%s: enough small-drop points to fit a slope" % arm, False)
            continue
        slope = sum(dy for _, dy in pts) / sum(dv for dv, _ in pts)
        check("%s: implied pushing figure is within five percent of the 105.9 "
              "measured on 2026-07-29" % arm,
              abs(slope - PUSH_INDEPENDENT) / PUSH_INDEPENDENT < 0.05,
              "%.1f percent per volt from %d points" % (slope, len(pts)))
        check("%s: a heavier supply resistance makes the ring slower, not faster"
              % arm, slope > 0, "%+.1f" % slope)

    ra, rb = path_resistance()
    print("\n== the resistances the shipped layout actually has ==")
    print("Arm A, %.2f um of 0.48 um met1 rail at %.3f ohm per square: %.2f ohm"
          % (MET4_PITCH_UM / 2.0, RSH["met1"], ra))
    print("Arm B, %.1f um of 2.4 um met4 stripe at %.3f ohm per square: %.2f ohm"
          % (CORE_HEIGHT_UM, RSH["met4"], rb))
    sa, sb = interp(rows_a, ra), interp(rows_b, rb)
    print("frequency shift there: Arm A %+.4f percent, Arm B %+.4f percent"
          % (sa, sb))
    gap = abs(sa - sb)
    print("arm to arm difference: %.4f percent" % gap)

    print("\n== what that difference is worth ==")
    check("both arms sit in the first decade of the sweep, so the four decades "
          "bracket the real layout with room to spare",
          ra < 100 and rb < 100, "%.1f and %.1f ohm" % (ra, rb))
    check("the arm to arm difference stays under Arm A's own dispersion by more "
          "than two orders of magnitude", gap < ARM_A_SPREAD / 100.0,
          "%.4f against %.2f percent" % (gap, ARM_A_SPREAD))
    check("it stays under the transistor mismatch scale", gap < SIGMA_MISMATCH,
          "%.4f against %.3f percent" % (gap, SIGMA_MISMATCH))
    ten = abs(interp(rows_a, ra * 10) - interp(rows_b, rb * 10))
    print("if my geometry is wrong by a factor of ten the difference becomes "
          "%.4f percent" % ten)
    check("even then it stays well under Arm A's dispersion, which is the claim "
          "the experiment rests on", ten < ARM_A_SPREAD / 4.0,
          "%.4f against %.2f percent" % (ten, ARM_A_SPREAD))
    print("one counter count is %.4f percent, so the difference is %.2f counts"
          % (ONE_COUNT, gap / ONE_COUNT))

    print()
    print("== SUMMARY ==  %d passed, %d failed" % (ok, fail))
    print("Ring current %.1f uA in Arm A and %.1f uA in Arm B at an ideal supply."
          % (rows_a[0][1] * 1e6, rows_b[0][1] * 1e6))
    print("At the layout's own resistance the arms differ by %.4f percent, which "
          "is %.0f times under Arm A's %.2f percent dispersion."
          % (gap, ARM_A_SPREAD / gap if gap else float("inf"), ARM_A_SPREAD))
    return fail


def synthetic(push=PUSH_INDEPENDENT, i0=100e-6, ideal=False, ohmic=True,
              sign=1.0):
    """A sweep built by hand, so the planted faults below are known to be faults."""
    rows, f0 = [], 570.0
    for ohms in OHMS:
        idd = i0
        vloc = SUPPLY if ideal else SUPPLY - idd * ohms
        if not ohmic:
            vloc = SUPPLY - idd * ohms * 2.0
        f = f0 * (1.0 + sign * push / 100.0 * (vloc - SUPPLY))
        rows.append((ohms, idd, vloc, f))
    return rows


GOOD_LOG = """tp = 1.755000e-09
idd = -1.023000e-04
vlocal = 1.697700e+00
f = 5.698000e+08
"""


def parser_cases():
    """The reader itself, against logs whose faults I know are there."""
    bad = 0
    trials = [("a complete log", GOOD_LOG, "parse"),
              ("a log whose current measurement never happened",
               GOOD_LOG.replace("-1.023000e-04", "0.000000e+00"), "reject"),
              ("a log with no current line at all",
               "\n".join(l for l in GOOD_LOG.splitlines()
                          if not l.startswith("idd")), "none")]
    for name, text, want in trials:
        try:
            got = "parse" if parse_log_text(text) else "none"
        except SystemExit:
            got = "reject"
        mark = "ok  " if got == want else "MISS"
        if got != want:
            bad += 1
        print("  %s %-58s expected %s got %s" % (mark, name, want, got))
    return bad


def selftest():
    cases = [
        ("a clean sweep", synthetic(), synthetic(), True),
        ("a deck that kept its ideal supply", synthetic(ideal=True),
         synthetic(), False),
        ("a supply that does not obey Ohm's law", synthetic(ohmic=False),
         synthetic(), False),
        ("a pushing figure that disagrees with the 2026-07-29 measurement",
         synthetic(push=40.0), synthetic(), False),
        ("a ring that speeds up when its supply droops",
         synthetic(sign=-1.0), synthetic(), False),
        ("a ring drawing a hundred times too much current",
         synthetic(i0=10e-3), synthetic(), False),
    ]
    bad = parser_cases()
    for name, a, b, want_pass in cases:
        buf, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            fails = report(a, b)
        finally:
            sys.stdout.close()
            sys.stdout = buf
        got = (fails == 0)
        mark = "ok  " if got == want_pass else "MISS"
        if got != want_pass:
            bad += 1
        print("  %s %-58s expected %s got %s"
              % (mark, name, "pass" if want_pass else "fail",
                 "pass" if got else "fail"))
    print("selftest: %s" % ("all %d planted cases behaved" % (len(cases) + 3)
                            if not bad else "%d case(s) did not" % bad))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/supply")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(1 if selftest() else 0)
    fails = report(read_arm(args.dir, "arma"), read_arm(args.dir, "armb"))
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
