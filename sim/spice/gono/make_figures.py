#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Publication-quality figures for the SILICON go/no-go, regenerated from the raw
data (par2.txt frequencies + gono_results.csv). Overwrites:
  ro_gono.png        - (a) mechanism (freq vs extracted cap) + (b) spatial map
  armB_prediction.png - Arm A measured spread vs Arm B (matched macro) zero spread
"""
import re, os, csv, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager  # noqa

plt.rcParams.update({
    "figure.dpi": 200, "savefig.dpi": 200, "figure.facecolor": "white",
    "savefig.facecolor": "white", "font.size": 11, "axes.titlesize": 12,
    "axes.labelsize": 11, "axes.edgecolor": "#444444", "axes.linewidth": 0.8,
    "xtick.color": "#333333", "ytick.color": "#333333", "text.color": "#222222",
    "axes.labelcolor": "#222222", "axes.grid": True, "grid.color": "#cccccc",
    "grid.linewidth": 0.6, "grid.alpha": 0.6, "legend.frameon": True,
    "legend.framealpha": 0.95, "legend.edgecolor": "#cccccc",
})
BLUE, RED, GRAY = "#2b6cb0", "#c0392b", "#7f8c8d"
ORANGE, GREEN = "#d96704", "#1e8449"

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

# ---------------------------------------------------------------- Figure 1
fig, (axL, axR) = plt.subplots(1, 2, figsize=(12.5, 5.2))

axL.axhline(f_ctrl, color=GRAY, ls=(0, (4, 3)), lw=1.6,
            label=f"no-parasitic control: {f_ctrl:.0f} MHz", zorder=1)
xf = [min(cap)-0.4, max(cap)+0.4]
axL.plot(xf, [a + b*v for v in xf], "--", color=RED, lw=2.0, zorder=2,
         label=f"linear fit:  {b:.2f} MHz/fF\nPearson r = {r_cap:.3f}")
axL.scatter(cap, f, s=60, c=BLUE, edgecolor="white", linewidth=0.7, zorder=3)
axL.set_xlabel("Extracted ring capacitance per oscillator  (fF)")
axL.set_ylabel("Oscillation frequency  (MHz)")
axL.set_title("(a)  Frequency versus extracted ring capacitance",
              loc="left", fontweight="bold")
axL.legend(loc="upper right", fontsize=9)
axL.margins(x=0.05)

sc = axR.scatter(x, y, c=f, cmap="viridis", s=200, edgecolor="black", linewidth=0.5)
for i in ros:
    axR.annotate(str(i), (x[ros.index(i)], y[ros.index(i)]), fontsize=6.5,
                 ha="center", va="center", color="white", fontweight="bold")
axR.set_xlabel("x  (µm)"); axR.set_ylabel("y  (µm)")
axR.set_title("(b)  Spatial map of oscillator frequency",
              loc="left", fontweight="bold")
cb = fig.colorbar(sc, ax=axR, pad=0.02); cb.set_label("Frequency  (MHz)")
axR.margins(0.08)

fig.suptitle("Arm A: the routing sets each oscillator's frequency",
             fontsize=13, fontweight="bold", y=0.99)
fig.text(0.5, 0.005,
         f"sky130 TinyTapeout, OpenROAD-extracted parasitics at the nominal corner. "
         f"Spread {ptp:.0f} MHz peak-to-peak ({100*ptp/mean:.1f}% of mean), "
         f"std {100*std/mean:.1f}%. Same logic, different routing.",
         ha="center", fontsize=8.5, color="#555555", style="italic")
fig.tight_layout(rect=[0, 0.03, 1, 0.96])
fig.savefig(os.path.join(HERE, "ro_gono.png"))
plt.close(fig)

# ---------------------------------------------------------------- Figure 2
import random; random.seed(1)
matched = 569.51                     # MEASURED: macro nom-SPEF deck (verify_macro.py)
fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.5, 5.2),
                               gridspec_kw={"width_ratios": [1.45, 1]})

xa = [1 + (random.random()-0.5)*0.30 for _ in f]
xb = [2 + (random.random()-0.5)*0.30 for _ in f]
axL.scatter(xa, f, s=55, c=ORANGE, edgecolor="white", lw=0.6, zorder=3)
axL.scatter(xb, [matched]*n, s=55, c=GREEN, edgecolor="white", lw=0.6, zorder=3)
axL.hlines(mean, 0.78, 1.22, color=ORANGE, lw=2.2, zorder=4)
axL.hlines(matched, 1.78, 2.22, color=GREEN, lw=2.2, zorder=4)
axL.set_ylim(min(f) - 13, max(f) + 11)
axL.text(1.30, mean, f"{ptp:.0f} MHz p-p\n({100*ptp/mean:.1f}% spread)",
         va="center", ha="left", fontsize=9.5, color=ORANGE, fontweight="bold")
axL.text(2.0, matched - 9, "0% spread\n(identical macro copies)",
         va="top", ha="center", fontsize=9.5, color=GREEN, fontweight="bold")
axL.set_xticks([1, 2])
axL.set_xticklabels(["Arm A\n(auto-placed)", "Arm B\n(matched macro)"], fontsize=11)
axL.set_ylabel("Oscillation frequency  (MHz)")
axL.set_xlim(0.5, 2.6)
axL.set_title("(a)  Per-oscillator frequency", loc="left", fontweight="bold")
axL.grid(axis="x", alpha=0)

bars = axR.bar(["Arm A", "Arm B"], [100*ptp/mean, 0.0],
               color=[ORANGE, GREEN], edgecolor="black", linewidth=0.6, width=0.6)
axR.set_ylabel("Layout-induced spread  (% of mean, peak-to-peak)")
axR.set_title("(b)  Fake-entropy magnitude", loc="left", fontweight="bold")
axR.set_ylim(0, 100*ptp/mean*1.25)
for rect, v in zip(bars, [100*ptp/mean, 0.0]):
    axR.text(rect.get_x()+rect.get_width()/2, v+0.2, f"{v:.1f}%",
             ha="center", va="bottom", fontsize=11, fontweight="bold")
axR.grid(axis="x", alpha=0)

fig.suptitle("Matched macro removes the Arm A spread",
             fontsize=13, fontweight="bold", y=0.99)
fig.text(0.5, 0.01,
         "Arm A is measured from the extracted parasitics. Arm B is 16 bit-identical "
         "hardened-macro copies, so their internal parasitics are identical and the "
         "layout spread is zero by construction\n(array DRC, LVS, antenna and power all clean). "
         "The Arm B level is the macro's own routed nom-SPEF frequency, 569.5 MHz, "
         "0.3% from the Arm A mean. Only mismatch remains.",
         ha="center", fontsize=8.0, color="#555555", style="italic")
fig.tight_layout(rect=[0, 0.06, 1, 0.96])
fig.savefig(os.path.join(HERE, "armB_prediction.png"))
plt.close(fig)

print("regenerated ro_gono.png and armB_prediction.png")
print(f"  mean={mean:.2f} MHz  ptp={ptp:.2f} MHz ({100*ptp/mean:.2f}%)  "
      f"std={std:.2f} ({100*std/mean:.2f}%)  r={r_cap:.4f}  slope={b:.2f}")
