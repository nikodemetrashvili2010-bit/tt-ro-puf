#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Monte Carlo uniqueness study for the two-arm RO-PUF.

Models many chips and compares the two arms:

  Arm A  frequency = shared layout bias (same on every chip) + random mismatch
  Arm B  frequency = random mismatch only (the shared bias is removed by layout)

Each chip's key is a set of pairwise oscillator comparisons. We then measure the
inter-chip fractional Hamming distance, the fraction of key bits that differ
between two different chips, averaged over all chip pairs. The ideal for a PUF
is 0.5.

Expected: Arm A sits far below 0.5 because the shared bias makes every chip
produce nearly the same key (fake entropy). Arm B sits near 0.5 because only
the independent random mismatch decides each bit (real entropy).

Pure standard library, no external packages.
"""

import random
from itertools import combinations

N_CHIPS        = 200
N_PER_ARM      = 16
N_BITS         = N_PER_ARM // 2     # consecutive pairs -> 8 comparison bits
SIGMA_SPATIAL  = 5.0                # shared deterministic layout bias (Arm A)
SIGMA_MISMATCH = 0.5                # random per-chip variation (both arms)
SEED           = 1


def make_keys(spatial):
    """One key per chip. Each chip adds independent random mismatch to the
    shared spatial bias, then compares oscillators in pairs."""
    keys = []
    for _ in range(N_CHIPS):
        f = [spatial[i] + random.gauss(0.0, SIGMA_MISMATCH) for i in range(N_PER_ARM)]
        keys.append([1 if f[2 * k] > f[2 * k + 1] else 0 for k in range(N_BITS)])
    return keys


def mean_uniqueness(keys):
    """Mean inter-chip fractional Hamming distance over all chip pairs."""
    total, pairs = 0.0, 0
    for a, b in combinations(range(len(keys)), 2):
        total += sum(x != y for x, y in zip(keys[a], keys[b])) / N_BITS
        pairs += 1
    return total / pairs


def uniformity(keys):
    return sum(sum(k) for k in keys) / (len(keys) * N_BITS)


def main():
    random.seed(SEED)

    spatial_A = [random.gauss(0.0, SIGMA_SPATIAL) for _ in range(N_PER_ARM)]
    spatial_B = [0.0] * N_PER_ARM

    keys_A = make_keys(spatial_A)
    keys_B = make_keys(spatial_B)

    print(f"chips = {N_CHIPS}, bits per chip = {N_BITS}")
    print(f"sigma_spatial = {SIGMA_SPATIAL}, sigma_mismatch = {SIGMA_MISMATCH}")
    print()
    print(f"Arm A inter-chip uniqueness: {mean_uniqueness(keys_A) * 100:5.1f} %   (ideal 50; low means fake entropy)")
    print(f"Arm B inter-chip uniqueness: {mean_uniqueness(keys_B) * 100:5.1f} %   (ideal 50; this is real entropy)")
    print()
    print(f"Arm A uniformity: {uniformity(keys_A) * 100:5.1f} %")
    print(f"Arm B uniformity: {uniformity(keys_B) * 100:5.1f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
