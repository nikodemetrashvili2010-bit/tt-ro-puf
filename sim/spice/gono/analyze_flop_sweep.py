#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Check the flop-level ring-stop sweep from gen_flop_sweep.py.

For every enable-fall phase this reads the toggle-flop output q and reports two
things. First, whether q settles to a clean logic level in the tail after the
ring has stopped: a metastable plateau near mid-rail would show up as samples
sitting in the forbidden band well after the last clock. Second, the number of
counted toggles, so we can see how much the captured count moves across phases.

The design claim under test: a short boundary pulse costs at most one count and
never a corrupt or hung result, because the ring is stopped and the measurement
core waits for the counter to settle before latching. That is PASS here when every
phase settles to a rail and the toggle count varies by at most one edge.

Usage: python3 analyze_flop_sweep.py /tmp/flopsweep [--tail-ns 2.0]
"""

import argparse
import glob
import os
import sys

VDD = 1.8
TH = VDD / 2.0
LO = 0.2 * VDD          # forbidden band low edge
HI = 0.8 * VDD          # forbidden band high edge


def load(path):
    t, v = [], []
    for line in open(path):
        p = line.split()
        if len(p) < 2:
            continue
        try:
            a, b = float(p[0]), float(p[1])
        except ValueError:
            continue
        t.append(a)
        v.append(b)
    return t, v


def count_toggles(t, v, t0=1.5e-9):
    """Number of q threshold crossings after reset release (one per clocked edge)."""
    n, above = 0, None
    for ti, vi in zip(t, v):
        if ti < t0:
            continue
        a = vi > TH
        if above is None:
            above = a
            continue
        if a != above:
            n += 1
            above = a
    return n


def tail_state(t, v, tail_ns):
    """Return (fraction of tail samples in the forbidden band, final level, distance to nearest rail)."""
    t_end = t[-1]
    start = t_end - tail_ns * 1e-9
    tail = [vi for ti, vi in zip(t, v) if ti >= start]
    if not tail:
        return 1.0, v[-1], min(abs(v[-1]), abs(v[-1] - VDD))
    in_band = sum(1 for vi in tail if LO < vi < HI)
    final = sum(tail[-50:]) / len(tail[-50:])
    rail = min(abs(final - 0.0), abs(final - VDD))
    return in_band / len(tail), final, rail


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sweep_dir")
    ap.add_argument("--tail-ns", type=float, default=2.0,
                    help="window at the end of the run to test for a settled rail")
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.sweep_dir, "flop_*.raw.txt")))
    if not files:
        print("error: no flop_*.raw.txt in %s" % args.sweep_dir, file=sys.stderr)
        return 2

    counts, unsettled = [], 0
    for path in files:
        t, v = load(path)
        if len(t) < 100:
            print("%s: too little data, skipped" % os.path.basename(path))
            unsettled += 1
            continue
        n = count_toggles(t, v)
        frac_band, final, rail = tail_state(t, v, args.tail_ns)
        settled = frac_band < 0.01 and rail < 0.05 * VDD
        counts.append(n)
        if not settled:
            unsettled += 1
        print("%s: %3d toggles, final q=%.3f V (%s), tail-in-band %.2f%%  %s"
              % (os.path.basename(path), n, final, "HIGH" if final > TH else "LOW",
                 100 * frac_band, "settled" if settled else "NOT-SETTLED"))

    print()
    spread = (max(counts) - min(counts)) if counts else 99
    if counts:
        print("counted toggles across phases: min %d, max %d, spread %d"
              % (min(counts), max(counts), spread))
    if unsettled == 0 and counts and spread <= 1:
        print("PASS: every enable-fall phase settled to a clean rail; "
              "captured count varies by at most one edge")
        return 0
    print("FAIL: %d unsettled phase(s); count spread %d" % (unsettled, spread))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
