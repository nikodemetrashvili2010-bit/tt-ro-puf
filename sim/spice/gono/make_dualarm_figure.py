#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

# Figure 4: nominal lumped-C predictions for the archived dual-arm layout.
import os, re, random
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({
    "figure.dpi": 200, "savefig.dpi": 200,
    "figure.facecolor": "white", "savefig.facecolor": "white",
    "font.size": 12, "axes.labelsize": 12,
    "axes.edgecolor": "#4d4d4d", "axes.linewidth": 1.0,
    "axes.spines.top": False, "axes.spines.right": False,
    "xtick.color": "#333333", "ytick.color": "#333333",
    "xtick.labelsize": 11, "ytick.labelsize": 11,
    "text.color": "#1a1a1a", "axes.labelcolor": "#1a1a1a",
    "axes.grid": True, "axes.axisbelow": True,
    "grid.color": "#e8e8e8", "grid.linewidth": 0.8, "legend.frameon": False,
})
A_RED, B_GREEN = "#c0504d", "#3a8a5f"
HERE = os.path.dirname(os.path.abspath(__file__))

def read_named(path, name):
    pattern = re.compile(rf'^{re.escape(name)}\s*=\s*([0-9.eE+\-]+)')
    for line in open(path):
        match = pattern.match(line)
        if match:
            return float(match.group(1))
    raise ValueError(f"{name} not found in {path}")

ARMB = read_named(os.path.join(HERE, "macro_out.txt"), "f_b") / 1e6
t = open(os.path.join(HERE, "..", "..", "..", "dualarm", "build_current", "dualarm_par_out.txt")).read()
f = [float(m.group(2))/1e6 for m in sorted(re.finditer(r'f(\d+) = ([0-9.e+-]+)', t), key=lambda m: int(m.group(1)))]
mean = sum(f)/len(f); ptp = max(f)-min(f); n = len(f); pct = 100*ptp/mean
random.seed(3)
fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.5, 5.0), gridspec_kw={"width_ratios": [1.5, 1]})
fig.subplots_adjust(top=0.85, bottom=0.14, left=0.08, right=0.97, wspace=0.32)
xa = [1 + (random.random()-0.5)*0.30 for _ in f]
axL.scatter(xa, f, s=64, c=A_RED, edgecolor="white", lw=0.7, zorder=3)
axL.hlines(mean, 0.74, 1.26, color=A_RED, lw=2.4, zorder=4)
axL.hlines(ARMB, 1.60, 2.40, color=B_GREEN, lw=3.0, zorder=4)
axL.set_ylim(min(f)-14, ARMB+14); axL.set_xlim(0.55, 2.5)
axL.text(1.0, max(f)+3, f"{ptp:.0f} MHz peak-to-peak", va="bottom", ha="center", fontsize=10.5, color=A_RED, fontweight="bold")
axL.text(2.0, ARMB-6, f"{ARMB:.1f} MHz reference\n(one simulation, shared GDS)", va="top", ha="center", fontsize=10.5, color=B_GREEN, fontweight="bold")
axL.set_xticks([1, 2]); axL.set_xticklabels(["Arm A\nauto-placed", "Arm B\nmatched macro"], fontsize=11)
axL.set_ylabel("oscillation frequency  (MHz)")
axL.set_title("(a)  per-oscillator frequency", loc="left", fontsize=11.5, color="#444444", pad=8)
axL.grid(axis="x", visible=False)
bars = axR.bar([0], [pct], color=[A_RED], edgecolor="white", linewidth=0.8, width=0.62)
axR.set_ylim(0, pct*1.28)
for rect, v, c in zip(bars, [pct], [A_RED]):
    axR.text(rect.get_x()+rect.get_width()/2, v+pct*0.02, f"{v:.1f}%", ha="center", va="bottom", fontsize=12, fontweight="bold", color=c)
axR.set_xlim(-0.6, 1.6)
axR.set_xticks([0, 1]); axR.set_xticklabels(["Arm A", "Arm B"])
axR.text(1, pct*0.24, "0% by construction\n(same internal GDS)", ha="center", va="center", fontsize=10.5, color=B_GREEN, fontweight="bold")
axR.set_ylabel("modeled internal-layout spread  (%, peak-to-peak)")
axR.set_title("(b)  modeled internal-layout spread", loc="left", fontsize=11.5, color="#444444", pad=8)
axR.grid(axis="x", visible=False)
fig.text(0.02, 0.95, "The dual-arm chip: Arm A spreads, Arm B is one layout", ha="left", va="top", fontsize=14, fontweight="bold", color="#1a1a1a")
fig.savefig(os.path.join(HERE, "dualarm_gono.png"))
print(f"dualarm_gono | Arm A mean {mean:.2f} ptp {ptp:.2f} = {pct:.2f}%")
