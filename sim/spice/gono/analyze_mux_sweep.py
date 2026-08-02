#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Acceptance test for the 32-to-1 selection path, hardware item 2.

Reads what gen_mux_sweep.py produced. It asks one question of every oscillator.
Does the count at the flop equal the count at the ring?

A selector that delays every edge is harmless. A fixed delay cannot change a
frequency. A selector that swallows an edge on one path and not on another is a
different matter. That oscillator reads slow, and the difference then belongs to
the routing rather than to the ring, which is the confound this chip is built to
measure.

Corrected 2026-08-02, and the correction matters more than the original result.

The first version took the narrowest level at the tap and the narrowest level at
sel_ro and reported the difference as a shortening. Those are not the same
level. Rise and fall travel a path at different speeds, and the difference moves
each trailing edge without moving the leading one, so one polarity grows by
exactly as much as the other shrinks. On B15 the tap runs 539 ps high and 583 ps
low while sel_ro runs 721 ps high and 401 ps low, with the period preserved to
the picosecond. The narrowest level at the tap is therefore a high and the
narrowest at sel_ro is a low, and comparing them produced a headline of 25.0%
shortening for a path that lengthens its high level by 181 ps.

I found it because the boundary sweep, which reused this comparison, reported a
pulse arriving wider than it left. A selector cannot do that, and the impossible
number was the only reason I went and looked at the waveform.

So highs and lows are kept apart here now, and rise delay and fall delay are
reported separately, because their difference is the quantity that actually
describes what the path does.

What each deck gives up. Rising edges at the ring tap inside the measurement
window. Rising edges at sel_ro over the same window. Transitions of the first
ripple flop, which should come at half that rate. The narrowest complete high
and the narrowest complete low at each node. And the two edge delays.

A pass needs the counts to agree on all 32 paths and the blocked controls to
deliver nothing.

The controls matter more than they look. Each deck holds a cell's side inputs at
the levels that open one path. If a level were wrong the cell would sit at a
constant and the deck would report no edges. Running the same paths deliberately
closed shows that a silent path really does read as zero here. That is what
makes a passing open path evidence instead of an assumption.

Run:
    python3 analyze_mux_sweep.py /tmp/muxsweep
    python3 analyze_mux_sweep.py --selftest
"""

import argparse
import csv
import glob
import os
import re
import sys

T_START_NS = 8.0      # ring is enabled at 2 ns; ignore startup
TOGGLE_SLACK = 1      # a window boundary can legitimately cost one toggle

# The first ripple stage divides by two, so a clean path gives half as many flop
# rises as sel_ro rises. That is the count the measurement depends on.
#
# The width limit below is a screening threshold and not a library figure. The
# sky130 datasheets do not publish a minimum clock pulse width for dfrtp_2. The
# boundary sweep measured the real limit on B15 at the fast corner: a 105 ps high
# at the tap survives the path and clocks the flop, a 71 ps one does not. So the
# count is the real test and the width is the early warning.
MAX_EROSION_PCT = 50.0


def read_raw(path):
    """ngspice wrdata output: a time column in front of every saved vector."""
    rows, names = [], None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if not parts:
                continue
            try:
                rows.append([float(x) for x in parts])
            except ValueError:
                if names is None:
                    names = parts
    if not rows:
        raise ValueError("no numeric rows in %s" % path)
    ncol = len(rows[0])
    cols = list(zip(*[r for r in rows if len(r) == ncol]))
    t = list(cols[0])
    vectors = [list(cols[i]) for i in range(1, ncol, 2)]
    return t, vectors


def crossings(t, v, level, t0):
    """Times where v crosses level, with the direction, linearly interpolated."""
    out = []
    for i in range(1, len(v)):
        if t[i] < t0:
            continue
        a, b = v[i - 1], v[i]
        if (a < level <= b) or (a > level >= b):
            span = b - a
            frac = 0.0 if span == 0 else (level - a) / span
            out.append((t[i - 1] + frac * (t[i] - t[i - 1]), 1 if b > a else -1))
    return out


def deck_chain(directory, tag):
    """Cell count and chain, read back out of the deck's own header comment."""
    path = os.path.join(directory, "mux_%s.spice" % tag)
    cells, chain = 0, ""
    if not os.path.isfile(path):
        return cells, chain
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r'(\d+) cells', line)
        if m and not cells:
            cells = int(m.group(1))
        if line.startswith("* chain:"):
            chain = line.split(":", 1)[1].strip()
        if chain and cells:
            break
    return cells, chain


