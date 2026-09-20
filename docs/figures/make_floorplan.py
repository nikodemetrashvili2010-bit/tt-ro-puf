#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Where each arm sits on the die, drawn from the release build's DEF.

Not a GDS render. It reads dualarm/build_armc's DEF and draws the sixteen
Arm B macros, the 512 Arm A cells, the 512 Arm C cells, the rest of the
logic and the met4 power stripes, so the three arms can be told apart at a
glance. A cell's width is the distance to the next cell origin in its row,
which is exact here because the final DEF is filled edge to edge; the last
cell in a row runs to the row's end.

Run: python3 make_floorplan.py  (writes floorplan_3arm.png beside itself)
"""

import os
import re
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", ".."))
DEF = os.path.join(
    PROJ, "dualarm", "build_armc", "tt_um_nikodemetrashvili20_ro_puf.def"
)
OUT = os.path.join(HERE, "floorplan_3arm.png")
ROW_H = 2.72
A_RED, B_GREEN, C_PURPLE, GREY = "#c0504d", "#3a8a5f", "#7b5ea7", "#9a9a9a"


def read_def(path):
    txt = open(path).read()
    die = [
        int(v) / 1000
        for v in re.search(
            r"DIEAREA \( (\d+) (\d+) \) \( (\d+) (\d+) \)", txt
        ).groups()
    ]
    rows = [
        (int(x) / 1000, int(y) / 1000, int(n) * int(s) / 1000)
        for x, y, n, s in re.findall(
            r"^ROW \S+ \S+ (\d+) (\d+) \S+ DO (\d+) BY 1 STEP (\d+) 0",
            txt,
            re.M,
        )
    ]
    comps = re.search(
        r"^COMPONENTS \d+ ;(.*?)^END COMPONENTS", txt, re.S | re.M
    ).group(1)
    cells = [
        (n, m, int(x) / 1000, int(y) / 1000)
        for n, m, x, y in re.findall(
            r"- (\S+) (\S+) .*?\+ (?:PLACED|FIXED|FIRM) \( (-?\d+) (-?\d+) \)",
            comps,
        )
    ]
    stripes = []
    sn = re.search(
        r"^SPECIALNETS \d+ ;(.*?)^END SPECIALNETS", txt, re.S | re.M
    ).group(1)
    for net, body in re.findall(
        r"- (VPWR|VGND) (.*?)(?=^\s+- |\Z)", sn, re.S | re.M
    ):
        for x in re.findall(
            r"met4 2400 \+ SHAPE STRIPE \( (\d+) \d+ \)", body
        ):
            stripes.append((int(x) / 1000, net))
    return die, rows, cells, stripes


def widths(rows, cells):
    """Width of every row cell from the next origin in the same row."""
    ends = {}
    for x, y, w in rows:
        ends.setdefault(round(y, 3), []).append((x, x + w))
    byrow = {}
    for c in cells:
        if c[1].startswith("sky130_fd_sc_hd__"):
            byrow.setdefault(round(c[3], 3), []).append(c)
    out = {}
    for y, cs in byrow.items():
        cs.sort(key=lambda c: c[2])
        for i, c in enumerate(cs):
            if i + 1 < len(cs):
                nxt = cs[i + 1][2]
            else:
                nxt = max(e for s, e in ends[y] if s <= c[2])
            out[c[0]] = nxt - c[2]
    return out


def main(argv):
    die, rows, cells, stripes = read_def(DEF)
    w = widths(rows, cells)
    fig, ax = plt.subplots(figsize=(10.5, 7.6))
    ax.add_patch(
        Rectangle((0, 0), die[2], die[3], fc="#f7f7f5", ec="#444444", lw=1.2)
    )
    for x, net in stripes:
        ax.add_patch(
            Rectangle(
                (x - 1.2, 2.48),
                2.4,
                220.8,
                fc="#d9c7a0" if net == "VPWR" else "#b9c7d9",
                ec="none",
                alpha=0.55,
                zorder=1,
            )
        )
    groups = {"A": [], "C": [], "logic": []}
    for name, master, x, y in cells:
        if master == "ro_macro_hard":
            ax.add_patch(
                Rectangle(
                    (x, y), 60, 40, fc="#cfe6d8", ec=B_GREEN, lw=1.4, zorder=3
                )
            )
            continue
        if any(k in master for k in ("fill", "decap", "tapvpwrvgnd")):
            continue
        box = Rectangle((x, y), w.get(name, 0.46), ROW_H)
        if ".g_ro_bank[" in name.replace("\\", ""):
            groups["A"].append(box)
        elif ".g_armc[" in name.replace("\\", ""):
            groups["C"].append(box)
        else:
            groups["logic"].append(box)
    for key, colour in (("logic", GREY), ("A", A_RED), ("C", C_PURPLE)):
        ax.add_collection(
            PatchCollection(groups[key], fc=colour, ec="none", zorder=4)
        )
    counts = {k: len(v) for k, v in groups.items()}
    ax.text(
        90,
        -9,
        "Arm B: 16 hardened macros",
        color=B_GREEN,
        ha="center",
        fontsize=10.5,
        fontweight="bold",
    )
    ax.text(
        240,
        -9,
        "Arm A: %d cells" % counts["A"],
        color=A_RED,
        ha="center",
        fontsize=10.5,
        fontweight="bold",
    )
    ax.text(
        305,
        -9,
        "Arm C: %d cells" % counts["C"],
        color=C_PURPLE,
        ha="center",
        fontsize=10.5,
        fontweight="bold",
    )
    ax.text(
        0,
        die[3] + 5,
        "Release build (run 83): where the three arms sit. Grey is the"
        " counter, selector and control logic; the pale\nvertical bands are"
        " the met4 power stripes. Filler, decap and tap cells are not drawn.",
        fontsize=9.5,
        color="#333333",
        va="bottom",
    )
    ax.set_xlim(-4, die[2] + 4)
    ax.set_ylim(-14, die[3] + 16)
    ax.set_aspect("equal")
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT, dpi=170)
    print(
        "floorplan_3arm.png: %d Arm A cells, %d Arm C cells, %d logic cells, "
        "%d macros, %d stripes"
        % (
            counts["A"],
            counts["C"],
            counts["logic"],
            sum(1 for c in cells if c[1] == "ro_macro_hard"),
            len(stripes),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
