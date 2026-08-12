#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
# Figure for Section 7.2: what compensating the layout term does, and what it
# does not do. Every number is imported from compensated_bits.py rather than
# copied, so the figure cannot drift away from the reported totals.
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compensated_bits as cb  # noqa: E402
import compensation as cp  # noqa: E402

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
A_RED, B_GREEN, BLUE, GREY = "#c0504d", "#3a8a5f", "#35618f", "#8c8c8c"

feats = cp.spef_features(cp.CUR_SPEF, cb.NRO)
C = [f[0] for f in feats]
R = [f[1] for f in feats]
_, _, f_rc = cp.read_rc()
y = cp.centred(f_rc)
resid = cb.loo_residuals([C, R], y)

un = cb.score(y, cb.SIGMA_RING)
co = cb.score(resid, cb.SIGMA_RING)
labels = ["%d/%d" % p for p in cb.PAIRS]
e_un, a_un, _ = cb.totals(un)
e_co, a_co, _ = cb.totals(co)

fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.5, 5.0))
fig.subplots_adjust(top=0.80, bottom=0.15, left=0.075, right=0.975, wspace=0.26)
xs = list(range(len(labels)))
w = 0.38

# ---- (a) entropy: compensation gives a lot of it back ---------------------
axL.bar([x - w / 2 for x in xs], [r[2] for r in un], width=w, color=A_RED,
        edgecolor="white", linewidth=0.8, label="as built")
axL.bar([x + w / 2 for x in xs], [r[2] for r in co], width=w, color=BLUE,
        edgecolor="white", linewidth=0.8, label="layout term compensated")
axL.axhline(1.0, color=B_GREEN, lw=2.2, zorder=4)
axL.set_xticks(xs)
axL.set_xticklabels(labels, fontsize=10)
axL.set_xlim(-0.7, len(labels) - 0.3)
axL.set_ylim(0, 1.22)
axL.set_xlabel("oscillator pair")
axL.set_ylabel("across-die entropy of the bit  (bits)")
axL.set_title("(a)  entropy the die still decides", loc="left",
              fontsize=11.5, color="#444444", pad=8)
axL.grid(axis="x", visible=False)
axL.legend(loc="upper left", fontsize=10, bbox_to_anchor=(0.0, 0.99))
axL.text(len(labels) - 0.45, 1.03, "a full bit each", ha="right", va="bottom",
         fontsize=10, color=B_GREEN)
axL.text(2.85, 0.70, "%.2f of 8  ->  %.2f of 8\nbits left fixed: %d  ->  %d"
         % (e_un, e_co,
            sum(1 for r in un if r[2] < 0.01), sum(1 for r in co if r[2] < 0.01)),
         ha="left", va="center", fontsize=10.5, color=BLUE)

# ---- (b) accuracy: the reader subtracts the same numbers ------------------
axR.bar([x - w / 2 for x in xs], [r[3] * 100 for r in un], width=w, color=A_RED,
        edgecolor="white", linewidth=0.8, label="as built")
axR.bar([x + w / 2 for x in xs], [r[3] * 100 for r in co], width=w, color=BLUE,
        edgecolor="white", linewidth=0.8, label="layout term compensated")
axR.axhline(50.0, color=GREY, lw=2.2, ls="--", zorder=4)
axR.set_xticks(xs)
axR.set_xticklabels(labels, fontsize=10)
axR.set_xlim(-0.7, len(labels) - 0.3)
axR.set_ylim(40, 122)
axR.set_yticks([50, 60, 70, 80, 90, 100])
axR.set_xlabel("oscillator pair")
axR.set_ylabel("bit called correctly from public files  (%)")
axR.set_title("(b)  what the design database still predicts", loc="left",
              fontsize=11.5, color="#444444", pad=8)
axR.grid(axis="x", visible=False)
axR.text(len(labels) - 0.45, 51.5, "guessing", ha="right", va="bottom",
         fontsize=10, color=GREY)
axR.text(-0.5, 114.0, "%.2f of 8  ->  %.2f of 8      guessing would get %.2f"
         % (a_un, a_co, len(cb.PAIRS) / 2), ha="left", va="center",
         fontsize=10.5, color=BLUE)

fig.text(0.02, 0.955,
         "Compensation returns the entropy and none of the secrecy",
         ha="left", va="top", fontsize=14, fontweight="bold", color="#1a1a1a")
fig.text(0.02, 0.895,
         "The correction is computed from the published extraction, so a reader "
         "applies it too.",
         ha="left", va="top", fontsize=11, color="#555555")

out = os.path.join(HERE, "compensated_bits.png")
fig.savefig(out)
print("compensated_bits.png | entropy %.3f -> %.3f of 8, guessed %.3f -> %.3f of 8"
      % (e_un, e_co, a_un, a_co))
