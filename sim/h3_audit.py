#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
H3 adversarial predictability audit for the two-arm RO-PUF.

An attacker who knows only oscillator position (not the chip) tries to predict
a chip's key. We train a position-based predictor on a subset of chips and test
it on held-out chips:

  Arm A  shared layout bias -> position predicts the key -> high accuracy
  Arm B  random mismatch only -> position carries no secret -> chance (50%)

The predictor is the optimal position-only model: for each bit position, learn
the majority value across the training chips and predict it for every test
chip. A logistic-regression or SVM model reaches the same conclusion; this
version needs no external packages.
"""

import random

N_CHIPS        = 200
N_PER_ARM      = 16
N_BITS         = N_PER_ARM // 2
SIGMA_SPATIAL  = 5.0
SIGMA_MISMATCH = 0.5
TRAIN_FRAC     = 0.7
SEED           = 1


def make_keys(spatial):
    keys = []
    for _ in range(N_CHIPS):
        f = [spatial[i] + random.gauss(0.0, SIGMA_MISMATCH) for i in range(N_PER_ARM)]
        keys.append([1 if f[2 * k] > f[2 * k + 1] else 0 for k in range(N_BITS)])
    return keys


def audit(keys):
    """Train on the first TRAIN_FRAC of chips, test on the rest."""
    n_train = int(len(keys) * TRAIN_FRAC)
    train, test = keys[:n_train], keys[n_train:]

    # Learn the majority bit at each position from the training chips.
    pred = []
    for k in range(N_BITS):
        ones = sum(chip[k] for chip in train)
        pred.append(1 if 2 * ones >= len(train) else 0)

    correct = total = 0
    for chip in test:
        for k in range(N_BITS):
            correct += (chip[k] == pred[k])
            total += 1
    return correct / total


def main():
    random.seed(SEED)
    spatial_A = [random.gauss(0.0, SIGMA_SPATIAL) for _ in range(N_PER_ARM)]
    spatial_B = [0.0] * N_PER_ARM
    keys_A = make_keys(spatial_A)
    keys_B = make_keys(spatial_B)

    train_pct = int(TRAIN_FRAC * 100)
    print(f"chips = {N_CHIPS}, train/test = {train_pct}/{100 - train_pct}, bits per chip = {N_BITS}")
    print()
    print(f"Arm A prediction accuracy on unseen chips: {audit(keys_A) * 100:5.1f} %   (chance 50; high means the layout leaks the key)")
    print(f"Arm B prediction accuracy on unseen chips: {audit(keys_B) * 100:5.1f} %   (chance 50; position carries no secret)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
