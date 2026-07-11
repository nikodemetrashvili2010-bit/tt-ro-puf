#!/usr/bin/env python3
# Figure 3: both arms measured from the one submitted chip layout.
import os, re, csv, random
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ORANGE, GREEN = "#d95f02", "#1b9e77"
ARMB = 569.51

t = open(os.path.join(HERE, "dualarm_par_out.txt")).read()
f = [float(m.group(2))/1e6 for m in sorted(
     re.finditer(r'f(\d+) = ([0-9.e+-]+)', t), key=lambda m: int(m.group(1)))]
mean = sum(f)/len(f); ptp = max(f)-min(f)

random.seed(3)
fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.5, 5.2),
                               gridspec_kw={"width_ratios": [1.45, 1]})
xa = [1 + (random.random()-0.5)*0.30 for _ in f]
xb = [2 + (random.random()-0.5)*0.30 for _ in f]
axL.scatter(xa, f, s=55, c=ORANGE, edgecolor="white", lw=0.6, zorder=3)
axL.scatter(xb, [ARMB]*len(f), s=55, c=GREEN, edgecolor="white", lw=0.6, zorder=3)
axL.hlines(mean, 0.78, 1.22, color=ORANGE, lw=2.2, zorder=4)
axL.hlines(ARMB, 1.78, 2.22, color=GREEN, lw=2.2, zorder=4)
axL.set_ylim(min(f)-11, ARMB+9)
axL.text(1.30, mean, f"{ptp:.0f} MHz p-p\n({100*ptp/mean:.1f}% spread)",
         va="center", ha="left", fontsize=9.5, color=ORANGE, fontweight="bold")
axL.text(2.0, ARMB-7, "0% spread\n(16 copies of one GDS)",
         va="top", ha="center", fontsize=9.5, color=GREEN, fontweight="bold")
axL.set_xticks([1, 2])
axL.set_xticklabels(["Arm A\n(auto-placed)", "Arm B\n(matched macro)"], fontsize=11)
axL.set_ylabel("Oscillation frequency  (MHz)")
axL.set_xlim(0.5, 2.6)
axL.set_title("(a)  Per-oscillator frequency, one chip", loc="left", fontweight="bold")

bars = axR.bar(["Arm A", "Arm B"], [100*ptp/mean, 0.0],
               color=[ORANGE, GREEN], edgecolor="black", linewidth=0.6, width=0.6)
axR.set_ylabel("Layout-induced spread  (% of mean, peak-to-peak)")
axR.set_title("(b)  Fake-entropy magnitude", loc="left", fontweight="bold")
axR.set_ylim(0, 100*ptp/mean*1.25)
for rect, v in zip(bars, [100*ptp/mean, 0.0]):
    axR.text(rect.get_x()+rect.get_width()/2, v+0.12, f"{v:.1f}%",
             ha="center", va="bottom", fontsize=11, fontweight="bold")

fig.suptitle("The submitted two-arm chip: auto-placed arm spreads, matched arm does not",
             fontsize=12.5, fontweight="bold", y=0.99)
fig.text(0.5, 0.01,
         "Both arms from ONE routed 2x2-tile build. Arm A: 16 auto-placed oscillators, extracted parasitics, "
         "r = -0.999 against ring capacitance.\nArm B: 16 bit-identical hardened-macro copies at 569.5 MHz "
         "(macro nom-SPEF). Note Arm A's pattern differs from the single-arm build (5.4% vs 8.8%): "
         "each flow run mints a new fingerprint.",
         ha="center", fontsize=8.0, color="#555555", style="italic")
fig.tight_layout(rect=[0, 0.06, 1, 0.96])
fig.savefig(os.path.join(HERE, "dualarm_gono.png"))
print(f"dualarm_gono.png written  (Arm A mean {mean:.2f}, ptp {ptp:.2f} = {100*ptp/mean:.2f}%)")
