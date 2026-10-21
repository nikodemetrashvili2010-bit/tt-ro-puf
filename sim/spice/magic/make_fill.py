#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Fill a layout the way open_pdks' generate_fill.py does, one tile.

Same magic commands as sky130/custom/scripts/generate_fill.py at open_pdks
8afc8346 (the PDK the shuttle pins): sky130A-GDS.tech, cif ostyle
wafflefill(tiled), the tile flattened 1.6 um wider than the fill box and
the box drawn on COMMENT. Two differences, both on purpose:

- one tile, the design's box grown by MARGIN on every side, so the tile
  edge (where the style keeps 1.5 um clear) is outside the design. In the
  chip the tile is 700 um and its edges fall wherever they fall
- the box can be moved down and left by (dx, dy). The fill grid is
  anchored to the box corner, and where it lands on the chip is not known,
  so the phase is sampled instead of guessed

Writes OUT, holding only the fill layers (datatype 99 in this tech).
Usage: python3 make_fill.py DESIGN.gds TOPCELL OUT.gds DX_UM DY_UM TECH
"""
import os
import subprocess
import sys

MARGIN_UM = 5.0

design, top, out, dx, dy, tech = sys.argv[1:7]
dx, dy = float(dx), float(dy)
work = os.path.dirname(os.path.abspath(out))
tcl = os.path.join(work, os.path.basename(out) + ".tcl")
with open(tcl, "w") as f:
    f.write("""drc off
crashbackups stop
locking disable
tech unlock *
scalegrid 1 2
snap internal
box values 0 0 0 0
box size 1um 1um
set u [lindex [box values] 2]
gds rescale false
gds drccheck no
gds read %(design)s
load %(top)s -dereference
select top cell
expand
cif ostyle wafflefill(tiled)
select top cell
set fb [box values]
set xlo [expr {int(round([lindex $fb 0] - (%(m)f + %(dx)f) * $u))}]
set ylo [expr {int(round([lindex $fb 1] - (%(m)f + %(dy)f) * $u))}]
set xhi [expr {int(round([lindex $fb 2] + %(m)f * $u))}]
set yhi [expr {int(round([lindex $fb 3] + %(m)f * $u))}]
puts stdout "internal units per um $u, fill box $xlo $ylo $xhi $yhi"
box values $xlo $ylo $xhi $yhi
box grow c 1.6um
flatten -dobox -nolabels %(top)s_fill_pattern
load %(top)s_fill_pattern
property GDS_FILE ""
select top cell
erase COMMENT
box values $xlo $ylo $xhi $yhi
paint COMMENT
gds write %(out)s
quit -noprompt
""" % {"design": os.path.abspath(design), "top": top, "m": MARGIN_UM,
       "dx": dx, "dy": dy, "out": os.path.abspath(out)})

r = subprocess.run(["magic", "-dnull", "-noconsole", "-T", tech, tcl],
                   cwd=work, stdin=subprocess.DEVNULL, capture_output=True,
                   text=True)
for line in r.stdout.splitlines():
    if "fill box" in line or "rror" in line:
        print(line)
if r.returncode != 0 or not os.path.exists(out):
    print(r.stdout[-3000:], r.stderr[-3000:])
    sys.exit(1)
print("wrote", out)
