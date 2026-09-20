#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
# Independent width and spacing check on the release GDS, KLayout Python API.
# Not a signoff deck: minimum width and same-layer spacing only, the two rules
# that decide whether two wires can touch. Values from the sky130 tech LEF
# (efabless/skywater-pdk-libs-sky130_fd_sc_hd 5a42fd0, tech/*_nom.tlef).
# Needs `pip install klayout`, so it is not in the evidence gate, which runs
# on the standard library. The flow's own Magic and KLayout DRC are, through
# real_world.py reading metrics.json. Run from the repository root:
#   python3 sim/spice/gono/real_world/space_width.py \
#       dualarm/build_armc/tt_um_nikodemetrashvili20_ro_puf.gds
# The smallest drawn gap is recomputed from the edge geometry, because the
# edge pairs KLayout returns for corner-to-corner cases can be zero-length
# and their distance() then reads 0 for two corners 0.25 um apart.
import math, sys, klayout.db as db


def segdist(a, b):
    def pt_seg(p, s):
        (x1, y1), (x2, y2) = (s.p1.x, s.p1.y), (s.p2.x, s.p2.y)
        dx, dy = x2 - x1, y2 - y1
        L = dx * dx + dy * dy
        t = (
            0.0
            if L == 0
            else max(0.0, min(1.0, ((p[0] - x1) * dx + (p[1] - y1) * dy) / L))
        )
        return math.hypot(p[0] - (x1 + t * dx), p[1] - (y1 + t * dy))

    return min(
        pt_seg((a.p1.x, a.p1.y), b),
        pt_seg((a.p2.x, a.p2.y), b),
        pt_seg((b.p1.x, b.p1.y), a),
        pt_seg((b.p2.x, b.p2.y), a),
    )


gds = sys.argv[1]
ly = db.Layout()
ly.read(gds)
top = ly.top_cell()
LAYERS = {  # name: (gds layer, datatype, min width, min space)
    "li1": (67, 20, 0.17, 0.17),
    "met1": (68, 20, 0.14, 0.14),
    "met2": (69, 20, 0.14, 0.14),
    "met3": (70, 20, 0.30, 0.30),
    "met4": (71, 20, 0.30, 0.30),
    "met5": (72, 20, 1.60, 1.60),
}
dbu = ly.dbu
print("top cell", top.name, "dbu", dbu)
for name, (l, d, w, s) in LAYERS.items():
    li = ly.find_layer(l, d)
    if li is None:
        print("%-5s  not drawn in this cell" % name)
        continue
    r = db.Region(top.begin_shapes_rec(li))
    r.merge()
    wv = r.width_check(int(round(w / dbu))).count()
    sv = r.space_check(int(round(s / dbu))).count()
    probe = r.space_check(int(round(1.5 * s / dbu)))
    gaps = [segdist(ep.first, ep.second) * dbu for ep in probe.each()]
    print(
        "%-5s %6d shapes  width<%.2f: %d  space<%.2f: %d  smallest gap %s"
        % (
            name,
            r.count(),
            w,
            wv,
            s,
            sv,
            "%.3f um" % min(gaps) if gaps else "above %.2f" % (1.5 * s),
        )
    )