def median(xs):
    ys = sorted(xs)
    n = len(ys)
    if not n:
        return 0.0
    return ys[n // 2] if n % 2 else 0.5 * (ys[n // 2 - 1] + ys[n // 2])


def level_stats(xs):
    """Narrowest complete high and narrowest complete low, kept apart.

    Taking one minimum over both polarities and comparing it node to node is the
    error this function exists to prevent. A path that lengthens its high and
    shortens its low will report the tap's high against sel_ro's low, and the
    answer looks like erosion when nothing eroded.

    The first and last interval are dropped. Both are clipped by the window
    rather than by the circuit, and a clipped level is not a measurement.
    """
    if len(xs) < 4:
        return 0.0, 0.0
    highs, lows = [], []
    for i in range(1, len(xs) - 2):
        width = xs[i + 1][0] - xs[i][0]
        (highs if xs[i][1] > 0 else lows).append(width)
    return (min(highs) if highs else 0.0), (min(lows) if lows else 0.0)


def edge_delay(src, dst):
    """Median time for an edge of one direction to travel from src to dst."""
    gaps = []
    for x in src[:-1]:
        later = [y for y in dst if y >= x]
        if later:
            gaps.append(later[0] - x)
    return median(gaps) if gaps else 0.0


def match_edges(rises_in, rises_out, t_end):
    """Pair each ring edge with the selector edge it produced.

    Totals over a fixed window cannot answer this. The selector delays every
    edge, so the last ring edge has no time to arrive before the transient ends
    and a total count reports it as lost. Item 6 has the same lesson written
    down: a pass condition that assumes the window lines up with the period
    fails for a reason that has nothing to do with the design.

    So each ring edge is matched to a selector edge one delay later, and only a
    ring edge with enough time left to have produced one is judged at all. A
    swallowed pulse shows up as an unmatched edge in the middle of the run,
    which is a real result. An edge left over at the end shows up as nothing.
    """
    if len(rises_in) < 4 or len(rises_out) < 2:
        return 0, [], 0.0, 0.0
    period = median([rises_in[i + 1] - rises_in[i] for i in range(len(rises_in) - 1)])
    delay = edge_delay(rises_in[:5], rises_out)
    tol = 0.25 * period
    judged, lost = 0, []
    for x in rises_in:
        if x + delay > t_end - 0.5 * period:
            continue                      # no time left to have produced one
        judged += 1
        if not any(abs(y - (x + delay)) <= tol for y in rises_out):
            lost.append(x)
    return judged, lost, delay, period


def measure(t, vec, directory, tag):
    """One deck, reduced to the numbers the pass condition needs."""
    tap, sel, q = vec
    level = 0.5 * max(max(tap), max(sel))
    t0 = T_START_NS * 1e-9

    x_in, x_out, x_q = (crossings(t, tap, level, t0), crossings(t, sel, level, t0),
                        crossings(t, q, level, t0))
    r_in = [x for x, d in x_in if d > 0]
    r_out = [x for x, d in x_out if d > 0]
    f_in = [x for x, d in x_in if d < 0]
    f_out = [x for x, d in x_out if d < 0]

    hi_in, lo_in = level_stats(x_in)
    hi_out, lo_out = level_stats(x_out)
    judged, lost, delay, period = match_edges(r_in, r_out, t[-1])
    cells, chain = deck_chain(directory, tag)

    return dict(tag=tag, n_in=judged, n_out=judged - len(lost),
                n_tog=len([x for x, d in x_q if d > 0]),
                hi_in=hi_in, lo_in=lo_in, hi_out=hi_out, lo_out=lo_out,
                rise=edge_delay(r_in, r_out), fall=edge_delay(f_in, f_out),
                delay=delay, period=period, lost=lost, raw_out=len(x_out),
                cells=cells, chain=chain)


def report(opens, controls, csv_path=None):
    failures = []
    print("selection path, fast corner")
    print()
    print("  osc   judged  matched  flop rises   rise    fall   asym   high    low")
    for r in opens:
        print("  %-5s %6d %8d %11d  %5.0f  %6.0f %6.0f %6.0f %6.0f"
              % (r["tag"], r["n_in"], r["n_out"], r["n_tog"],
                 r["rise"] * 1e12, r["fall"] * 1e12,
                 (r["fall"] - r["rise"]) * 1e12,
                 r["hi_out"] * 1e12, r["lo_out"] * 1e12))
        if r["lost"]:
            failures.append("%s: the selector lost %d %s, at %s ns"
                            % (r["tag"], len(r["lost"]),
                               "edge" if len(r["lost"]) == 1 else "edges",
                               ", ".join("%.2f" % (x * 1e9) for x in r["lost"])))
        expect = r["n_out"] // 2
        if abs(r["n_tog"] - expect) > TOGGLE_SLACK:
            failures.append("%s: %d edges at sel_ro should give %d flop rises, got %d"
                            % (r["tag"], r["n_out"], expect, r["n_tog"]))
        if r["hi_in"] and 100.0 * (1 - r["hi_out"] / r["hi_in"]) > MAX_EROSION_PCT:
            failures.append("%s: the high level fell from %.0f ps to %.0f ps, %.0f%% gone"
                            % (r["tag"], r["hi_in"] * 1e12, r["hi_out"] * 1e12,
                               100.0 * (1 - r["hi_out"] / r["hi_in"])))

    if opens:
        # The stimulus is the same extracted ring in all 32 decks, so the tap
        # figures should agree across them. If they do not, something in the
        # generator is varying that should not be.
        taps_hi = sorted(set("%.0f" % (r["hi_in"] * 1e12) for r in opens))
        taps_lo = sorted(set("%.0f" % (r["lo_in"] * 1e12) for r in opens))
        print()
        print("at the tap, the same ring in every deck: high %s ps, low %s ps"
              % ("/".join(taps_hi), "/".join(taps_lo)))

        asym = [(r["fall"] - r["rise"]) * 1e12 for r in opens]
        print("rise-to-fall asymmetry across the 32 paths: %.0f ps to %.0f ps"
              % (min(asym), max(asym)))
        print("so the high level changes by that much and the low by the opposite")

        shrink = [r["tag"] for r in opens if r["fall"] < r["rise"]]
        if shrink:
            print("paths whose fall beats their rise, so the high SHRINKS: %s"
                  % ", ".join(shrink))
            print("  the boundary sweep was run on the largest lengthening, not on "
                  "these; the worst case for a short pulse is here")
        else:
            print("no path has its fall arriving sooner than its rise, so no path "
                  "shortens a high level")

        worst_hi = min(opens, key=lambda r: r["hi_out"])
        worst_lo = min(opens, key=lambda r: r["lo_out"])
        print("narrowest high at sel_ro: %.0f ps on %s. narrowest low: %.0f ps on %s"
              % (worst_hi["hi_out"] * 1e12, worst_hi["tag"],
                 worst_lo["lo_out"] * 1e12, worst_lo["tag"]))
        delays = [r["rise"] * 1e12 for r in opens]
        print("rise delay: %.0f ps to %.0f ps, a spread of %.0f ps"
              % (min(delays), max(delays), max(delays) - min(delays)))

    if controls:
        live = [r["tag"] for r in controls if r["raw_out"] > 0]
        print()
        print("blocked controls: %d of %d silent" % (len(controls) - len(live), len(controls)))
        if live:
            failures.append("controls that should have been silent produced edges: %s"
                            % ", ".join(live))
    else:
        print()
        print("no blocked controls in this directory; rerun the generator with --control")

    if csv_path and opens:
        with open(csv_path, "w", newline="\n", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["osc", "cells", "rise_delay_ps", "fall_delay_ps",
                        "asymmetry_ps", "tap_high_ps", "sel_high_ps",
                        "tap_low_ps", "sel_low_ps", "edges_judged",
                        "edges_matched", "flop_rises", "chain"])
            for r in opens:
                w.writerow([r["tag"], r["cells"],
                            "%.0f" % (r["rise"] * 1e12), "%.0f" % (r["fall"] * 1e12),
                            "%.0f" % ((r["fall"] - r["rise"]) * 1e12),
                            "%.0f" % (r["hi_in"] * 1e12), "%.0f" % (r["hi_out"] * 1e12),
                            "%.0f" % (r["lo_in"] * 1e12), "%.0f" % (r["lo_out"] * 1e12),
                            r["n_in"], r["n_out"], r["n_tog"], r["chain"]])
        print()
        print("wrote %s" % csv_path)

    print()
    if failures:
        print("FAIL, %d problems" % len(failures))
        for f in failures:
            print("  " + f)
        return 1
    print("PASS: every oscillator's edges survive the selector and reach the counter")
    return 0


# --------------------------------------------------------------------------
# Self-test. The polarity mistake this file was corrected for passed every check
# it had, so the checks were the problem. These plant it deliberately.
# --------------------------------------------------------------------------

def _synth_deck(d, tag, vdd, period, rise_d, fall_d, lose=False):
    """A steady ring at the tap, and sel_ro with its own rise and fall delays."""
    step = 2e-12
    n = int(24e-9 / step)
    t = [i * step for i in range(n)]
    highs, k = [], 0
    while 2e-9 + k * period < 22e-9:
        r = 2e-9 + k * period
        highs.append((r, r + 0.5 * period))
        k += 1
    sel_highs = [(r + rise_d, f + fall_d) for i, (r, f) in enumerate(highs)
                 if not (lose and i == len(highs) // 2)]

    def sample(hs):
        out, j = [], 0
        for x in t:
            while j < len(hs) and x >= hs[j][1]:
                j += 1
            out.append(vdd if j < len(hs) and hs[j][0] <= x else 0.0)
        return out

    tap, sel = sample(highs), sample(sel_highs)
    q, lvl, j = [], 0.0, 0
    for x in t:
        while j < len(sel_highs) and x >= sel_highs[j][0]:
            lvl = vdd - lvl
            j += 1
        q.append(lvl)

    with open(os.path.join(d, "mux_%s.spice" % tag), "w", newline="\n") as fh:
        fh.write("* --- selector path for oscillator %s, 5 cells, open path ---\n" % tag)
        fh.write("* chain: synthetic\n")
    with open(os.path.join(d, "mux_%s.raw.txt" % tag), "w", newline="\n") as fh:
        fh.write("time v(b_out) time v(sel_ro) time v(q)\n")
        for i in range(n):
            fh.write("%.6e %.6e %.6e %.6e %.6e %.6e\n"
                     % (t[i], tap[i], t[i], sel[i], t[i], q[i]))


def selftest():
    import io
    import shutil
    import tempfile

    vdd, period = 1.95, 1.122e-9
    ok = True

    def run(label, build, expect_fail, check):
        nonlocal ok
        d = tempfile.mkdtemp(prefix="muxselftest.")
        try:
            build(d)
            opens = []
            for p in sorted(glob.glob(os.path.join(d, "mux_*.raw.txt"))):
                tag = os.path.basename(p)[4:-8]
                t, vec = read_raw(p)
                opens.append(measure(t, vec, d, tag))
            buf, keep = io.StringIO(), sys.stdout
            sys.stdout = buf
            try:
                rc = report(opens, [])
            finally:
                sys.stdout = keep
            text = buf.getvalue()
            good = ((rc != 0) == expect_fail) and check(opens, text)
            print("  %-56s %s" % (label, "ok" if good else "MISSED"))
            if not good:
                ok = False
                print(text)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    print("self-test of analyze_mux_sweep")

    # B15's real numbers. The high grows 181 ps and the low shrinks 181 ps, so
    # the narrowest level at the tap is a high and the narrowest at sel_ro is a
    # low. Reporting that as erosion is the bug.
    def grows(d):
        _synth_deck(d, "B15", vdd, period, 0.360e-9, 0.541e-9)
    run("a path that lengthens its high is not called erosion", grows,
        expect_fail=False,
        check=lambda o, text: (o[0]["hi_out"] > o[0]["hi_in"]
                               and o[0]["lo_out"] < o[0]["lo_in"]
                               and "no path shortens a high level" in text))

    def shrinks(d):
        _synth_deck(d, "X00", vdd, period, 0.360e-9, 0.240e-9)
    run("a path that really does shorten its high is named", shrinks,
        expect_fail=False,
        check=lambda o, text: "the high SHRINKS: X00" in text)

    def dropped(d):
        _synth_deck(d, "X01", vdd, period, 0.360e-9, 0.541e-9, lose=True)
    run("a swallowed edge in mid-run still fails", dropped, expect_fail=True,
        check=lambda o, text: "the selector lost" in text)

    print("self-test %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", nargs="?")
    ap.add_argument("--csv", help="write the derived per-oscillator record here")
    ap.add_argument("--selftest", action="store_true",
                    help="run the planted-fault checks and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.directory:
        ap.error("give a sweep directory, or --selftest")

    files = sorted(glob.glob(os.path.join(args.directory, "mux_*.raw.txt")))
    if not files:
        raise SystemExit("no mux_*.raw.txt in %s; run the decks first" % args.directory)

    opens, controls = [], []
    for path in files:
        tag = os.path.basename(path)[4:-8]
        t, vec = read_raw(path)
        if len(vec) < 3:
            raise SystemExit("%s: expected three saved vectors, found %d"
                             % (tag, len(vec)))
        row = measure(t, vec, args.directory, tag)
        (controls if tag.startswith("ctl") else opens).append(row)

    return report(opens, controls, args.csv)


if __name__ == "__main__":
    sys.exit(main())
