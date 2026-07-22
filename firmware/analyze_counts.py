#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Summarize RO-PUF measurements without mixing chips or conditions.

Labels must have the form ``chip_id_condition``.  The first underscore
separates the chip identifier from the condition, so ``chip03_room_1v8`` and
``chip03_freeze_1v8`` are two conditions measured on the same chip.
"""

import argparse
import csv
import math
import re
import sys
from itertools import combinations


NRO = 16
BIT_PAIRS = tuple((i, i + 1) for i in range(0, NRO, 2))
META_RE = re.compile(r"\b(clk|window|repeats)=([^\s]+)")


def split_label(label):
    """Return ``(chip_id, condition)`` from the measurement label."""
    label = label.strip()
    if "_" not in label:
        raise ValueError(
            f"label {label!r} has no condition; use chip_id_condition"
        )
    chip_id, condition = label.split("_", 1)
    if not chip_id or not condition:
        raise ValueError(
            f"label {label!r} must contain both a chip id and a condition"
        )
    return chip_id, condition


def parse_metadata(lines):
    """Read the clock/window tuple emitted by ``measure_puf.py``."""
    for line in lines:
        if line.startswith("# tt_ro_puf measurement"):
            fields = dict(META_RE.findall(line))
            try:
                return int(fields["clk"]), int(fields["window"])
            except (KeyError, ValueError):
                return None
    return None


def load_files(paths):
    groups = {}
    for path in paths:
        with open(path, encoding="utf-8", newline="") as handle:
            lines = handle.readlines()
        setting = parse_metadata(lines)
        rows = csv.DictReader(line for line in lines if not line.startswith("#"))
        required = {"label", "arm", "idx", "count"}
        if not rows.fieldnames or not required.issubset(rows.fieldnames):
            missing = sorted(required.difference(rows.fieldnames or ()))
            raise ValueError(f"{path}: missing CSV column(s): {', '.join(missing)}")

        for line_number, row in enumerate(rows, 2):
            try:
                label = row["label"].strip()
                chip_id, condition = split_label(label)
                arm = int(row["arm"])
                idx = int(row["idx"])
                count = int(row["count"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            if arm not in (0, 1) or not 0 <= idx < NRO:
                raise ValueError(
                    f"{path}:{line_number}: arm/index out of range ({arm}, {idx})"
                )

            key = (chip_id, condition)
            group = groups.setdefault(
                key,
                {"raw": {}, "sources": set(), "settings": set(), "timeouts": 0},
            )
            group["sources"].add(path)
            # Keep a missing header visible.  Silently borrowing metadata from
            # another file in the same group could make incomparable captures
            # look compatible.
            group["settings"].add(setting)
            if count < 0:
                group["timeouts"] += 1
                continue
            group["raw"].setdefault((arm, idx), []).append(count)
    return groups


def mean(values):
    return sum(values) / len(values)


def population_sd(values):
    centre = mean(values)
    return math.sqrt(mean([(value - centre) ** 2 for value in values]))


def oscillator_means(group, arm):
    return {
        idx: mean(samples)
        for (sample_arm, idx), samples in group["raw"].items()
        if sample_arm == arm and samples
    }


def complete_vector(group, arm):
    values = oscillator_means(group, arm)
    if set(values) != set(range(NRO)):
        return None
    return [values[idx] for idx in range(NRO)]


def response_bits(vector):
    """Eight fixed adjacent-pair bits, or ``None`` if a pair is tied."""
    bits = []
    for left, right in BIT_PAIRS:
        if vector[left] == vector[right]:
            return None
        bits.append(int(vector[left] > vector[right]))
    return bits


def correlation(first, second):
    first_mean = mean(first)
    second_mean = mean(second)
    a = [value - first_mean for value in first]
    b = [value - second_mean for value in second]
    scale = math.sqrt(sum(value * value for value in a)) * math.sqrt(
        sum(value * value for value in b)
    )
    if scale == 0:
        return None
    return sum(x * y for x, y in zip(a, b)) / scale


def hamming_percent(first, second):
    return 100.0 * sum(a != b for a, b in zip(first, second)) / len(first)


def compatible_settings(entries):
    settings = []
    for _, group, _ in entries:
        if len(group["settings"]) != 1 or None in group["settings"]:
            return False
        settings.append(next(iter(group["settings"])))
    return len(set(settings)) == 1


def print_group_summaries(groups):
    for (chip_id, condition), group in sorted(groups.items()):
        sources = ", ".join(sorted(group["sources"]))
        print(f"\n== {chip_id} / {condition}  [{sources}]")
        if group["timeouts"]:
            print(f"  skipped timeout samples: {group['timeouts']}")
        if len(group["settings"]) == 1 and None not in group["settings"]:
            clk, window = next(iter(group["settings"]))
            print(f"  acquisition: clk={clk} Hz, window={window} cycles")
        elif group["settings"] == {None}:
            print("  acquisition metadata: missing")
        else:
            print("  acquisition metadata: missing or inconsistent across files")

        for arm, name in ((0, "Arm A (auto)"), (1, "Arm B (matched)")):
            means = oscillator_means(group, arm)
            if not means:
                print(f"  {name}: no valid data")
                continue
            values = list(means.values())
            centre = mean(values)
            spread = max(values) - min(values)
            sd = population_sd(values)
            repeat_sds = [
                population_sd(samples)
                for (sample_arm, _), samples in group["raw"].items()
                if sample_arm == arm and len(samples) > 1
            ]
            noise_text = (
                f"mean within-oscillator repeat SD {mean(repeat_sds):.2f} counts"
                if repeat_sds
                else "repeat noise unavailable (need at least two valid samples)"
            )
            relative_text = (
                f"{100 * spread / centre:.2f}% p-p, "
                f"SD {sd:.1f} ({100 * sd / centre:.2f}%)"
                if centre != 0
                else f"relative spread unavailable (mean is zero), SD {sd:.1f}"
            )
            print(
                f"  {name}: {len(values)}/{NRO} oscillators, mean {centre:.1f}, "
                f"spread {spread:.1f} ({relative_text}); {noise_text}"
            )


def print_across_chip_metrics(groups):
    print("\n== Across chips at the same condition")
    conditions = sorted({condition for _, condition in groups})
    for condition in conditions:
        print(f"  Condition: {condition}")
        for arm, name in ((0, "Arm A (auto)"), (1, "Arm B (matched)")):
            entries = []
            for (chip_id, group_condition), group in sorted(groups.items()):
                if group_condition != condition:
                    continue
                vector = complete_vector(group, arm)
                if vector is not None:
                    entries.append((chip_id, group, vector))
            if len(entries) < 2:
                print(
                    f"    {name}: insufficient data (need complete measurements "
                    "from at least two distinct chips)"
                )
                continue
            if not compatible_settings(entries):
                print(
                    f"    {name}: insufficient comparable data "
                    "(clock/window metadata missing or inconsistent)"
                )
                continue

            correlations = []
            distances = []
            tied = False
            for first, second in combinations(entries, 2):
                corr = correlation(first[2], second[2])
                if corr is not None:
                    correlations.append(corr)
                first_bits = response_bits(first[2])
                second_bits = response_bits(second[2])
                if first_bits is None or second_bits is None:
                    tied = True
                else:
                    distances.append(hamming_percent(first_bits, second_bits))

            if correlations:
                print(
                    f"    {name}: centred frequency-pattern correlation "
                    f"mean r={mean(correlations):+.3f} over "
                    f"{len(correlations)} chip pair(s)"
                )
            else:
                print(
                    f"    {name}: pattern correlation unavailable "
                    "(one or more patterns have no variation)"
                )
            if distances and not tied:
                print(
                    f"    {name}: 8-bit adjacent-pair uniqueness "
                    f"mean Hamming distance={mean(distances):.1f}% over "
                    f"{len(distances)} chip pair(s)"
                )
            else:
                print(
                    f"    {name}: response uniqueness unavailable "
                    "(a fixed pair tied or a complete response is missing)"
                )


def print_across_condition_metrics(groups):
    print("\n== Same chip across conditions")
    chip_ids = sorted({chip_id for chip_id, _ in groups})
    for chip_id in chip_ids:
        print(f"  Chip: {chip_id}")
        for arm, name in ((0, "Arm A (auto)"), (1, "Arm B (matched)")):
            entries = []
            for (group_chip, condition), group in sorted(groups.items()):
                if group_chip != chip_id:
                    continue
                vector = complete_vector(group, arm)
                if vector is not None:
                    entries.append((condition, group, vector))
            if len(entries) < 2:
                print(
                    f"    {name}: insufficient data (need two complete "
                    "conditions for this chip)"
                )
                continue

            correlations = []
            distances = []
            tied = False
            for first, second in combinations(entries, 2):
                corr = correlation(first[2], second[2])
                if corr is not None:
                    correlations.append(corr)
                first_bits = response_bits(first[2])
                second_bits = response_bits(second[2])
                if first_bits is None or second_bits is None:
                    tied = True
                else:
                    distances.append(hamming_percent(first_bits, second_bits))

            if correlations:
                print(
                    f"    {name}: cross-condition pattern correlation "
                    f"mean r={mean(correlations):+.3f} over "
                    f"{len(correlations)} condition pair(s)"
                )
            else:
                print(
                    f"    {name}: pattern stability unavailable "
                    "(one or more patterns have no variation)"
                )
            if distances and not tied:
                error = mean(distances)
                print(
                    f"    {name}: 8-bit cross-condition response change "
                    f"mean Hamming distance={error:.1f}% "
                    f"(agreement={100 - error:.1f}%)"
                )
            else:
                print(
                    f"    {name}: cross-condition response comparison unavailable "
                    "(a fixed pair tied or a complete response is missing)"
                )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Summarize grouped RO-PUF count CSV files without mixing chips or conditions."
    )
    parser.add_argument("csv_files", metavar="CSV", nargs="+")
    paths = parser.parse_args(argv).csv_files
    try:
        groups = load_files(paths)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not groups:
        print("error: no measurement rows found", file=sys.stderr)
        return 2

    print_group_summaries(groups)
    print_across_chip_metrics(groups)
    print_across_condition_metrics(groups)
    print(
        "\nThese are descriptive metrics for the supplied files. "
        "They do not establish cross-die repeatability or entropy on their own."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
