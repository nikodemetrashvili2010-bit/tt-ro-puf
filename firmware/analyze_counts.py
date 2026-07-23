#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Summarize RO-PUF measurements without mixing chips, conditions, or runs.

Input CSVs come from measure_puf.py: a ``# META {json}`` header line plus rows
``run_id,chip_id,condition,round,order,arm,idx,count,t_ms``. The physical die is
the experimental unit, so across-chip statistics are bootstrapped over chips
rather than over the dependent set of chip pairs. Response bits use pairings
that are fixed before the data is seen. All outputs are descriptive; they do
not by themselves establish entropy, reliability, or a security claim.
"""

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from itertools import combinations

NRO = 16
# Predeclared logical adjacent pairs. Same index mapping in both arms, so this
# is a clean architectural comparison. A geometry-based pairing can be supplied
# with --positions (also fixed before seeing frequencies).
LOGICAL_PAIRS = tuple((i, i + 1) for i in range(0, NRO, 2))
BOOTSTRAP = 2000
NEAR_TIE_MARGIN = 1.0  # counts of separation below which a bit is called fragile


def mean(xs):
    return sum(xs) / len(xs)


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def population_sd(xs):
    c = mean(xs)
    return math.sqrt(mean([(x - c) ** 2 for x in xs]))


def mad(xs):
    m = median(xs)
    return median([abs(x - m) for x in xs])


def parse_meta(lines):
    for line in lines:
        if line.startswith("# META "):
            try:
                return json.loads(line[len("# META "):])
            except ValueError:
                return None
    return None


def load_files(paths):
    groups = {}
    seen_runs = {}
    seen_digests = {}
    for path in paths:
        with open(path, encoding="utf-8", newline="") as fh:
            raw_bytes = fh.read()
        digest = hashlib.sha256(raw_bytes.encode("utf-8")).hexdigest()[:12]
        if digest in seen_digests:
            raise ValueError(
                "identical file passed more than once: %s and %s"
                % (seen_digests[digest], path))
        seen_digests[digest] = path
        lines = raw_bytes.splitlines(keepends=True)
        meta = parse_meta(lines)
        setting = None
        if meta:
            setting = (meta.get("clk_hz_requested"), meta.get("window"))
        rows = csv.DictReader(l for l in lines if not l.startswith("#"))
        required = {"run_id", "chip_id", "condition", "round", "arm", "idx", "count"}
        if not rows.fieldnames or not required.issubset(rows.fieldnames):
            missing = sorted(required.difference(rows.fieldnames or ()))
            raise ValueError("%s: missing CSV column(s): %s" % (path, ", ".join(missing)))
        for n, row in enumerate(rows, 2):
            try:
                run_id = row["run_id"].strip()
                chip_id = row["chip_id"].strip()
                condition = row["condition"].strip()
                rnd = int(row["round"])
                arm = int(row["arm"])
                idx = int(row["idx"])
                count = int(row["count"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("%s:%d: %s" % (path, n, exc)) from exc
            if arm not in (0, 1) or not 0 <= idx < NRO:
                raise ValueError("%s:%d: arm/idx out of range" % (path, n))
            # Reject a run_id seen in a different file: re-submitting the same
            # run would inflate the sample with duplicate observations.
            if run_id in seen_runs and seen_runs[run_id] != (path, digest):
                raise ValueError(
                    "duplicate run_id %s in %s and %s" % (run_id, seen_runs[run_id][0], path))
            seen_runs[run_id] = (path, digest)
            g = groups.setdefault(
                (chip_id, condition),
                {"raw": {}, "by_round": {}, "runs": set(), "sources": set(),
                 "settings": set(), "timeouts": 0, "saturated": 0})
            g["sources"].add(path)
            g["runs"].add(run_id)
            g["settings"].add(setting)
            if count < 0:
                g["timeouts"] += 1
                continue
            if count >= 65000:
                g["saturated"] += 1
            g["raw"].setdefault((arm, idx), []).append(count)
            g["by_round"].setdefault((run_id, rnd), {})[(arm, idx)] = count
    return groups


def osc_means(g, arm):
    return {idx: mean(s) for (a, idx), s in g["raw"].items() if a == arm and s}


def complete_vector(g, arm):
    v = osc_means(g, arm)
    if set(v) != set(range(NRO)):
        return None
    return [v[i] for i in range(NRO)]


def correlation(a, b):
    ma, mb = mean(a), mean(b)
    da = [x - ma for x in a]
    db = [x - mb for x in b]
    s = math.sqrt(sum(x * x for x in da)) * math.sqrt(sum(x * x for x in db))
    return None if s == 0 else sum(x * y for x, y in zip(da, db)) / s


def response_bits(vector, pairs):
    bits = []
    for l, r in pairs:
        if vector[l] == vector[r]:
            return None
        bits.append(int(vector[l] > vector[r]))
    return bits


def hamming_pct(a, b):
    return 100.0 * sum(x != y for x, y in zip(a, b)) / len(a)


def settings_ok(entries):
    ss = []
    for e in entries:
        s = e[1]["settings"]
        if len(s) != 1 or None in s:
            return False
        ss.append(next(iter(s)))
    return len(set(ss)) == 1


def bit_reliability(g, arm, pairs):
    """Per-pair bit-error rate across rounds, and a fragile-bit count.

    A bit whose two oscillators sit within NEAR_TIE_MARGIN counts on average, or
    that flips across repeats, is unreliable even if the pooled means order it.
    """
    per_round = [rc for (rid, rnd), rc in g["by_round"].items()]
    fragile = 0
    bers = []
    for l, r in pairs:
        votes = []
        for rc in per_round:
            if (arm, l) in rc and (arm, r) in rc and rc[(arm, l)] != rc[(arm, r)]:
                votes.append(int(rc[(arm, l)] > rc[(arm, r)]))
        if not votes:
            continue
        ref = 1 if sum(votes) * 2 >= len(votes) else 0
        ber = mean([int(v != ref) for v in votes])
        bers.append(ber)
        ml = g["raw"].get((arm, l))
        mr = g["raw"].get((arm, r))
        if ml and mr and abs(mean(ml) - mean(mr)) < NEAR_TIE_MARGIN:
            fragile += 1
        elif ber > 0.02:
            fragile += 1
    return (mean(bers) if bers else None), fragile, len(bers)


def shared_position_ratio(vectors):
    """Descriptive variance split: how much of the total across-chip variance is
    the shared per-position pattern versus chip-by-position residual. A larger
    ratio means a more repeatable layout pattern. Not a formal mixed model."""
    if len(vectors) < 2:
        return None
    n = len(vectors[0])
    col_means = [mean([v[i] for v in vectors]) for i in range(n)]
    grand = mean(col_means)
    shared = mean([(c - grand) ** 2 for c in col_means])
    resid = mean([mean([(v[i] - col_means[i]) ** 2 for i in range(n)]) for v in vectors])
    total = shared + resid
    return None if total == 0 else shared / total


def boot_ci(values, chips, stat, reps=BOOTSTRAP):
    """Bootstrap a statistic by resampling whole chips (the experimental unit),
    not chip pairs. values maps a chip to its vector."""
    rng = random.Random(20260723)
    keys = list(chips)
    if len(keys) < 2:
        return None
    samples = []
    for _ in range(reps):
        pick = [rng.choice(keys) for _ in keys]
        vecs = [values[k] for k in pick]
        s = stat(vecs)
        if s is not None:
            samples.append(s)
    if not samples:
        return None
    samples.sort()
    lo = samples[int(0.025 * len(samples))]
    hi = samples[min(len(samples) - 1, int(0.975 * len(samples)))]
    return mean(samples), lo, hi


def mean_pairwise_corr(vectors):
    cs = [c for a, b in combinations(vectors, 2) for c in [correlation(a, b)] if c is not None]
    return mean(cs) if cs else None


def load_positions(path):
    """Geometry-based pairing fixed before frequencies are seen: greedily pair
    each oscillator with its nearest unused neighbour by (x, y)."""
    pos = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                pos[int(row["ro"])] = (float(row["x_um"]), float(row["y_um"]))
            except (KeyError, ValueError):
                return None
    if set(pos) != set(range(NRO)) or any(math.isnan(x) or math.isnan(y) for x, y in pos.values()):
        return None
    remaining = set(range(NRO))
    pairs = []
    while len(remaining) >= 2:
        i = min(remaining)
        remaining.discard(i)
        j = min(remaining, key=lambda k: (pos[i][0] - pos[k][0]) ** 2 + (pos[i][1] - pos[k][1]) ** 2)
        remaining.discard(j)
        pairs.append((i, j))
    return tuple(pairs)


def print_summaries(groups):
    for (chip, cond), g in sorted(groups.items()):
        print("\n== %s / %s  [%d run(s), %d file(s)]"
              % (chip, cond, len(g["runs"]), len(g["sources"])))
        if g["timeouts"]:
            print("  timeout samples skipped: %d" % g["timeouts"])
        if g["saturated"]:
            print("  WARNING: %d samples near the 16-bit ceiling" % g["saturated"])
        if len(g["settings"]) == 1 and None not in g["settings"]:
            clk, win = next(iter(g["settings"]))
            print("  acquisition: clk=%s Hz window=%s" % (clk, win))
        else:
            print("  acquisition metadata: missing or inconsistent across files")
        for arm, name in ((0, "Arm A (auto)"), (1, "Arm B (matched)")):
            v = osc_means(g, arm)
            if not v:
                print("  %s: no valid data" % name)
                continue
            vals = list(v.values())
            c = mean(vals)
            pp = max(vals) - min(vals)
            sd = population_sd(vals)
            rep = [population_sd(s) for (a, _), s in g["raw"].items() if a == arm and len(s) > 1]
            noise = "repeat SD %.2f counts" % mean(rep) if rep else "repeat noise n/a"
            if c:
                print("  %s: %d/%d osc, mean %.1f | p-p %.2f%% | SD %.2f%% | "
                      "median %.1f MAD %.2f | %s"
                      % (name, len(vals), NRO, c, 100 * pp / c, 100 * sd / c,
                         median(vals), mad(vals), noise))
            else:
                print("  %s: mean is zero" % name)


def print_across_chips(groups, pairings):
    print("\n== Across chips at the same condition (chip is the unit)")
    for cond in sorted({c for _, c in groups}):
        print("  Condition: %s" % cond)
        for arm, name in ((0, "Arm A (auto)"), (1, "Arm B (matched)")):
            entries = []
            for (chip, gc), g in sorted(groups.items()):
                if gc != cond:
                    continue
                vec = complete_vector(g, arm)
                if vec is not None:
                    entries.append((chip, g, vec))
            if len(entries) < 2:
                print("    %s: need complete data from >=2 chips" % name)
                continue
            if not settings_ok(entries):
                print("    %s: incompatible acquisition settings across chips" % name)
                continue
            vectors = {chip: vec for chip, _, vec in entries}
            point = mean_pairwise_corr(list(vectors.values()))
            ci = boot_ci(vectors, list(vectors), mean_pairwise_corr)
            ratio = shared_position_ratio(list(vectors.values()))
            npairs = len(list(combinations(entries, 2)))
            if point is not None and ci:
                _, lo, hi = ci
                print("    %s: pattern correlation mean r=%+.3f "
                      "[bootstrap 95%% by chip: %+.3f, %+.3f], n_chips=%d "
                      "(%d dependent pairs)" % (name, point, lo, hi, len(vectors), npairs))
            if ratio is not None:
                print("      shared-position variance fraction %.2f "
                      "(higher = more repeatable layout pattern)" % ratio)
            for label, pairs in pairings:
                bits = {chip: response_bits(vec, pairs) for chip, _, vec in entries}
                good = {c: b for c, b in bits.items() if b is not None}
                if len(good) < 2:
                    print("      %s bits: a fixed pair tied on >=1 chip" % label)
                    continue
                hd = [hamming_pct(good[a], good[b]) for a, b in combinations(good, 2)]
                print("      %s uniqueness: mean HD=%.1f%% over %d chips "
                      "(%d dependent pairs, %d bits/chip)"
                      % (label, mean(hd), len(good), len(hd), len(pairs)))


def print_reliability(groups, pairings):
    print("\n== Bit reliability within chip/condition (needs repeated rounds)")
    for (chip, cond), g in sorted(groups.items()):
        for arm, name in ((0, "Arm A"), (1, "Arm B")):
            for label, pairs in pairings:
                ber, fragile, nb = bit_reliability(g, arm, pairs)
                if ber is None:
                    continue
                print("  %s/%s %s %s: mean BER %.3f, %d/%d fragile bits"
                      % (chip, cond, name, label, ber, fragile, nb))


def print_across_conditions(groups, pairings):
    print("\n== Same chip across conditions")
    for chip in sorted({c for c, _ in groups}):
        for arm, name in ((0, "Arm A"), (1, "Arm B")):
            entries = []
            for (gc, cond), g in sorted(groups.items()):
                if gc != chip:
                    continue
                vec = complete_vector(g, arm)
                if vec is not None:
                    entries.append((cond, g, vec))
            if len(entries) < 2:
                continue
            # Same compatibility gate as the across-chip path: comparing count
            # magnitude across incompatible acquisition settings is meaningless.
            if not settings_ok(entries):
                print("  %s %s: incompatible acquisition settings across conditions"
                      % (chip, name))
                continue
            cs = [c for a, b in combinations(entries, 2)
                  for c in [correlation(a[2], b[2])] if c is not None]
            if cs:
                print("  %s %s: cross-condition pattern r=%+.3f over %d condition pair(s)"
                      % (chip, name, mean(cs), len(cs)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_files", metavar="CSV", nargs="+")
    ap.add_argument("--positions", help="ro/x_um/y_um CSV for a geometry-based pairing")
    args = ap.parse_args(argv)
    try:
        groups = load_files(args.csv_files)
    except (OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if not groups:
        print("error: no measurement rows found", file=sys.stderr)
        return 2

    pairings = [("logical-pair", LOGICAL_PAIRS)]
    if args.positions:
        geo = load_positions(args.positions)
        if geo:
            pairings.append(("geometric-pair", geo))
        else:
            print("note: --positions ignored (incomplete or nan coordinates)", file=sys.stderr)

    print_summaries(groups)
    print_across_chips(groups, pairings)
    print_reliability(groups, pairings)
    print_across_conditions(groups, pairings)
    print("\nDescriptive metrics only. The physical die is the unit; pairwise "
          "chip/condition counts are dependent, so read the bootstrap-by-chip "
          "interval, not the pair count, as the sample size. Hamming distance and "
          "correlation are not entropy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
