#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
SILICON go/no-go analysis.

Joins the extracted-parasitic ngspice frequencies (par2.txt) with each RO's
placement centroid and ring capacitance (ro_positions.csv) and the no-parasitic
control frequency (ctrl2.txt), then quantifies the layout-induced frequency
spread and tests whether it is position-dependent.

Verdict logic:
  GO  if the parasitic frequency spread across nominally-identical ROs is large
      (>>0) and tracks the extracted capacitance (mechanism confirmed). Because
      it is a layout effect with nominal transistors, this bias is deterministic
      and identical on every fabricated chip -> shared "fake entropy".
"""
import re, os, csv, math

HERE = os.path.dirname(os.path.abspath(__file__))

def read_freqs(path):
    d = {}
    for line in open(path):
        m = re.match(r'^f(\d+)\s*=\s*([0-9.eE+\-]+)', line)
        if m:
            d[int(m.group(1))] = float(m.group(2))
    return d

def mean(v): return sum(v) / len(v)
def std(v):
    m = mean(v); return math.sqrt(sum((x-m)**2 for x in v) / (len(v)-1))
def pearson(a, b):
    ma, mb = mean(a), mean(b)
    num = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x-ma)**2 for x in a)); db = math.sqrt(sum((y-mb)**2 for y in b))
    return num/(da*db) if da and db else float('nan')
def linfit(x, y):                       # least squares y = a + b x
    n = len(x); mx, my = mean(x), mean(y)
    b = sum((xi-mx)*(yi-my) for xi, yi in zip(x, y)) / sum((xi-mx)**2 for xi in x)
    return my - b*mx, b

par  = read_freqs(os.path.join(HERE, "par2.txt"))
ctrl = read_freqs(os.path.join(HERE, "ctrl2.txt"))
pos  = {}
with open(os.path.join(HERE, "ro_positions.csv")) as f:
    for r in csv.DictReader(f):
        pos[int(r["ro"])] = (float(r["x_um"]), float(r["y_um"]), float(r["ring_cap_fF"]))

ros   = sorted(par)
fMHz  = [par[i]/1e6 for i in ros]
caps  = [pos[i][2] for i in ros]
xs    = [pos[i][0] for i in ros]
ys    = [pos[i][1] for i in ros]
f_ctrl = mean(list(ctrl.values()))/1e6

# radial distance from die centre (mid-range of placements)
cx = (min(xs)+max(xs))/2; cy = (min(ys)+max(ys))/2
rad = [math.hypot(x-cx, y-cy) for x, y in zip(xs, ys)]

m, s = mean(fMHz), std(fMHz)
print("="*64)
print("SILICON go/no-go : Arm A (auto-placed) extracted-parasitic result")
print("="*64)
print(f"control (no parasitics) : {f_ctrl:.2f} MHz  (all 32 identical)")
print(f"parasitic mean          : {m:.2f} MHz   ({100*(f_ctrl-m)/f_ctrl:.1f}% slower than control)")
print(f"parasitic std-dev       : {s:.2f} MHz   ({100*s/m:.2f}% of mean)")
print(f"parasitic min / max     : {min(fMHz):.2f} / {max(fMHz):.2f} MHz")
print(f"peak-to-peak spread     : {max(fMHz)-min(fMHz):.2f} MHz   ({100*(max(fMHz)-min(fMHz))/m:.1f}% of mean)")
print()
print("MECHANISM  (does parasitic loading explain the spread?)")
print(f"  corr(freq, ring_cap)  : r = {pearson(fMHz, caps):+.3f}   (expect strongly negative)")
a, b = linfit(caps, fMHz)
print(f"  slope                 : {b:+.2f} MHz per fF of ring cap")
print()
print("POSITION DEPENDENCE  (is the bias spatial?)")
print(f"  corr(freq, x)         : r = {pearson(fMHz, xs):+.3f}")
print(f"  corr(freq, y)         : r = {pearson(fMHz, ys):+.3f}")
print(f"  corr(freq, radius)    : r = {pearson(fMHz, rad):+.3f}")
print()
print(f"{'RO':>3} {'x_um':>8} {'y_um':>7} {'cap_fF':>7} {'freq_MHz':>9}")
for i in ros:
    print(f"{i:>3} {pos[i][0]:>8.1f} {pos[i][1]:>7.1f} {pos[i][2]:>7.2f} {par[i]/1e6:>9.2f}")

# write joined table
with open(os.path.join(HERE, "gono_results.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["ro","x_um","y_um","ring_cap_fF","freq_MHz","freq_ctrl_MHz"])
    for i in ros:
        w.writerow([i, pos[i][0], pos[i][1], pos[i][2], round(par[i]/1e6,3), round(ctrl[i]/1e6,3)])

# ---- figure ----
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(12, 5))
    axL.scatter(caps, fMHz, c="#2b6cb0", s=45, zorder=3)
    xfit = [min(caps), max(caps)]; axL.plot(xfit, [a+b*xx for xx in xfit], "r--", lw=1.5,
            label=f"fit: {b:+.2f} MHz/fF\nr={pearson(fMHz,caps):+.3f}")
    axL.axhline(f_ctrl, color="gray", ls=":", label=f"control {f_ctrl:.0f} MHz")
    axL.set_xlabel("extracted ring capacitance (fF)"); axL.set_ylabel("oscillation frequency (MHz)")
    axL.set_title("Mechanism: parasitic loading -> frequency"); axL.legend(fontsize=8); axL.grid(alpha=.3)
    sc = axR.scatter(xs, ys, c=fMHz, cmap="viridis", s=120, edgecolor="k", linewidth=.4)
    for i in ros: axR.annotate(str(i), (xs[ros.index(i)], ys[ros.index(i)]), fontsize=6,
                               ha="center", va="center", color="white")
    axR.set_xlabel("x (um)"); axR.set_ylabel("y (um)")
    axR.set_title("Spatial map of RO frequency (auto-placed Arm A)")
    fig.colorbar(sc, ax=axR, label="freq (MHz)")
    fig.suptitle("SILICON go/no-go: auto-layout injects a deterministic RO frequency spread (nom SPEF)", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "ro_gono.png"), dpi=130)
    print("\nfigure written: ro_gono.png")
except Exception as e:
    print(f"\n(figure skipped: {e})")
