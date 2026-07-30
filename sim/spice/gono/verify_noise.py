#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""
Independent consistency check of the noise-floor result (re-derives it from raw
logs). Fresh code, raw inputs only: the twelve ngspice logs and the archived
nominal log. It imports nothing from analyze_noise.py, so a mistake in that
script cannot pass this one, and it hardcodes the figures that appear in the
paper and the results writeup so that editing a log without editing the prose
fails here rather than in review.

Everything checked is arithmetic on printed frequencies. The thermal-jitter
estimate is not checked against a number, because it depends on a modelling
choice (gamma, and which capacitance counts as the node load) rather than on the
logs alone; what is checked is that it stays well under the counter granularity,
which is the claim the writeup actually makes.
"""
import math
import os
import re
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NOM = os.path.join(PROJ, "dualarm", "build_current", "dualarm_par_out.txt")

PAIRS = [(i, i + 1) for i in range(0, 16, 2)]
WINDOW, FREF = 1000, 25e6
SIGMA_RING, RESIDUAL = 0.062, 0.183

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"PASS  {name}" + (f"   [{detail}]" if detail else ""))
    else:
        fail += 1
        print(f"FAIL  {name}" + (f"   [{detail}]" if detail else ""))


def log(name):
    return name if os.path.isabs(name) else os.path.join(HERE, name)


def freqs(path):
    txt = open(path, errors="ignore").read()
    d = {int(m.group(1)): float(m.group(2)) / 1e6
         for m in re.finditer(r"^f(\d+)\s*=\s*([0-9.eE+-]+)", txt, re.M)}
    return [d[i] for i in sorted(d)]


def ran_at(path):
    m = re.search(r"analysis at TEMP\s*=\s*(-?[0-9.]+)",
                  open(path, errors="ignore").read())
    return float(m.group(1)) if m else None


nom = freqs(NOM)
vlog = {162: "noise_vdd_1620_out.txt", 180: "noise_vdd_1800_out.txt",
        198: "noise_vdd_1980_out.txt"}
v = {k: freqs(log(p2)) for k, p2 in vlog.items()}
tlog = {-40: "noise_temp_m40_out.txt", 0: "noise_temp_000_out.txt",
        27: "noise_vdd_1800_out.txt", 85: "noise_temp_085_out.txt",
        125: "noise_temp_125_out.txt"}
tt = {k: freqs(log(p)) for k, p in tlog.items()}
glog = {(1.62, -40): "noise_vt_1620_m40_out.txt", (1.62, 125): "noise_vt_1620_125_out.txt",
        (1.98, -40): "noise_vt_1980_m40_out.txt", (1.98, 125): "noise_vt_1980_125_out.txt"}
gg = {k: freqs(log(p)) for k, p in glog.items()}

print("== provenance ==")
check("the 1.80 V deck returns the archived nominal frequencies to 1e-9 MHz",
      max(abs(a - b) for a, b in zip(v[180], nom)) < 1e-9,
      "otherwise these logs are not the shipped layout")
check("every supply log ran at 27 C",
      all(ran_at(log(p2)) == 27 for p2 in vlog.values()))
check("every temperature log ran at the temperature its deck asked for",
      all(abs(ran_at(log(p)) - k) < 0.5 for k, p in tlog.items()),
      ", ".join(f"{k}->{ran_at(log(p)):g}" for k, p in sorted(tlog.items())))
check("every grid log ran at the temperature its deck asked for",
      all(abs(ran_at(log(p)) - k[1]) < 0.5 for k, p in glog.items()))
check("all twelve logs hold sixteen frequencies",
      all(len(f) == 16 for f in list(v.values()) + list(tt.values()) + list(gg.values())))

print("\n== supply ==")
push = [(c - a) / (1.98 - 1.62) / b * 100 for a, b, c in zip(v[162], v[180], v[198])]
check("fitted pushing figure is 105.9 percent per volt",
      abs(st.fmean(push) - 105.88) < 0.01, f"{st.fmean(push):.2f}")
check("the sixteen pushing figures span 105.57 to 106.17",
      abs(min(push) - 105.57) < 0.01 and abs(max(push) - 106.17) < 0.01,
      f"{min(push):.2f} to {max(push):.2f}")
for tag, f, want_sd, want_worst in ((162, v[162], 0.027, 0.048), (198, v[198], 0.034, 0.063)):
    r = [a / b for a, b in zip(f, nom)]
    mr = st.fmean(r)
    sd = st.pstdev(r) * 100
    worst = max(abs(x - mr) for x in r) * 100
    check(f"at {tag/100:.2f} V the ring-to-ring departure is {want_sd} percent SD, "
          f"worst ring {want_worst}",
          abs(sd - want_sd) < 0.001 and abs(worst - want_worst) < 0.001,
          f"{sd:.3f} and {worst:.3f}")
check("both differential terms stay under the mismatch scale",
      all(st.pstdev([a / b for a, b in zip(f, nom)]) * 100 < SIGMA_RING
          for f in (v[162], v[198])))

print("\n== temperature ==")
means = {k: st.fmean(f) for k, f in tt.items()}
check("the 1.80 V curve is 549.7, 553.4, 554.7, 555.1, 553.9 MHz",
      [round(means[k], 1) for k in (-40, 0, 27, 85, 125)]
      == [549.7, 553.4, 554.7, 555.1, 553.9])
check("the curve turns over inside the range instead of sloping",
      max(means, key=means.get) == 85)
span = (max(means.values()) - min(means.values())) / st.fmean(list(means.values())) * 100
check("the whole -40 to 125 C range moves the mean by 0.97 percent",
      abs(span - 0.97) < 0.01, f"{span:.2f}")
disp = [round((max(tt[k]) - min(tt[k])) / st.fmean(tt[k]) * 100, 2)
        for k in sorted(tt)]
check("dispersion falls monotonically 5.66, 5.58, 5.53, 5.43, 5.36 percent",
      disp == [5.66, 5.58, 5.53, 5.43, 5.36] and disp == sorted(disp, reverse=True))

at = {k: st.fmean(f) for k, f in gg.items()}
at[(1.62, 27)], at[(1.98, 27)] = st.fmean(v[162]), st.fmean(v[198])
tc = {sv: (at[(sv, 125)] - at[(sv, -40)]) / 165.0 / at[(sv, 27)] * 100
      for sv in (1.62, 1.98)}
tc[1.80] = (means[125] - means[-40]) / 165.0 / means[27] * 100
check("the coefficient is +0.053, +0.005 and -0.024 percent per degree at "
      "1.62, 1.80 and 1.98 V",
      [round(tc[sv], 3) for sv in (1.62, 1.80, 1.98)] == [0.053, 0.005, -0.024])
check("it falls with rising supply and changes sign, which is the crossover "
      "prediction the writeup makes",
      tc[1.62] > tc[1.80] > tc[1.98] and tc[1.62] > 0 > tc[1.98])

print("\n== response bits ==")
ref = [nom[a] > nom[b] for a, b in PAIRS]
every = list(v.values()) + [tt[k] for k in tt if k != 27] + list(gg.values())
check("eleven operating points are covered", len(every) == 11, f"{len(every)}")
check("all eight pair bits keep their sign at every one of them",
      all([f[a] > f[b] for a, b in PAIRS] == ref for f in every))
marg = [abs(nom[a] - nom[b]) / st.fmean(nom) * 100 for a, b in PAIRS]
check("the tightest pair is separated by 0.270 percent of the arm mean",
      abs(min(marg) - 0.270) < 0.001, f"{min(marg):.3f}, pair {marg.index(min(marg))}")
worst = max(max(abs(x / y - st.fmean([p / q for p, q in zip(f, nom)]))
                for x, y in zip(f, nom)) * 100 for f in every)
check("the largest ring-to-ring departure anywhere in the box is 0.150 percent",
      abs(worst - 0.150) < 0.001, f"{worst:.3f}")
check("so the margin on the tightest pair is 1.8, which the writeup does not "
      "round up", abs(min(marg) / worst - 1.8) < 0.05, f"{min(marg)/worst:.2f}")

print("\n== resolution floor ==")
n = st.fmean(nom) * 1e6 * WINDOW / FREF
quant, rms = 100.0 / n, 100.0 / (math.sqrt(12.0) * n)
check("the window holds 22189 ring periods", round(n) == 22189, f"{n:.0f}")
check("one count is 0.00451 percent and the rounding error is 0.00130 rms",
      abs(quant - 0.00451) < 1e-5 and abs(rms - 0.00130) < 1e-5)
jit = 0.94e-12
frac = jit / (math.sqrt(n) * (1.0 / (st.fmean(nom) * 1e6))) * 100
check("averaged thermal jitter stays well under the counter granularity, so the "
      "counter is the floor", frac < rms / 2.0,
      f"{frac:.5f} against {rms:.5f}")
check("the floor sits 48, 207 and 141 times below the mismatch scale, the "
      "tightest pair and the compensation residual",
      round(SIGMA_RING / rms) == 48 and round(min(marg) / rms) == 207
      and round(RESIDUAL / rms) == 141)

print()
print(f"== SUMMARY ==  {ok} passed, {fail} failed")
print(f"Resolution floor {rms:.5f} percent, set by counter granularity rather "
      f"than by the oscillator.")
print(f"Supply sensitivity {st.fmean(push):.1f} percent per volt, almost entirely "
      f"common to the sixteen rings.")
print(f"Temperature coefficient at 1.80 V {tc[1.80]:+.4f} percent per degree, "
      f"crossing zero between 1.62 and 1.98 V.")
raise SystemExit(1 if fail else 0)
