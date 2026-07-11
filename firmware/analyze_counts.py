#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
#
# First-pass analysis of measure_puf.py CSV files. Pure stdlib. Give it one
# or more CSV files (one per chip/condition):
#
#   python3 analyze_counts.py chip01_room_1v8.csv chip02_room_1v8.csv
#
# Per file it prints per-arm stats. With two or more files it also prints the
# inter-chip picture per arm: how much of each oscillator's deviation from
# the arm mean REPEATS across chips (the shared, fake-entropy part) versus
# varies per chip (the real entropy). The prediction to check: Arm A's
# pattern repeats across chips, Arm B's does not.
import sys, csv, math

def load(path):
    per = {}     # (arm, idx) -> [counts]
    with open(path) as f:
        for row in csv.DictReader(l for l in f if not l.startswith("#")):
            c = int(row["count"])
            if c < 0:
                continue                     # timeout marker
            per.setdefault((int(row["arm"]), int(row["idx"])), []).append(c)
    return {k: sum(v)/len(v) for k, v in per.items()}, per

def stats(vals):
    m = sum(vals)/len(vals)
    sd = math.sqrt(sum((v-m)**2 for v in vals)/len(vals))
    return m, sd, min(vals), max(vals)

chips = {}
for path in sys.argv[1:]:
    means, raw = load(path)
    chips[path] = means
    print(f"\n== {path}")
    for arm, name in ((0, "Arm A (auto)"), (1, "Arm B (matched)")):
        vals = [means[(arm, i)] for i in range(16) if (arm, i) in means]
        if not vals:
            print(f"  {name}: no data")
            continue
        m, sd, mn, mx = stats(vals)
        noise = [math.sqrt(sum((x-sum(v)/len(v))**2 for x in v)/len(v))
                 for (a, i), v in raw.items() if a == arm and len(v) > 1]
        ns = (sum(noise)/len(noise)) if noise else 0.0
        print(f"  {name}: mean {m:.1f}  spread {mx-mn:.1f} ({100*(mx-mn)/m:.2f}% p-p)"
              f"  std {sd:.1f} ({100*sd/m:.2f}%)  repeat-noise {ns:.2f} counts")

if len(chips) > 1:
    print("\n== Across chips: does the pattern repeat?")
    names = list(chips)
    for arm, aname in ((0, "Arm A (auto)"), (1, "Arm B (matched)")):
        # deviation-from-arm-mean vector per chip, then mean pairwise correlation
        vecs = []
        for n in names:
            vals = [chips[n].get((arm, i)) for i in range(16)]
            if None in vals:
                continue
            m = sum(vals)/16
            vecs.append([v-m for v in vals])
        rs = []
        for i in range(len(vecs)):
            for j in range(i+1, len(vecs)):
                a, b = vecs[i], vecs[j]
                sa = math.sqrt(sum(x*x for x in a)); sb = math.sqrt(sum(x*x for x in b))
                if sa and sb:
                    rs.append(sum(x*y for x, y in zip(a, b))/(sa*sb))
        if rs:
            r = sum(rs)/len(rs)
            print(f"  {aname}: mean pairwise correlation of patterns r = {r:+.3f}"
                  f"  ({len(vecs)} chips; near +1 = shared fake entropy, near 0 = real entropy)")
