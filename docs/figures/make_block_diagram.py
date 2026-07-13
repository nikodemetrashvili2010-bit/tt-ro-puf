#!/usr/bin/env python3
# Draws the chip block diagram (Figure 0 of the paper, also used in README).
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import os

ORANGE, GREEN, BLUE, GREY = "#c0504d", "#3a8a5f", "#35618f", "#666666"
fig, ax = plt.subplots(figsize=(11, 5.6))
ax.set_xlim(0, 110); ax.set_ylim(0, 62); ax.axis("off")

def box(x, y, w, h, color, title, sub="", title_size=11):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6",
                 fc="white", ec=color, lw=2.2))
    ax.text(x+w/2, y+h-3, title, ha="center", va="center",
            fontsize=title_size, fontweight="bold", color=color)
    if sub:
        ax.text(x+w/2, y+h/2-2.2, sub, ha="center", va="center",
                fontsize=8.6, color="#333333")

def arrow(x1, y1, x2, y2, label="", color=GREY, off=1.8):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                 mutation_scale=16, lw=1.8, color=color))
    if label:
        ax.text((x1+x2)/2, (y1+y2)/2+off, label, ha="center",
                fontsize=8.6, color=color, fontweight="bold")

# Arm A
box(3, 32, 30, 17, ORANGE, "Arm A: 16 oscillators",
    "auto-placed by the flow\nevery copy gets different\nrouting (different metal)")
# Arm B
box(3, 8, 30, 17, GREEN, "Arm B: 16 oscillators",
    "16 copies of ONE hardened\nmacro, identical layout\nby construction")
# mux + core
box(44, 20, 28, 17, BLUE, "measurement core",
    "select 1 of 32 oscillators,\ncount its edges in a fixed\nwindow of 1000 clk cycles")
# output
box(83, 20, 24, 17, GREY, "TinyTapeout pins",
    "ui_in: start, arm,\nindex, byte select\nuo_out: count byte\nuio[0]: done")

arrow(33.6, 40, 44, 32, "16x en / out", ORANGE, off=2.4)
arrow(33.6, 16, 44, 24, "16x en / out", GREEN, off=-3.0)
arrow(72.6, 28.5, 82.4, 28.5, "16-bit count", BLUE, off=2.2)

ax.text(55, 57.5, "One chip, both layouts. Same circuit in both arms, so any "
        "frequency difference between the arms comes from layout.",
        ha="center", fontsize=10.5, style="italic", color="#333333")
fig.tight_layout()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chip_block.png")
fig.savefig(out, dpi=170)
print("written:", out)
