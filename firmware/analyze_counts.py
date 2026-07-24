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
LOW_MARGIN_SIGMA = 3.0  # pair margin below this multiple of repeat noise = fragile


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
        measured = {}
        if meta:
            setting = (meta.get("clk_hz_requested"), meta.get("window"))
            for k in ("clk_hz_measured", "vdd_v_measured", "temp_c_measured"):
                v = meta.get(k)
                if v:
                    measured[k] = v
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
                 "settings": set(), "timeouts": 0, "saturated": 0,
                 "measured": {}})
            g["sources"].add(path)
            g["runs"].add(run_id)
            g["settings"].add(setting)
            g["measured"].update(measured)
            if count < 0:
                g["timeouts"] += 1
                continue
            if count >= 65000:
                g["saturated"] += 1
            g["raw"].setdefault((arm, idx), []).append(count)
            g["by_round"].setdefault((run_id, rnd), {})[(arm, idx)] = count
    return groups


def osc_means(g, arm):
    # Per-run means first, then average the runs, so one long run cannot
    # outweigh a short one for the same chip/condition.
    per_run = {}
    for (run_id, rnd), rc in g["by_round"].items():
        for (a, idx), c in rc.items():
            if a == arm:
                per_run.setdefault(run_id, {}).setdefault(idx, []).append(c)
    out = {}
    for idx in range(NRO):
        run_means = [mean(v[idx]) for v in per_run.values() if idx in v]
        if run_means:
            out[idx] = mean(run_means)
    return out


def centered(vec):
    # Remove the chip-wide speed offset: (f - mean) / mean. The scientific
    # object is the spatial pattern, not how fast the whole chip is.
    m = mean(vec)
    return [(x - m) / m for x in vec]


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


# Tolerances for measured values, applied when both runs recorded them.
CLK_TOL = 0.001     # 0.1% relative on measured reference clock
VDD_TOL = 0.02      # volts
TEMP_TOL = 3.0      # degrees C


def settings_ok(entries):
    ss = []
    meas = []
    for e in entries:
        s = e[1]["settings"]
        if len(s) != 1 or None in s:
            return False
        ss.append(next(iter(s)))
        meas.append(e[1].get("measured", {}))
    if len(set(ss)) != 1:
        return False
    # Requested settings match; now compare measured values where present.
    # A shared label like room_1v8 is not experimental control by itself.
    def spread_bad(key, tol, relative=False):
        vals = [m[key] for m in meas if m.get(key)]
        if len(vals) < 2:
            return False
        lo, hi = min(vals), max(vals)
        return ((hi - lo) / lo > tol) if relative else ((hi - lo) > tol)
    if spread_bad("clk_hz_measured", CLK_TOL, relative=True):
        return False
    if spread_bad("vdd_v_measured", VDD_TOL):
        return False
    if spread_bad("temp_c_measured", TEMP_TOL):
        return False
    return True


def bit_reliability(g, arm, pairs):
    """Enrollment/evaluation bit-error rate and a margin-based fragile count.

    The reference bit for each pair is enrolled from the first half of the
    rounds only; the error rate is evaluated on the held-out second half.
    Deciding the reference from the same rounds it is scored on would
    understate the error. A pair is fragile when its mean separation is
    below LOW_MARGIN_SIGMA times its own repeat noise."""
    keys = sorted(g["by_round"])
    if len(keys) < 4:
        return None, None, 0
    half = len(keys) // 2
    enroll = [g["by_round"][k] for k in keys[:half]]
    evaluate = [g["by_round"][k] for k in keys[half:]]

    def votes_in(rounds, l, r):
        out = []
        for rc in rounds:
            if (arm, l) in rc and (arm, r) in rc and rc[(arm, l)] != rc[(arm, r)]:
                out.append(int(rc[(arm, l)] > rc[(arm, r)]))
        return out

    fragile = 0
    bers = []
    for l, r in pairs:
        ev = votes_in(enroll, l, r)
        hv = votes_in(evaluate, l, r)
        if not ev or not hv:
            continue
        ref = 1 if sum(ev) * 2 >= len(ev) else 0
        bers.append(mean([int(v != ref) for v in hv]))
        ml = g["raw"].get((arm, l))
        mr = g["raw"].get((arm, r))
        if ml and mr and len(ml) > 1 and len(mr) > 1:
            noise = max(population_sd(ml), population_sd(mr), 1e-9)
            if abs(mean(ml) - mean(mr)) < LOW_MARGIN_SIGMA * noise:
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


