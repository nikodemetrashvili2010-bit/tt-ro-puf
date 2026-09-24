#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The release build's die, drawn from its GDS, with the three arms marked.

The layout is dualarm/build_armc's GDS, flattened and drawn layer by layer
(diffusion, poly, local interconnect, metal 1 to 4) the way a layout viewer
shows it. The outlines on top come from the same build's DEF: the sixteen
Arm B macros, the box that holds Arm A's 512 cells, and the blocks Arm C's
sixteen rings make where they sit next to each other.

Until 24 September this script drew every placed cell as its own rectangle
instead: 712 logic cells and Arm A's 512, each a few pixels across at the
width the README shows, scattered between the filler it left out, and the
met4 stripes, which only showed as stubs between the macro rows. It read as
a broken image. It draws the layout now, and the cell rectangles are only
used to find the outlines.

A cell's width is the distance to the next cell origin in its row, which is
exact here because the final DEF is filled edge to edge; the last cell in a
row runs to the row's end.

Run: python3 make_floorplan.py  (writes floorplan_3arm.png beside itself)
Needs gdstk as well as matplotlib, see requirements-analysis.txt.
"""

import os
import re
import sys

import matplotlib

matplotlib.use("Agg")
import gdstk  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", ".."))
BUILD = os.path.join(PROJ, "dualarm", "build_armc")
GDS = os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.gds")
DEF = os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.def")
OUT = os.path.join(HERE, "floorplan_3arm.png")
ROW_H = 2.72
MACRO_W, MACRO_H = 60.0, 40.0
A_RED, B_GREEN, C_PURPLE = "#ff5a52", "#4fd08a", "#c6a4ff"

# sky130 layer/datatype, colour, alpha, bottom to top
LAYERS = [
    ((64, 20), "nwell", "#d8d2c0", 0.30),
    ((65, 20), "diff", "#5aa05a", 0.55),
    ((66, 20), "poly", "#c84a4a", 0.55),
    ((67, 20), "li1", "#6f8fd8", 0.45),
    ((68, 20), "met1", "#8a6fc8", 0.45),
    ((69, 20), "met2", "#e0a040", 0.60),
    ((70, 20), "met3", "#40b8c8", 0.60),
    ((71, 20), "met4", "#b0b0b0", 0.40),
]


def read_gds(path):
    top = gdstk.read_gds(path).top_level()
    if len(top) != 1:
        raise SystemExit("expected one top cell in %s, found %d"
                         % (path, len(top)))
    shapes = {}
    for p in top[0].get_polygons(depth=None):
        shapes.setdefault((p.layer, p.datatype), []).append(p.points)
    (x0, y0), (x1, y1) = top[0].bounding_box()
    return shapes, (x0, y0, x1, y1)


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
        (n.replace("\\", ""), m, int(x) / 1000, int(y) / 1000)
        for n, m, x, y in re.findall(
            r"- (\S+) (\S+) .*?\+ (?:PLACED|FIXED|FIRM) \( (-?\d+) (-?\d+) \)",
            comps,
        )
    ]
    return die, rows, cells


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


def bbox(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def merge(boxes, gap=0.5):
    """Join boxes that overlap or sit within `gap` of each other."""
    out = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                a, b = out[i], out[j]
                if (a[0] <= b[2] + gap and b[0] <= a[2] + gap
                        and a[1] <= b[3] + gap and b[1] <= a[3] + gap):
                    out[i] = list(bbox([a, b]))
                    del out[j]
                    changed = True
                    break
            if changed:
                break
    return [tuple(b) for b in out]


def arms(die, rows, cells):
    w = widths(rows, cells)
    macros, arm_a, rings = [], [], {}
    for name, master, x, y in cells:
        if master == "ro_macro_hard":
            macros.append((x, y, x + MACRO_W, y + MACRO_H))
            continue
        box = (x, y, x + w.get(name, 0.46), y + ROW_H)
        if ".g_ro_bank[" in name:
            arm_a.append(box)
        elif ".g_armc[" in name:
            ring = re.search(r"\.g_armc\[(\d+)\]", name).group(1)
            rings.setdefault(int(ring), []).append(box)
    blocks = merge([bbox(v) for v in rings.values()])
    return macros, arm_a, rings, blocks


def outline(ax, box, colour, lw=2.0):
    """A coloured box with a dark edge under it, so it reads on the layout."""
    x0, y0, x1, y1 = box
    r = Rectangle((x0, y0), x1 - x0, y1 - y0, fc="none", ec=colour, lw=lw,
                  zorder=6)
    r.set_path_effects([patheffects.withStroke(linewidth=lw + 2.2,
                                               foreground="#0a0a0a")])
    ax.add_patch(r)


def main(argv):
    shapes, gbox = read_gds(GDS)
    die, rows, cells = read_def(DEF)
    if any(abs(a - b) > 1e-3 for a, b in zip(gbox, die)):
        raise SystemExit("GDS box %s and DEF die %s disagree" % (gbox, die))
    macros, arm_a, rings, blocks = arms(die, rows, cells)

    fig, ax = plt.subplots(figsize=(10.5, 7.6))
    ax.add_patch(Rectangle((0, 0), die[2], die[3], fc="#161616",
                           ec="#444444", lw=1.2, zorder=0))
    drawn = 0
    for key, _, colour, alpha in LAYERS:
        polys = shapes.get(key, [])
        drawn += len(polys)
        ax.add_collection(PolyCollection(
            polys, facecolors=colour, edgecolors="none", alpha=alpha,
            antialiased=False, zorder=2))
    for m in macros:
        outline(ax, m, B_GREEN, lw=1.4)
    outline(ax, bbox(arm_a), A_RED, lw=2.4)
    for b in blocks:
        outline(ax, b, C_PURPLE, lw=2.4)

    ax.text(90, -9, "Arm B: %d hardened macros" % len(macros),
            color="#2f7f52", ha="center", fontsize=10.5, fontweight="bold")
    ax.text(236, -9, "Arm A: %d cells" % len(arm_a),
            color="#c0504d", ha="center", fontsize=10.5, fontweight="bold")
    ax.text(310, -9, "Arm C: %d rings" % len(rings),
            color="#7b5ea7", ha="center", fontsize=10.5, fontweight="bold")
    ax.text(
        0, die[3] + 5,
        "Release build (run 83), drawn from its GDS: diffusion, poly, local"
        " interconnect and metal 1 to 4. The\ncoloured outlines come from the"
        " same build's DEF and mark where each arm sits.",
        fontsize=9.5, color="#333333", va="bottom")
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
        "floorplan_3arm.png: %d shapes on %d layers, %d macros, %d Arm A "
        "cells, %d Arm C cells in %d rings, %d Arm C blocks"
        % (drawn, len(LAYERS), len(macros), len(arm_a),
           sum(len(v) for v in rings.values()), len(rings), len(blocks))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
