#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Analyze the v2 Monte Carlo log (one matched oscillator, mismatch-only
common draws) as a first-order mismatch-sensitivity estimate.

  python3 analyze_mc.py mc_out.txt

Chain of reasoning and its limits:
1. Each run redraws the GLOBAL mismatch parameters once, so all 31 in-loop
   nfets shift together and all 31 pfets shift together. The measured
   run-to-run sigma is the "common draw" sigma.
2. On real silicon every device draws independently. With equal per-stage
   sensitivities, a first-order scaling is sigma_ring = sigma_common/sqrt(31).
   This is not a substitute for independent-device Monte Carlo.
3. A virtual IID Gaussian key necessarily has expected uniqueness 50% by
   symmetry. The generated-key result is therefore only a code sanity check,
   not validation of entropy, reliability, or the sqrt(31) model.
4. Arm A and nominal Arm B reference values are re-read from the raw logs.
"""
import sys, re, math, random, os
from statistics import NormalDist

N_CLASS   = 31          # in-loop devices per class (31 nfets, 31 pfets)
N_CHIPS   = 1000
SEED      = 1
HERE      = os.path.dirname(os.path.abspath(__file__))
GONO      = os.path.abspath(os.path.join(HERE, "..", "gono"))
DECK      = os.path.join(HERE, "mc_matched.spice")
MACRO_LOG = os.path.join(GONO, "macro_out.txt")
ARM_A_LOG = os.path.join(GONO, "dualarm_par_out.txt")


def read_scalar(path, name):
    text = open(path).read()
    match = re.search(rf'^{re.escape(name)} = ([0-9.eE+-]+)', text, re.M)
    if not match:
        raise ValueError(f"{name} not found in {path}")
    return float(match.group(1))


def read_indexed(path):
    text = open(path).read()
    values = {int(m.group(1)): float(m.group(2))
              for m in re.finditer(r'^f(\d+) = ([0-9.eE+-]+)', text, re.M)}
    if not values:
        raise ValueError(f"no indexed frequencies found in {path}")
    return [values[i] for i in sorted(values)]


def chi_square_quantile_approx(probability, degrees_of_freedom):
    """Wilson-Hilferty approximation used only for a sampling-uncertainty CI."""
    z = NormalDist().inv_cdf(probability)
    a = 1.0 - 2.0/(9.0*degrees_of_freedom)
    b = z * math.sqrt(2.0/(9.0*degrees_of_freedom))
    return degrees_of_freedom * (a + b)**3


def sigma_ci95(sample_sigma, n):
    """Approximate normal-population 95% CI for sigma via chi-square."""
    df = n - 1
    q025 = chi_square_quantile_approx(0.025, df)
    q975 = chi_square_quantile_approx(0.975, df)
    return (sample_sigma * math.sqrt(df/q975),
            sample_sigma * math.sqrt(df/q025))

def main(path):
    txt = open(path).read()
    f = [float(m.group(1)) for m in re.finditer(r'^f0 = ([0-9.eE+-]+)', txt, re.M)]
    deck_text = open(DECK).read()
    expected_match = re.search(r'dowhile\s+mc_i\s*<\s*(\d+)', deck_text)
    expected_runs = int(expected_match.group(1)) if expected_match else None
    if len(f) < 5 or (expected_runs is not None and len(f) != expected_runs):
        print(f"ERROR: parsed {len(f)} runs from {path}; expected {expected_runs}",
              file=sys.stderr)
        return 1
    n = len(f)
    mean = sum(f)/n
    sample_sigma_hz = math.sqrt(sum((x-mean)**2 for x in f)/(n-1))
    sig_common = sample_sigma_hz/mean*100
    common_lo_hz, common_hi_hz = sigma_ci95(sample_sigma_hz, n)
    common_lo, common_hi = common_lo_hz/mean*100, common_hi_hz/mean*100
    sig_ring = sig_common/math.sqrt(N_CLASS)
    ring_lo, ring_hi = common_lo/math.sqrt(N_CLASS), common_hi/math.sqrt(N_CLASS)

    expect_f = read_scalar(MACRO_LOG, "f_b")
    arm_a = read_indexed(ARM_A_LOG)
    arm_a_mean = sum(arm_a)/len(arm_a)
    arm_a_std = math.sqrt(sum((x-arm_a_mean)**2 for x in arm_a)/len(arm_a))/arm_a_mean*100
    arm_a_ptp = (max(arm_a)-min(arm_a))/arm_a_mean*100

    print(f"runs parsed: {n}")
    print(f"mean frequency: {mean/1e6:.2f} MHz "
          f"(macro raw-log nominal {expect_f/1e6:.2f}, "
          f"deviation {100*(mean-expect_f)/expect_f:+.2f}%)")
    print(f"common-draw sigma (all devices of a class together): {sig_common:.3f}%")
    print(f"  approximate 95% sampling CI: {common_lo:.3f}% .. {common_hi:.3f}%")
    print(f"first-order per-ring sigma estimate (/sqrt({N_CLASS})): {sig_ring:.3f}%")
    print(f"  propagated sampling CI only: {ring_lo:.3f}% .. {ring_hi:.3f}%")
    print("  model uncertainty from correlated PDK draws and unequal device "
          "sensitivities is not quantified")

    random.seed(SEED)
    chips = [[random.gauss(0, sig_ring) for _ in range(16)] for _ in range(N_CHIPS)]
    keys = [[1 if c[2*b] > c[2*b+1] else 0 for b in range(8)] for c in chips]
    hd = 0; pairs = 0
    for i in range(0, N_CHIPS-1, 2):     # disjoint pairs, plenty for the mean
        hd += sum(a != b for a, b in zip(keys[i], keys[i+1])); pairs += 1
    uniq = hd/(pairs*8)*100
    n_bits = pairs * 8
    p = uniq/100.0
    uniq_half_width = 1.96*math.sqrt(p*(1-p)/n_bits)*100
    print(f"IID-symmetry code check ({N_CHIPS} virtual chips, {n_bits} compared bits): "
          f"{uniq:.1f}% (sampling interval about {uniq-uniq_half_width:.1f}% .. "
          f"{uniq+uniq_half_width:.1f}%; analytic expectation 50%)")
    print("  This 50% result follows from the assumed symmetric IID model; "
          "it is not an entropy or reliability validation.")
    ratio = arm_a_std/max(sig_ring, 1e-12)
    ratio_lo = arm_a_std/max(ring_hi, 1e-12)
    ratio_hi = arm_a_std/max(ring_lo, 1e-12)
    print(f"nominal layout-to-mismatch comparison, std/std: Arm A {arm_a_std:.3f}% / "
          f"first-order estimate {sig_ring:.3f}% = {ratio:.1f}x "
          f"(sampling-only range {ratio_lo:.1f}x .. {ratio_hi:.1f}x)")
    print(f"Arm A nominal layout p-p {arm_a_ptp:.3f}% / first-order sigma = "
          f"{arm_a_ptp/max(sig_ring,1e-12):.1f}x")
    print("Interpretation: the nominal extracted layout effect is larger than this "
          "first-order mismatch estimate. Silicon entropy still requires "
          "independent-device, PVT, noise, and repeatability measurements.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else
                          os.path.join(HERE, "mc_out.txt")))
