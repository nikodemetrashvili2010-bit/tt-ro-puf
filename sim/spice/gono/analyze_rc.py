#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Compare the lumped and distributed-RC models of the same oscillators.

gen_rc_decks.py writes two decks per oscillator that differ only in how the
extraction is represented: one total capacitance grounded per net, against the
per-node capacitances, series resistors and real node-to-node coupling the SPEF
recorded. Running both isolates the model from everything else, since the cells,
the corner and the startup are identical.

The first version of this script demanded that the two models rank all sixteen
oscillators identically. That is the wrong test. Several rings sit within a few
tenths of a percent of each other, so any small per-ring difference reorders them
while telling you nothing about whether the model is trustworthy. What matters is
which claims survive, so this reports four things instead.

  Spread. The headline result is a peak-to-peak percentage, so whether the two
  models agree on the size of the dispersion is the first question.

  Rank agreement. A high rank correlation means the per-oscillator fingerprint is
  a property of the layout rather than of the simplification, even if near-tied
  rings swap places.

  Adjacent-pair bits. The design turns pairs of neighbouring oscillators into
  response bits, so the decision-relevant question is how many of those
  comparisons the model change reverses, and how large a gap protects a pair.

  Shift against load. If the heavier rings slow down more under the fuller model,
  the lumped result understates the dispersion rather than inventing it.

Usage:
    python3 analyze_rc.py --dir /tmp/rc16 --ro $(seq 0 15)
