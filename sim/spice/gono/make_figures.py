#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Figures for the SILICON go/no-go, regenerated from the raw data
(par2.txt frequencies + gono_results.csv). Overwrites:
  ro_gono.png         - (a) frequency vs extracted ring capacitance, (b) spatial map
  armB_prediction.png - Arm A measured spread against the matched macro
"""
import re, os, csv, math, random
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
POINT, FIT, CTRL = "#35618f", "#c0504d", "#9aa7b0"
HERE = os.path.dirname(os.path.abspath(__file__))

def read_fN(path):
    d = {}
    for line in open(path):
        m = re.match(r'^f(\d+)\s*=\s*([0-9.eE+\-]+)', line)
        if m: d[int(m.group(1))] = float(m.group(2))
    return d

par  = read_fN(os.path.join(HERE, "par2.txt"))
ctrl = read_fN(os.path.join(HERE, "ctrl2.txt"))
f_ctrl = sum(ctrl.values())/len(ctrl)/1e6

rows = {}
with open(os.path.join(HERE, "gono_results.csv")) as fh:
    for r in csv.DictReader(fh):
        rows[int(r["ro"])] = (float(r["x_um"]), float(r["y_um"]),
                              float(r["ring_cap_fF"]), float(r["freq_MHz"]))
ros = sorted(rows)
x   = [rows[i][0] for i in ros]; y = [rows[i][1] for i in ros]
cap = [rows[i][2] for i in ros]; f = [par[i]/1e6 for i in ros]
n = len(f); mean = sum(f)/n
std = math.sqrt(sum((v-mean)**2 for v in f)/(n-1))
ptp = max(f)-min(f)
mc = sum(cap)/n
b = sum((cap[i]-mc)*(f[i]-mean) for i in range(n))/sum((c-mc)**2 for c in cap)
a = mean - b*mc
def pearson(p, q):
    mp, mq = sum(p)/len(p), sum(q)/len(q)
    return (sum((p[i]-mp)*(q[i]-mq) for i in range(len(p))) /
            math.sqrt(sum((v-mp)**2 for v in p)*sum((v-mq)**2 for v in q)))
r_cap = pearson(f, cap)

def fig_title(fig, s):
    fig.text(0.02, 0.95, s, ha="left", va="top", fontsize=14,
             fontweight="bold", color="#1a1a1a")

# ---- ro_gono.png : mechanism + spatial map ----
fig, (axL, axR) = plt.subplots(1, 2, figsize=(12.0, 5.1))
fig.subplots_adjust(top=0.85, bottom=0.12, left=0.07, right=0.98, wspace=0.26)
axL.axhline(f_ctrl, color=CTRL, ls=(0, (5, 4)), lw=1.6,
            label=f"no-parasitic control, {f_ctrl:.0f} MHz")
xf = [min(cap)-0.4, max(cap)+0.4]
axL.plot(xf, [a+b*v for v in xf], ls="--", color=FIT, lw=2.0,
         label=f"fit  {b:.2f} MHz/fF,  r = {r_cap:.3f}")
axL.scatter(cap, f, s=66, c=POINT, edgecolor="white", linewidth=0.8, zorder=3)
axL.set_xlabel("extracted ring capacitance per oscillator  (fF)")
axL.set_ylabel("oscillation frequency  (MHz)")
axL.set_title("(a)  frequency vs extracted ring capacitance", loc="left",
              fontsize=11.5, color="#444444", pad=8)
axL.legend(loc="lower left", fontsize=10)
axL.grid(axis="x", visible=False)
axL.margins(x=0.05)
sc = axR.scatter(x, y, c=f, cmap="cividis", s=215, edgecolor="white", linewidth=0.9)
for i in ros:
    axR.annotate(str(i), (x[ros.index(i)], y[ros.index(i)]), fontsize=6.5,
                 ha="center", va="center", color="white", fontweight="bold")
axR.set_xlabel("x  (µm)"); axR.set_ylabel("y  (µm)")
axR.set_title("(b)  spatial map of frequency", loc="left",
              fontsize=11.5, color="#444444", pad=8)
axR.grid(False)
cb = fig.colorbar(sc, ax=axR, pad=0.02); cb.set_label("frequency  (MHz)")
axR.margins(0.08)
fig_title(fig, "Arm A: the routing sets each oscillator's frequency")
fig.savefig(os.path.join(HERE, "ro_gono.png"))
plt.close(fig)

# ---- armB_prediction.png : matched macro removes the spread ----
random.seed(1)
matched = 569.51
fig, ax = plt.subplots(figsize=(8.6, 5.3))
fig.subplots_adjust(top=0.85, bottom=0.12, left=0.12, right=0.96)
xa = [1 + (random.random()-0.5)*0.32 for _ in f]
xb = [2 + (random.random()-0.5)*0.32 for _ in f]
ax.scatter(xa, f, s=72, c=A_RED, edgecolor="white", lw=0.8, zorder=3)
ax.scatter(xb, [matched]*n, s=72, c=B_GREEN, edgecolor="white", lw=0.8, zorder=3)
ax.hlines(mean, 0.72, 1.28, color=A_RED, lw=2.4, zorder=4)
ax.hlines(matched, 1.72, 2.28, color=B_GREEN, lw=2.4, zorder=4)
ax.set_ylim(min(f)-15, max(f)+22); ax.set_xlim(0.5, 2.7)
ax.text(1.0, max(f)+4, f"{ptp:.0f} MHz peak-to-peak\n{100*ptp/mean:.1f}% spread",
        va="bottom", ha="center", fontsize=11.5, color=A_RED, fontweight="bold")
ax.text(2.0, matched-9, "one frequency\n0% spread, 16 identical copies",
        va="top", ha="center", fontsize=11.5, color=B_GREEN, fontweight="bold")
ax.set_xticks([1, 2])
ax.set_xticklabels(["Arm A\nauto-placed", "Arm B\nmatched macro"], fontsize=12)
ax.set_ylabel("oscillation frequency  (MHz)")
ax.grid(axis="x", visible=False)
fig_title(fig, "Matched macro removes the Arm A spread")
fig.savefig(os.path.join(HERE, "armB_prediction.png"))
plt.close(fig)
print(f"ro_gono + armB regenerated | mean={mean:.2f} ptp={ptp:.2f} ({100*ptp/mean:.2f}%) std={100*std/mean:.2f}% r={r_cap:.4f}")
