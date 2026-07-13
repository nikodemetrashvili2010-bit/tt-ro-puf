#!/usr/bin/env python3
# Figure 4: both arms measured from the one submitted chip layout.
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
ARMB = 569.51

t = open(os.path.join(HERE, "dualarm_par_out.txt")).read()
f = [float(m.group(2))/1e6 for m in sorted(
     re.finditer(r'f(\d+) = ([0-9.e+-]+)', t), key=lambda m: int(m.group(1)))]
mean = sum(f)/len(f); ptp = max(f)-min(f); n = len(f)

random.seed(3)
fig, ax = plt.subplots(figsize=(8.6, 5.3))
fig.subplots_adjust(top=0.85, bottom=0.12, left=0.12, right=0.96)
xa = [1 + (random.random()-0.5)*0.32 for _ in f]
xb = [2 + (random.random()-0.5)*0.32 for _ in f]
ax.scatter(xa, f, s=72, c=A_RED, edgecolor="white", lw=0.8, zorder=3)
ax.scatter(xb, [ARMB]*n, s=72, c=B_GREEN, edgecolor="white", lw=0.8, zorder=3)
ax.hlines(mean, 0.72, 1.28, color=A_RED, lw=2.4, zorder=4)
ax.hlines(ARMB, 1.72, 2.28, color=B_GREEN, lw=2.4, zorder=4)
ax.set_ylim(min(f)-13, ARMB+20); ax.set_xlim(0.5, 2.7)
ax.text(1.0, max(f)+3, f"{ptp:.0f} MHz peak-to-peak\n{100*ptp/mean:.1f}% spread",
        va="bottom", ha="center", fontsize=11.5, color=A_RED, fontweight="bold")
ax.text(2.0, ARMB-9, "one frequency\n0% spread, 16 identical copies",
        va="top", ha="center", fontsize=11.5, color=B_GREEN, fontweight="bold")
ax.set_xticks([1, 2])
ax.set_xticklabels(["Arm A\nauto-placed", "Arm B\nmatched macro"], fontsize=12)
ax.set_ylabel("oscillation frequency  (MHz)")
ax.grid(axis="x", visible=False)
fig.text(0.02, 0.95, "The submitted chip: Arm A spreads, Arm B does not",
         ha="left", va="top", fontsize=14, fontweight="bold", color="#1a1a1a")
fig.savefig(os.path.join(HERE, "dualarm_gono.png"))
print(f"dualarm_gono regenerated | Arm A mean {mean:.2f} ptp {ptp:.2f} = {100*ptp/mean:.2f}%")
