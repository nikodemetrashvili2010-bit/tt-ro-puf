#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Figures for the nominal lumped-C go/no-go, regenerated from the raw data
(par2.txt frequencies + gono_results.csv). Overwrites:
  ro_gono.png         - (a) frequency vs extracted ring capacitance, (b) spatial map
  armB_prediction.png - (a) per-oscillator frequency, (b) spread magnitude
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

def read_named(path, name):
    pattern = re.compile(rf'^{re.escape(name)}\s*=\s*([0-9.eE+\-]+)')
    for line in open(path):
        match = pattern.match(line)
        if match:
            return float(match.group(1))
    raise ValueError(f"{name} not found in {path}")

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
ptp = max(f)-min(f); pct = 100*ptp/mean
mc = sum(cap)/n
b = sum((cap[i]-mc)*(f[i]-mean) for i in range(n))/sum((c-mc)**2 for c in cap)
a = mean - b*mc
def pearson(p, q):
    mp, mq = sum(p)/len(p), sum(q)/len(q)
    return (sum((p[i]-mp)*(q[i]-mq) for i in range(len(p))) /
            math.sqrt(sum((v-mp)**2 for v in p)*sum((v-mq)**2 for v in q)))
r_cap = pearson(f, cap)
def fig_title(fig, s):
    fig.text(0.02, 0.95, s, ha="left", va="top", fontsize=14, fontweight="bold", color="#1a1a1a")

# ---- ro_gono.png : mechanism + spatial map ----
fig, (axL, axR) = plt.subplots(1, 2, figsize=(12.0, 5.1))
fig.subplots_adjust(top=0.85, bottom=0.12, left=0.07, right=0.98, wspace=0.26)
axL.axhline(f_ctrl, color=CTRL, ls=(0, (5, 4)), lw=1.6, label=f"no-parasitic control, {f_ctrl:.0f} MHz")
xf = [min(cap)-0.4, max(cap)+0.4]
axL.plot(xf, [a+b*v for v in xf], ls="--", color=FIT, lw=2.0, label=f"fit  {b:.2f} MHz/fF,  r = {r_cap:.3f}")
axL.scatter(cap, f, s=66, c=POINT, edgecolor="white", linewidth=0.8, zorder=3)
axL.set_xlabel("extracted ring capacitance per oscillator  (fF)")
axL.set_ylabel("oscillation frequency  (MHz)")
axL.set_title("(a)  frequency vs extracted ring capacitance", loc="left", fontsize=11.5, color="#444444", pad=8)
axL.legend(loc="lower left", fontsize=10)
axL.grid(axis="x", visible=False); axL.margins(x=0.05)
sc = axR.scatter(x, y, c=f, cmap="cividis", s=215, edgecolor="white", linewidth=0.9)
for i in ros:
    axR.annotate(str(i), (x[ros.index(i)], y[ros.index(i)]), fontsize=6.5, ha="center", va="center", color="white", fontweight="bold")
axR.set_xlabel("x  (µm)"); axR.set_ylabel("y  (µm)")
axR.set_title("(b)  spatial map of frequency", loc="left", fontsize=11.5, color="#444444", pad=8)
axR.grid(False)
cb = fig.colorbar(sc, ax=axR, pad=0.02); cb.set_label("frequency  (MHz)")
axR.margins(0.08)
fig_title(fig, "Arm A: nominal lumped-C model predicts layout-dependent spread")
fig.savefig(os.path.join(HERE, "ro_gono.png")); plt.close(fig)

# ---- armB_prediction.png : (a) frequencies, (b) spread magnitude ----
random.seed(1)
matched = read_named(os.path.join(HERE, "macro_out.txt"), "f_b") / 1e6
fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.5, 5.0), gridspec_kw={"width_ratios": [1.5, 1]})
fig.subplots_adjust(top=0.85, bottom=0.14, left=0.08, right=0.97, wspace=0.32)
xa = [1 + (random.random()-0.5)*0.30 for _ in f]
axL.scatter(xa, f, s=64, c=A_RED, edgecolor="white", lw=0.7, zorder=3)
axL.hlines(mean, 0.74, 1.26, color=A_RED, lw=2.4, zorder=4)
axL.hlines(matched, 1.60, 2.40, color=B_GREEN, lw=3.0, zorder=4)
axL.set_ylim(min(f)-15, max(f)+16); axL.set_xlim(0.55, 2.5)
axL.text(1.0, max(f)+4, f"{ptp:.0f} MHz peak-to-peak", va="bottom", ha="center", fontsize=10.5, color=A_RED, fontweight="bold")
axL.text(2.0, matched-6, f"{matched:.1f} MHz reference\n(one simulation, shared GDS)", va="top", ha="center", fontsize=10.5, color=B_GREEN, fontweight="bold")
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
fig_title(fig, "Arm A spreads; the matched macro is one line")
fig.savefig(os.path.join(HERE, "armB_prediction.png")); plt.close(fig)
print(f"ro_gono + armB | mean={mean:.2f} ptp={ptp:.2f} ({pct:.2f}%) std={100*std/mean:.2f}% r={r_cap:.4f}")
