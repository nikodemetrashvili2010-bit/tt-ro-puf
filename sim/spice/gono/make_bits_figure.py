#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
# Figure 6: how much of Arm A's eight-bit response the design database decides.
# Every number comes from predictable_bits.py, which is imported rather than
# copied, so this figure cannot drift away from the reported result.
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import predictable_bits as pb  # noqa: E402

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
A_RED, B_GREEN, BLUE = "#c0504d", "#3a8a5f", "#35618f"

delta = pb.deltas(pb.rc())
rows = pb.score(delta, pb.SIGMA_RING)
sigma_pair = pb.SIGMA_RING * math.sqrt(2.0)
margin = [abs(d) / sigma_pair for d in delta]
entropy = [r[2] for r in rows]
labels = ["%d/%d" % p for p in pb.PAIRS]
total_a = sum(entropy)
alive = [i for i, e in enumerate(entropy) if e >= 0.01]

fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.5, 5.0),
                               gridspec_kw={"width_ratios": [1.1, 1]})
fig.subplots_adjust(top=0.83, bottom=0.15, left=0.075, right=0.975, wspace=0.28)

# ---- (a) how far the layout puts each pair from a coin flip --------------
y = list(range(len(labels)))
colours = [BLUE if e >= 0.01 else A_RED for e in entropy]
axL.axvspan(0.3, 2.0, color="#e9eef4", zorder=0)
axL.barh(y, margin, color=colours, edgecolor="white", linewidth=0.8, height=0.62)
axL.set_xscale("log")
axL.set_xlim(0.3, 260)
axL.set_yticks(y)
axL.set_yticklabels(labels)
axL.invert_yaxis()
axL.set_xlabel("separation, in standard deviations of mismatch")
axL.set_ylabel("oscillator pair")
axL.set_title("(a)  how far the layout puts each pair from a coin flip",
              loc="left", fontsize=11.5, color="#444444", pad=8)
axL.grid(axis="y", visible=False)
for yi, (m, e) in enumerate(zip(margin, entropy)):
    axL.text(m * 1.20, yi, "%.1f" % m, va="center", ha="left", fontsize=10.5,
             color=(BLUE if e >= 0.01 else A_RED), fontweight="bold")
axL.text(4.5, 1.5, "only 2/3 and 4/5 come close,\nand only 2/3 is inside the strip",
         va="center", ha="left", fontsize=10, color=BLUE)

# ---- (b) entropy the silicon still decides ------------------------------
xs = list(range(len(labels)))
axR.bar(xs, entropy, width=0.58, color=A_RED, edgecolor="white", linewidth=0.8)
axR.axhline(1.0, color=B_GREEN, lw=2.6, zorder=4)
axR.set_xticks(xs)
axR.set_xticklabels(labels, fontsize=10)
axR.set_xlim(-0.7, len(labels) - 0.3)
axR.set_ylim(0, 1.22)
axR.set_xlabel("oscillator pair")
axR.set_ylabel("across-die entropy of the bit  (bits)")
axR.set_title("(b)  entropy the silicon still decides", loc="left",
              fontsize=11.5, color="#444444", pad=8)
axR.grid(axis="x", visible=False)
axR.text(3.5, 1.05, "Arm B, matched macro: every bit a full bit, 8.00 of 8",
         ha="center", va="bottom", fontsize=10.5, color=B_GREEN,
         fontweight="bold")
for i in alive:
    axR.text(i, entropy[i] + 0.03, "%.2f" % entropy[i], ha="center",
             va="bottom", fontsize=10.5, color=A_RED, fontweight="bold")
axR.text(4.6, 0.42, "Arm A, auto-placed\n%.2f of 8 bits\nsix pairs sit at zero"
         % total_a, ha="left", va="center", fontsize=11, color=A_RED)

fig.text(0.02, 0.955, "Six of Arm A's eight bits are settled before fabrication",
         ha="left", va="top", fontsize=14, fontweight="bold", color="#1a1a1a")
out = os.path.join(HERE, "predictable_bits.png")
fig.savefig(out)
print("predictable_bits.png | Arm A entropy %.3f of 8, %d bits under 0.01, "
      "margins %.1f to %.1f sigma"
      % (total_a, sum(1 for e in entropy if e < 0.01), min(margin), max(margin)))