def loco_scores(vectors):
    """Leave-one-chip-out template correlation, one score per chip.

    For each chip, build the mean centered pattern of the other chips and
    correlate the held-out chip's centered pattern against it. This gives a
    per-chip repeatability score and avoids treating dependent chip pairs as
    a large sample."""
    if len(vectors) < 3:
        return None
    cvs = {k: centered(v) for k, v in vectors.items()}
    scores = {}
    for k in cvs:
        rest = [cvs[j] for j in cvs if j != k]
        template = [mean([r[i] for r in rest]) for i in range(NRO)]
        c = correlation(cvs[k], template)
        if c is not None:
            scores[k] = c
    return scores or None


def paired_delta_ci(scores_a, scores_b, reps=BOOTSTRAP):
    """Bootstrap the mean Arm A - Arm B LOCO-score difference over chips.

    Scores are per-chip numbers, so the resample unit is the chip and the
    statistic is a plain mean of paired differences."""
    common = sorted(set(scores_a) & set(scores_b))
    if len(common) < 3:
        return None
    diffs = [scores_a[c] - scores_b[c] for c in common]
    rng = random.Random(20260723)
    samples = []
    for _ in range(reps):
        pick = [rng.choice(diffs) for _ in diffs]
        samples.append(mean(pick))
    samples.sort()
    lo = samples[int(0.025 * len(samples))]
    hi = samples[min(len(samples) - 1, int(0.975 * len(samples)))]
    return mean(diffs), lo, hi, len(common)


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
            cvecs = [centered(v) for v in vectors.values()]
            point = mean_pairwise_corr(cvecs)
            ci = boot_ci(vectors, list(vectors),
                         lambda vs: mean_pairwise_corr([centered(v) for v in vs]))
            ratio = shared_position_ratio(cvecs)
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


def print_primary_delta(groups):
    print("\n== Primary comparison: Arm A minus Arm B pattern repeatability")
    print("   (leave-one-chip-out template correlation per chip, paired by chip)")
    for cond in sorted({c for _, c in groups}):
        per_arm = {}
        for arm in (0, 1):
            entries = []
            for (chip, gc), g in sorted(groups.items()):
                if gc != cond:
                    continue
                vec = complete_vector(g, arm)
                if vec is not None:
                    entries.append((chip, g, vec))
            if len(entries) >= 3 and settings_ok(entries):
                per_arm[arm] = loco_scores({c: v for c, _, v in entries})
        a, b = per_arm.get(0), per_arm.get(1)
        if not a or not b:
            print("  %s: needs complete, compatible data from >=3 chips in both arms"
                  % cond)
            continue
        res = paired_delta_ci(a, b)
        if res is None:
            print("  %s: fewer than 3 chips with both arms complete" % cond)
            continue
        d, lo, hi, n = res
        print("  %s: mean LOCO r  A=%.3f  B=%.3f  ->  delta=%+.3f "
              "[bootstrap 95%%: %+.3f, %+.3f], n_chips=%d"
              % (cond, mean(list(a.values())), mean(list(b.values())), d, lo, hi, n))
        print("    prediction: delta > 0 (Arm A pattern repeats across chips more"
              " than Arm B). An interval covering 0 means not resolved.")


def print_reliability(groups, pairings):
    print("\n== Bit reliability within chip/condition (needs repeated rounds)")
    for (chip, cond), g in sorted(groups.items()):
        for arm, name in ((0, "Arm A"), (1, "Arm B")):
            for label, pairs in pairings:
                ber, fragile, nb = bit_reliability(g, arm, pairs)
                if ber is None:
                    continue
                print("  %s/%s %s %s: held-out BER %.3f over %d pairs, "
                      "%d low-margin (<%.0f sigma)"
                      % (chip, cond, name, label, ber, nb, fragile,
                         LOW_MARGIN_SIGMA))


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
    print_primary_delta(groups)
    print_reliability(groups, pairings)
    print_across_conditions(groups, pairings)
    print("\nDescriptive metrics only. The physical die is the unit; pairwise "
          "chip/condition counts are dependent, so read the bootstrap-by-chip "
          "interval, not the pair count, as the sample size. Hamming distance and "
          "correlation are not entropy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
