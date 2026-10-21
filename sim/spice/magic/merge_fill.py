#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Put generated fill into a design as drawn shapes, so magic extracts it.

magic's sky130A.tech extraction has no rules for its fill types (m1fill
and the rest sit in no extraction alias), so fill read in as fill would
add no capacitance at all. Here each fill layer goes onto the drawn layer
it stands for, flat in the top cell, where every square is a floating
conductor of its own: li1, met1 to met4 and poly. Left out: FOM (diff)
fill, which needs implants to mean anything to the extractor and keeps
0.5 um clear of any diff and poly, and met5 fill, because met5 above the
tile is Tiny Tapeout's power grid in the chip, not empty space.

Usage: python3 merge_fill.py DESIGN.gds FILL.gds OUT.gds
"""
import sys

import klayout.db as db

MAP = {(66, 99): (66, 20), (67, 99): (67, 20), (68, 99): (68, 20),
       (69, 99): (69, 20), (70, 99): (70, 20), (71, 99): (71, 20)}

design, fill, out = sys.argv[1:4]
ly = db.Layout()
ly.read(design)
top = ly.top_cells()[0]
fl = db.Layout()
fl.read(fill)
ftop = fl.top_cells()[0]
assert abs(ly.dbu - fl.dbu) < 1e-12
total = 0
for k in fl.layer_indexes():
    i = fl.get_info(k)
    key = (i.layer, i.datatype)
    if key not in MAP:
        print("left out %d/%d" % key)
        continue
    r = db.Region(ftop.begin_shapes_rec(k))
    dst = ly.layer(*MAP[key])
    top.shapes(dst).insert(r)
    total += r.count()
    print("%d/%d -> %d/%d  %d shapes" % (key + MAP[key] + (r.count(),)))
opt = db.SaveLayoutOptions()
opt.format = "GDS2"
ly.write(out, opt)
print("wrote", out, total, "fill shapes")
