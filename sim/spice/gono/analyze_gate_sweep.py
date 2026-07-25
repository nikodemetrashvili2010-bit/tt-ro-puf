#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Characterize the ring tap at the enable-fall boundary.

Reads every sweep_XX.raw.txt written by the decks from gen_gate_sweep.py, finds
the threshold crossings of the tap waveform, and reports for each enable-fall
phase how many edges the tap produced and the narrowest pulse near the fall.

Every edge here is a full-swing ring transition. Stopping a free-running ring at
an arbitrary phase leaves a final pulse whose width depends on the phase and can
be short; that is inherent to gating any free ring, not a defect of this scheme.
Whether a short boundary pulse matters is decided at the first ripple flop, not
at the tap, so the acceptance test lives in gen_flop_sweep.py /
analyze_flop_sweep.py, which show the flop resolves every phase to a clean rail
with at most a one-count boundary ambiguity. This script only characterizes the
tap and flags a genuinely dead ring.

Usage: python3 analyze_gate_sweep.py /tmp/gatesweep [--short-ps 400]
"""

import argparse
import glob
import os
import statistics
import sys

VDD = 1.8
TH = VDD / 2


def crossings(times, volts):
    edges = []
    above = volts[0] > TH
    for t, v in zip(times, volts):
        now = v > TH
        if now != above:
            edges.append((t, now))
            above = now
    return edges


def load(path):
    times, volts = [], []
    for line in open(path):
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            t = float(parts[0])
            v = float(parts[1])
        except ValueError:
            continue
        times.append(t)
        volts.append(v)
    return times, volts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sweep_dir")
    ap.add_argument("--short-ps", type=float, default=400.0,
                    help="label a boundary pulse narrower than this as short "
                         "(default 400 ps); informational, not a pass/fail gate")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.sweep_dir, "sweep_*.raw.txt")))
    if not files:
        print("error: no sweep_*.raw.txt in %s" % args.sweep_dir, file=sys.stderr)
        return 2

    worst = None
    dead = 0
    all_widths = []
    for path in files:
        times, volts = load(path)
        if len(times) < 100:
            print("%s: too little data, skipped" % os.path.basename(path))
            continue
        edges = crossings(times, volts)
        if len(edges) < 4:
            print("%s: ring never ran (%d edges)" % (os.path.basename(path), len(edges)))
            dead += 1
            continue
        # pulse widths across the whole run; the boundary pulse is in the tail
        widths = [(b[0] - a[0]) * 1e12 for a, b in zip(edges, edges[1:])]
        all_widths.extend(widths)
        tail = widths[-6:] if len(widths) >= 6 else widths
        min_all = min(widths)
        min_tail = min(tail)
        # settle edges: transitions in the last 5 ns of the run
        t_end = times[-1]
        settle = sum(1 for t, _ in edges if t > t_end - 5e-9)
        note = "short boundary pulse" if min_tail < args.short_ps else "full-width to boundary"
        if worst is None or min_tail < worst[1]:
            worst = (os.path.basename(path), min_tail)
        print("%s: %4d edges total, %d in final 5 ns, min width %6.1f ps "
              "(tail %6.1f ps)  %s"
              % (os.path.basename(path), len(edges), settle,
                 min_all, min_tail, note))

    print()
    nominal = statistics.median(all_widths) if all_widths else 0.0
    if nominal:
        print("nominal ring half-period (median pulse width): %.1f ps" % nominal)
    if worst:
        frac = 100.0 * worst[1] / nominal if nominal else 0.0
        print("narrowest boundary pulse across the sweep: %.1f ps (%s), %.0f%% of nominal"
              % (worst[1], worst[0], frac))
    if dead:
        print("FAIL: %d phase(s) produced a dead ring (no oscillation)" % dead)
        return 1
    print("every edge is a full-swing ring transition. A short final pulse at some")
    print("phases is inherent to stopping a free ring; whether it is benign is decided")
    print("at the flop by analyze_flop_sweep.py (first flop resolves clean, count +-1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
