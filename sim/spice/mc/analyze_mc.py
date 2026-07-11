#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Analyze the v2 Monte Carlo log (one matched oscillator, mismatch-only
common draws) and turn it into the real-entropy numbers.

  python3 analyze_mc.py mc_out.txt

Chain of reasoning, spelled out because it will go in the paper:
1. Each run redraws the GLOBAL mismatch parameters once, so all 31 in-loop
   nfets shift together and all 31 pfets shift together. The measured
   run-to-run sigma is the "common draw" sigma.
2. On real silicon every device draws independently. With equal per-stage
   sensitivities, variances add: sigma_ring = sigma_common / sqrt(31).
3. From sigma_ring we synthesize virtual chips (16 independent matched
   oscillators each) and compute the uniqueness of an 8-bit
   neighbour-comparison key. Ideal is 50%.
4. The fake-to-real ratio compares Arm A's measured layout spread (std
   1.34% in the submitted dual-arm chip) to sigma_ring.
"""
import sys, re, math, random

N_CLASS   = 31          # in-loop devices per class (31 nfets, 31 pfets)
ARM_A_STD = 1.34        # % of mean, dual-arm build (verify_dualarm.py)
ARM_A_PTP = 5.38        # % of mean, same source
N_CHIPS   = 1000
EXPECT_F  = 569.51e6    # nominal matched frequency (sanity check)

def main(path):
    txt = open(path).read()
    f = [float(m.group(1)) for m in re.finditer(r'^f0 = ([0-9.e+-]+)', txt, re.M)]
    if len(f) < 5:
        print(f"only {len(f)} runs found in {path}; something went wrong"); return
    n = len(f)
    mean = sum(f)/n
    sig_common = math.sqrt(sum((x-mean)**2 for x in f)/(n-1))/mean*100
    sig_ring = sig_common/math.sqrt(N_CLASS)

    print(f"runs parsed: {n}")
    print(f"mean frequency: {mean/1e6:.2f} MHz "
          f"(nominal 569.51, deviation {100*(mean-EXPECT_F)/EXPECT_F:+.2f}%)")
    print(f"common-draw sigma (all devices of a class together): {sig_common:.3f}%")
    print(f"derived per-ring mismatch sigma (/sqrt({N_CLASS})): {sig_ring:.3f}%")

    random.seed(1)
    chips = [[random.gauss(0, sig_ring) for _ in range(16)] for _ in range(N_CHIPS)]
    keys = [[1 if c[2*b] > c[2*b+1] else 0 for b in range(8)] for c in chips]
    hd = 0; pairs = 0
    for i in range(0, N_CHIPS-1, 2):     # disjoint pairs, plenty for the mean
        hd += sum(a != b for a, b in zip(keys[i], keys[i+1])); pairs += 1
    uniq = hd/(pairs*8)*100
    print(f"virtual-chip uniqueness ({N_CHIPS} chips, 8-bit neighbour key): "
          f"{uniq:.1f}%  (ideal 50)")
    print(f"fake-to-real, std vs std: Arm A layout {ARM_A_STD}% / mismatch "
          f"{sig_ring:.3f}% = {ARM_A_STD/max(sig_ring,1e-12):.1f}x")
    print(f"fake-to-real, worst case: Arm A p-p {ARM_A_PTP}% is "
          f"{ARM_A_PTP/max(sig_ring,1e-12):.0f}x the mismatch sigma")
    print("Interpretation: on the matched arm only mismatch separates the")
    print("oscillators (real entropy). On the auto-placed arm the layout bias")
    print("is this many times larger, and it is the same on every die.")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mc_out.txt")