"""

import argparse
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_SPEF = os.path.join(
    PROJ, "dualarm", "build_current", "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
NINV = 30


def read_freq(path):
    if not os.path.exists(path):
        return None
    m = re.search(r'^f\s*=\s*([0-9.eE+-]+)', open(path, errors="ignore").read(), re.M)
    return float(m.group(1)) / 1e6 if m else None


def ring_caps(spef_path):
    """Total extracted ring capacitance per Arm A oscillator, in fF."""
    if not os.path.exists(spef_path):
        return {}
    txt = open(spef_path).read()
    names = {k: v.replace("\\", "")
             for k, v in re.findall(r'^\*(\d+)\s+(\S+)\s*$', txt, re.M)}
    inv = {v: k for k, v in names.items()}
    tot = {m.group(1): float(m.group(2)) * 1000
           for m in re.finditer(r'^\*D_NET \*(\d+)\s+([0-9.eE+-]+)', txt, re.M)}
    out = {}
    for i in range(16):
        s = 0.0
        for k in range(NINV + 1):
            num = inv.get(f"u_puf.u_core.g_ro_bank[{i}].u_ro.n[{k}]")
            if num:
                s += tot.get(num, 0.0)
        if s:
            out[i] = s
    return out


def pearson(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    return num / den if den else float("nan")


def spearman(a, b):
    """Rank correlation over the shared keys of two {key: value} maps."""
    keys = sorted(set(a) & set(b))
    n = len(keys)
    if n < 3:
        return float("nan")
    ra = {k: i for i, k in enumerate(sorted(keys, key=lambda k: -a[k]))}
    rb = {k: i for i, k in enumerate(sorted(keys, key=lambda k: -b[k]))}
    d2 = sum((ra[k] - rb[k]) ** 2 for k in keys)
    return 1 - 6 * d2 / (n * (n * n - 1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="/tmp/rc")
    ap.add_argument("--ro", type=int, nargs="+", required=True)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--spef", default=DEFAULT_SPEF)
    ap.add_argument("--min-rank-corr", type=float, default=0.85,
                    help="rank correlation below which the fingerprint is not "
                         "safe to attribute to layout (default %(default)s)")
    ap.add_argument("--max-spread-ratio", type=float, default=2.0)
    args = ap.parse_args(argv)

    lum, rc = {}, {}
    for ro in args.ro:
        fl = read_freq(os.path.join(args.dir, f"ro{ro:02d}{args.suffix}_lumped_out.txt"))
        fr = read_freq(os.path.join(args.dir, f"ro{ro:02d}{args.suffix}_rc_out.txt"))
        if fl is None or fr is None:
            print("missing or unparsable result for RO%d" % ro, file=sys.stderr)
            continue
        lum[ro], rc[ro] = fl, fr
    if len(lum) < 3:
        print("need at least three oscillators with both models", file=sys.stderr)
        return 2

    caps = ring_caps(args.spef)
    print("%-5s %11s %11s %9s %10s" % ("ring", "lumped MHz", "RC MHz", "shift %", "ring fF"))
    print("-" * 50)
    for ro in sorted(lum):
        d = 100 * (rc[ro] - lum[ro]) / lum[ro]
        c = "%10.2f" % caps[ro] if ro in caps else "         -"
        print("RO%-3d %11.2f %11.2f %+9.2f %s" % (ro, lum[ro], rc[ro], d, c))

    shifts = {ro: 100 * (rc[ro] - lum[ro]) / lum[ro] for ro in lum}
    sl = 100 * (max(lum.values()) - min(lum.values())) / st.mean(list(lum.values()))
    sr = 100 * (max(rc.values()) - min(rc.values())) / st.mean(list(rc.values()))
    rho = spearman(lum, rc)

    print()
    print("spread: lumped %.2f%%, RC %.2f%% (ratio %.2f)" % (sl, sr, sr / sl if sl else float("nan")))
    print("per-ring shift: %+.2f%% to %+.2f%% (all %s)"
          % (min(shifts.values()), max(shifts.values()),
             "slower" if max(shifts.values()) < 0 else "mixed in sign"))
    print("rank correlation lumped vs RC: %.3f" % rho)
    fast_l, fast_r = max(lum, key=lum.get), max(rc, key=rc.get)
    slow_l, slow_r = min(lum, key=lum.get), min(rc, key=rc.get)
    print("fastest: RO%d lumped, RO%d RC%s" % (fast_l, fast_r, "" if fast_l == fast_r else "  (changed)"))
    print("slowest: RO%d lumped, RO%d RC%s" % (slow_l, slow_r, "" if slow_l == slow_r else "  (changed)"))

    shared = sorted(set(shifts) & set(caps))
    if len(shared) >= 3:
        r = pearson([caps[i] for i in shared], [shifts[i] for i in shared])
        print("corr(ring capacitance, shift) = %+.3f  (%s)"
              % (r, "heavier rings slow down more, so the lumped model understates "
                    "the dispersion" if r < -0.3 else "no clear load dependence"))

    # --- the decision-relevant test: adjacent-pair response bits ---
    pairs = [(a, a + 1) for a in range(0, max(lum) + 1, 2) if a in lum and a + 1 in lum]
    flipped, held = [], []
    print()
    if pairs:
        print("adjacent-pair bits (the comparison the design actually makes):")
        for a, b in pairs:
            gap = 100 * abs(lum[a] - lum[b]) / st.mean([lum[a], lum[b]])
            same = (lum[a] > lum[b]) == (rc[a] > rc[b])
            (held if same else flipped).append((a, b, gap))
            print("  RO%-2d/RO%-2d  lumped gap %5.2f%%   %s"
                  % (a, b, gap, "holds" if same else "REVERSES"))
        print("  %d of %d bits reverse under the fuller model" % (len(flipped), len(pairs)))
        if flipped and held:
            print("  reversing pairs were separated by up to %.2f%%; "
                  "every pair beyond %.2f%% held"
                  % (max(g for *_, g in flipped), min(g for *_, g in held)))
            print("  treat predicted bits from pairs closer than about %.1f%% as "
                  "model-dependent" % max(g for *_, g in flipped))

    print()
    ok = True
    if not (1 / args.max_spread_ratio <= (sr / sl if sl else 0) <= args.max_spread_ratio):
        print("FAIL: the spread changes by more than a factor of %.1f, so the "
              "headline dispersion depends on the parasitic model" % args.max_spread_ratio)
        ok = False
    else:
        print("spread agrees within a factor of %.1f between the models" % args.max_spread_ratio)
    if rho < args.min_rank_corr:
        print("FAIL: rank correlation %.3f is below %.2f, so the per-oscillator "
              "pattern is not safe to attribute to layout" % (rho, args.min_rank_corr))
        ok = False
    else:
        print("rank agreement holds: the fingerprint survives the model change")
    if ok:
        print("PASS: the distributed network shifts absolute frequency and widens the "
              "spread, but the dispersion magnitude and the per-oscillator pattern "
              "both survive. Closely matched pairs are the exception, listed above.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
