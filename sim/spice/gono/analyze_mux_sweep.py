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

Four things are read out of each deck. Rising edges at the ring tap inside the
measurement window. Rising edges at sel_ro over the same window. Transitions of
the first ripple flop, which should come at half that rate. And the shortest
high or low level at sel_ro, against the same figure at the tap.

A pass needs the counts to agree on all 32 paths and the blocked controls to
deliver nothing.

The controls matter more than they look. Each deck holds a cell's side inputs at
the levels that open one path. If a level were wrong the cell would sit at a
constant and the deck would report no edges. Running the same paths deliberately
closed shows that a silent path really does read as zero here. That is what
makes a passing open path evidence instead of an assumption.

Run:
    python3 analyze_mux_sweep.py /tmp/muxsweep
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
# sky130 datasheets do not publish a minimum clock pulse width for dfrtp_2, and
# the flop sweep in item 1 already showed this flop resolving a 175 ps boundary
# pulse cleanly. So the count is the real test and the width is the early
# warning: a path that has eaten half of the narrowest level is misbehaving even
# if this particular run still happened to clock.
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


def edge_stats(t, v, level, t0):
    """Rising-edge times, and the narrowest complete level between them.

    The first and last interval are dropped. Both are clipped by the window
    rather than by the circuit, and a clipped level is not a measurement.
    """
    xs = crossings(t, v, level, t0)
    rises = [x for x, d in xs if d > 0]
    widths = [xs[i + 1][0] - xs[i][0] for i in range(len(xs) - 1)]
    inner = widths[1:-1] if len(widths) > 2 else widths
    return rises, (min(inner) if inner else 0.0)


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
    firsts = []
    for x in rises_in[:5]:
        later = [y for y in rises_out if y >= x]
        if later:
            firsts.append(later[0] - x)
    delay = median(firsts)
    tol = 0.25 * period
    judged, lost = 0, []
    for x in rises_in:
        if x + delay > t_end - 0.5 * period:
            continue                      # no time left to have produced one
        judged += 1
        if not any(abs(y - (x + delay)) <= tol for y in rises_out):
            lost.append(x)
    return judged, lost, delay, period


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory")
    ap.add_argument("--csv", help="write the derived per-oscillator record here")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.directory, "mux_*.raw.txt")))
    if not files:
        raise SystemExit("no mux_*.raw.txt in %s; run the decks first" % args.directory)

    opens, controls, failures = [], [], []
    for path in files:
        tag = os.path.basename(path)[4:-8]
        t, vec = read_raw(path)
        if len(vec) < 3:
            failures.append("%s: expected three saved vectors, found %d" % (tag, len(vec)))
            continue
        tap, sel, q = vec
        level = 0.5 * max(max(tap), max(sel))
        r_in, w_in = edge_stats(t, tap, level, T_START_NS * 1e-9)
        r_out, w_out = edge_stats(t, sel, level, T_START_NS * 1e-9)
        r_tog, _ = edge_stats(t, q, level, T_START_NS * 1e-9)
        judged, lost, delay, period = match_edges(r_in, r_out, t[-1])
        cells, chain = deck_chain(args.directory, tag)
        row = dict(tag=tag, n_in=judged, n_out=judged - len(lost), n_tog=len(r_tog),
                   w_in=w_in, w_out=w_out, delay=delay, period=period,
                   lost=lost, raw_out=len(r_out), cells=cells, chain=chain)
        (controls if tag.startswith("ctl") else opens).append(row)

    print("selection path, fast corner")
    print()
    print("  osc   edges judged  matched  flop rises  delay  narrowest level")
    for r in opens:
        keep = "%.0f ps" % (r["w_out"] * 1e12) if r["w_out"] else "none"
        print("  %-5s %12d %8d %11d %6.0f ps  %s"
              % (r["tag"], r["n_in"], r["n_out"], r["n_tog"],
                 r["delay"] * 1e12, keep))
        if r["lost"]:
            failures.append("%s: the selector lost %d %s, at %s ns"
                            % (r["tag"], len(r["lost"]),
                               "edge" if len(r["lost"]) == 1 else "edges",
                               ", ".join("%.2f" % (x * 1e9) for x in r["lost"])))
        expect = r["n_out"] // 2
        if abs(r["n_tog"] - expect) > TOGGLE_SLACK:
            failures.append("%s: %d edges at sel_ro should give %d flop rises, got %d"
                            % (r["tag"], r["n_out"], expect, r["n_tog"]))
        if r["w_in"] and 100.0 * (1 - r["w_out"] / r["w_in"]) > MAX_EROSION_PCT:
            failures.append("%s: narrowest level fell from %.0f ps to %.0f ps, %.0f%% gone"
                            % (r["tag"], r["w_in"] * 1e12, r["w_out"] * 1e12,
                               100.0 * (1 - r["w_out"] / r["w_in"])))

    if opens:
        erosion = [100.0 * (1 - r["w_out"] / r["w_in"]) for r in opens if r["w_in"]]
        worst = min(opens, key=lambda r: r["w_out"])
        print()
        print("narrowest level anywhere at sel_ro: %.0f ps on %s, against %.0f ps at the tap"
              % (worst["w_out"] * 1e12, worst["tag"], worst["w_in"] * 1e12))
        if erosion:
            print("level shortening across the 32 paths: %.1f%% to %.1f%%"
                  % (min(erosion), max(erosion)))
        delays = [r["delay"] * 1e12 for r in opens]
        print("selector delay: %.0f ps to %.0f ps, a spread of %.0f ps"
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

    if args.csv and opens:
        with open(args.csv, "w", newline="\n", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["osc", "cells", "delay_ps", "narrowest_ps", "tap_ps",
                        "shortening_pct", "edges_judged", "edges_matched",
                        "flop_rises", "chain"])
            for r in opens:
                w.writerow([r["tag"], r["cells"], "%.0f" % (r["delay"] * 1e12),
                            "%.0f" % (r["w_out"] * 1e12), "%.0f" % (r["w_in"] * 1e12),
                            "%.1f" % (100.0 * (1 - r["w_out"] / r["w_in"]) if r["w_in"] else 0),
                            r["n_in"], r["n_out"], r["n_tog"], r["chain"]])
        print()
        print("wrote %s" % args.csv)

    print()
    if failures:
        print("FAIL, %d problems" % len(failures))
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("PASS: every oscillator's edges survive the selector and reach the counter")


if __name__ == "__main__":
    main()
