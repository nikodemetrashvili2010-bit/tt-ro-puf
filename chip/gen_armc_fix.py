#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Arm C, fixed: the 512 cells of the hand-placed arm set FIRM at step 21,
from the template chip/armc_template.py scored, in the file the flow reads.

Until this was written the third arm had a scored template and no
placement. chip/armc_place.tcl is the August file for the region approach
that turned out to have no mechanism in this flow, and src/pdn_hook.tcl
sourced Arm A only, so a build would have handed Arm C's cells to the
placer and made it Arm A under a second name. That is the one thing
gen_placement_cfg.py's P11 exists to refuse.

What this does is small and all of it is derived. The chosen layout in
chip/ARMC_TEMPLATE.json gives sixteen region origins; the template gives
the grid inside each one, 8 cells a row on 4 rows between the two sites
the well taps take. The order of the 32 cells inside that grid is the one
decision here and it is recorded in ORDER below: a serpentine, with the
output buffer beside the inverter it taps rather than at the end of the
last row. Measured on Arm A as built, the placer kept that buffer 1.8 to
4.6 um from its tap node, median 3.0; the template's recorded default
would have put it two rows away, 5.4 um, past Arm A's worst, which is a
routing difference between the arms and the comparison G.4 preregisters
does not want one. Beside its tap node it is one row away, 2.7 um. The
serpentine closes the loop over three rows, 8.2 um, against Arm A's
worst of 7.0; a row-major walk would have closed it over 11.6.

Everything else is the same mechanism Arm A proved on 11 September: one
proc call per cell, database units, names as the netlist spells them,
OpenDB orientation names, FIRM, and a guard that refuses any count but
512. The file lands in dualarm/src/ beside arma_place.tcl and the wrapper
sources it third. It is called armc_fix.tcl and not armc_place.tcl
because that name is taken by the August record in chip/, which the gate
still regenerates and diffs, and two files of one name doing different
things is how a reader picks the wrong one.

Nothing here has run in the flow. The frozen DEF is checked for the rows,
the taps and the space, and that is a statement about the two-arm build;
the three-arm floorplan is the same die with the same tap pitch, run 80
showed as much, but only the next build says whether 512 of 512 held. So
this also reads a built DEF back (--verify-def) the way
placement_fidelity.py does for Arm A, and CI runs that on the build.

Usage:
    python3 gen_armc_fix.py --selftest
    python3 gen_armc_fix.py
    python3 gen_armc_fix.py --json /tmp/armc_fix.json --emit /tmp/afx
    python3 gen_armc_fix.py --verify-def runs/wokwi/final/def/x.def --annotate
"""

import argparse
import collections
import glob
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import tile_budget as tb  # noqa: E402  the shared hashing rule

TEMPLATE = os.path.join(HERE, "ARMC_TEMPLATE.json")
DEF = os.path.join(ROOT, "dualarm", "build_current",
                   "tt_um_nikodemetrashvili20_ro_puf.def")
LEF = os.path.join(ROOT, "dualarm", "src", "ro_macro_hard.lef")
CONFIG = os.path.join(ROOT, "dualarm", "src", "config.json")
RTL = os.path.join(ROOT, "dualarm", "src", "ro_armc.v")
ARMA_HOOK = os.path.join(ROOT, "dualarm", "src", "arma_place.tcl")
WRAPPER = os.path.join(ROOT, "dualarm", "src", "pdn_hook.tcl")
HOOK_NAME = "armc_fix.tcl"
HOOK_DEST = os.path.join(ROOT, "dualarm", "src", HOOK_NAME)
JSON_DEST = os.path.join(HERE, "ARMC_FIX.json")

PREFIX = "u_puf.u_core.g_armc[%d].u_roc."
ARM_C_RE = re.compile(r"^u_puf\.u_core\.g_armc\[(\d+)\]\.u_roc\.(.+)$")
ARM_A_RE = re.compile(r"^u_puf\.u_core\.g_ro_bank\[(\d+)\]\.u_ro\.")
TAP_MASTER = "sky130_fd_sc_hd__tapvpwrvgnd_1"
MACRO_MASTER = "ro_macro_hard"
MASTERS = {"u_nand": "sky130_fd_sc_hd__nand2_1",
           "u_buf": "sky130_fd_sc_hd__buf_1"}
INV_MASTER = "sky130_fd_sc_hd__inv_1"
STATUS = "FIRM"
GRIDIFY = 5
LEF2OA = {"N": "R0", "FS": "MX"}
OA2LEF = {"R0": "N", "MX": "FS"}
FLIP = {"N": "FS", "FS": "N"}
BOX_KEY = "PL_SOFT_OBSTRUCTIONS"

# The order. Positions 0 to 31 walk the grid as a serpentine: row 0 left
# to right, row 1 right to left, and so on. The chain is the enable NAND
# and then g_inv[0] to g_inv[N_INV-1] in ring order, which is how
# ro_armc.v wires it, n[i] into g_inv[i] and out as n[i+1]. The buffer
# taps n[N_INV/2], the output of g_inv[N_INV/2 - 1], so it is placed right
# after that inverter in the walk, which puts it on the next row directly
# above it. Picked 2026-09-16 out of three orders measured against Arm
# A as built; see docs/phaseG_armc_fix.md.
ORDER = "serpentine, buffer after g_inv[N_INV/2-1]"

HOOK_LINE_RE = re.compile(r"^armc_fix \{([^{}\s]+)\} (\d+) (\d+) "
                          r"(R0|R90|R180|R270|MY|MYR90|MX|MXR90)$")


def sha256_file(path):
    return tb.sha256_file(path)


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


# ------------------------------------------------------------------ inputs

Row = collections.namedtuple("Row", "name y x nsites step orient")
Cell = collections.namedtuple("Cell", "inst master x y orient status")

ROW_RE = re.compile(
    r"^ROW\s+(\S+)\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\S+)\s+DO\s+(\d+)\s+BY\s+"
    r"(\d+)\s+STEP\s+(\d+)\s+(\d+)\s*;")
COMP_RE = re.compile(r"^-\s+(\S+)\s+(\S+)\s*(.*)$")
PLACE_RE = re.compile(
    r"\+\s*(FIXED|PLACED|COVER|UNPLACED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*"
    r"(\S+)")


def read_def(path):
    """Units, die, rows and placed components. The DEF escapes each
    bracket with a backslash; the names come back unescaped, the way the
    RTL spells them, and go out escaped again when written to Tcl."""
    units = None
    die = None
    rows = []
    cells = []
    in_comps = False
    buf = ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("UNITS DISTANCE MICRONS"):
                units = int(s.split()[3])
            elif s.startswith("DIEAREA"):
                nums = [int(v) for v in re.findall(r"-?\d+", s)]
                die = (nums[0], nums[1], nums[2], nums[3])
            elif s.startswith("ROW "):
                m = ROW_RE.match(s)
                if m:
                    rows.append(Row(m.group(1), int(m.group(4)),
                                    int(m.group(3)), int(m.group(6)),
                                    int(m.group(8)), m.group(5)))
            elif s.startswith("COMPONENTS"):
                in_comps = True
            elif s.startswith("END COMPONENTS"):
                in_comps = False
            elif in_comps:
                buf += " " + s
                if s.endswith(";"):
                    m = COMP_RE.match(buf.strip())
                    if m:
                        inst = m.group(1).replace("\\", "")
                        p = PLACE_RE.search(m.group(3))
                        if p:
                            cells.append(Cell(inst, m.group(2),
                                              int(p.group(2)),
                                              int(p.group(3)), p.group(4),
                                              p.group(1)))
                        else:
                            cells.append(Cell(inst, m.group(2), None, None,
                                              None, "UNPLACED"))
                    buf = ""
    if units is None or not rows:
        raise SystemExit("not a DEF I can read: %s" % path)
    return {"units": units, "die": die, "rows": rows, "cells": cells}


def macro_size(lef_path, units):
    text = open(lef_path, encoding="utf-8", errors="replace").read()
    m = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", text)
    return (int(round(float(m.group(1)) * units)),
            int(round(float(m.group(2)) * units)))


def n_inv(rtl_path):
    text = open(rtl_path, encoding="utf-8", errors="replace").read()
    m = re.search(r"parameter\s+integer\s+N_INV\s*=\s*(\d+)", text)
    if not m:
        raise SystemExit("no N_INV in %s" % rtl_path)
    return int(m.group(1))


def ring_names(inv_count):
    """The 32 instance names one ring carries, in chain order with the
    buffer put in after the inverter it taps."""
    chain = ["u_nand"] + ["g_inv[%d].u_inv" % i for i in range(inv_count)]
    tap_driver = "g_inv[%d].u_inv" % (inv_count // 2 - 1)
    at = chain.index(tap_driver) + 1
    return chain[:at] + ["u_buf"] + chain[at:]


def load_template(path):
    t = json.load(open(path, encoding="utf-8"))
    chosen = t.get("chosen_layout")
    lay = (t.get("layouts") or {}).get(chosen) or {}
    return t, chosen, lay


# ----------------------------------------------------------------- geometry

def placements(template, layout, inv_count, units):
    """Every cell of every ring: name, region, row, col, x, y, LEF orient.
    Nothing typed: the region origins are the layout's, the grid is the
    template's, the names are the RTL's."""
    tpl = template["template"]
    step = int(round(tpl["width_um"] * units / tpl["sites"]))
    rh = int(round(tpl["height_um"] * units / tpl["rows"]))
    lo = tpl["cell_sites_from_to"][0]
    per_row = tpl["cells_per_row"]
    csites = tpl["cell_sites"]
    first = tpl["first_row_orient"]
    names = ring_names(inv_count)
    out = []
    for reg in sorted(layout.get("regions") or [], key=lambda r: r["index"]):
        x0 = int(round(reg["x0_um"] * units))
        y0 = int(round(reg["y0_um"] * units))
        for k, name in enumerate(names):
            row, pos = divmod(k, per_row)
            col = pos if row % 2 == 0 else per_row - 1 - pos
            orient = first if row % 2 == 0 else FLIP[first]
            out.append({
                "ring": reg["index"], "row": row, "col": col, "walk": k,
                "cell": name, "inst": (PREFIX % reg["index"]) + name,
                "master": MASTERS.get(name, INV_MASTER),
                "x": x0 + (lo + csites * col) * step, "y": y0 + row * rh,
                "orient": orient,
            })
    return out, {"step": step, "row_height": rh, "cell_sites": csites,
                 "cells_per_row": per_row, "rows": tpl["rows"],
                 "sites": tpl["sites"], "cell_lo": lo,
                 "cell_hi": lo + csites * per_row,
                 "reserved": list(tpl["reserved_tap_sites"]),
                 "first_orient": first}


def escape(name):
    return name.replace("[", "\\[").replace("]", "\\]")


def render_hook(cells):
    n = len(cells)
    out = [
        "# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili",
        "# SPDX-License-Identifier: Apache-2.0",
        "#",
        "# Arm C, fixed. Generated by chip/gen_armc_fix.py, do not edit.",
        "#",
        "# The third line src/pdn_hook.tcl sources, after the PDN recipe and",
        "# Arm A's arma_place.tcl, inside OpenROAD at OpenROAD.GeneratePDN,",
        "# step 21: rows cut, taps and endcaps in, nothing placed yet. The",
        "# same mechanism that held Arm A 512 of 512 on run 80, for the same",
        "# reasons (docs/phaseG_run77.md), on the hand-placed template",
        "# chip/armc_template.py scored (chip/ARMC_TEMPLATE.json).",
        "#",
        "# Sixteen rings, one template each: 8 cells a row on 4 rows, sites",
        "# 12 to 35 of a 56-site region, the well taps on sites 11 and 39",
        "# left clear. Serpentine order with the output buffer beside the",
        "# inverter it taps; see the generator for why.",
        "#",
        "# Coordinates in database units. Names as the netlist spells them,",
        "# a backslash before each bracket, braced so Tcl passes them",
        "# through untouched. Orientations as OpenDB names.",
        "",
        "proc armc_fix {name x y orient} {",
        "    set block [ord::get_db_block]",
        "    set inst [$block findInst $name]",
        "    if { $inst == \"NULL\" } {",
        "        error \"armc_fix: no instance $name\"",
        "    }",
        "    if { [$inst isFixed] } {",
        "        error \"armc_fix: $name is already fixed\"",
        "    }",
        "    $inst setOrient $orient",
        "    $inst setLocation $x $y",
        "    $inst setPlacementStatus %s" % STATUS,
        "    incr ::armc_fixed",
        "}",
        "",
        "set ::armc_fixed 0",
    ]
    for c in sorted(cells, key=lambda c: (c["ring"], c["walk"])):
        out.append("armc_fix {%s} %d %d %s"
                   % (escape(c["inst"]), c["x"], c["y"], LEF2OA[c["orient"]]))
    out += [
        "",
        "if { $::armc_fixed != %d } {" % n,
        "    error \"armc_fix: fixed $::armc_fixed of %d\"" % n,
        "}",
        "puts \"\\[INFO\\] armc_fix: $::armc_fixed Arm C cells set %s\""
        % STATUS,
        "",
    ]
    return "\n".join(out)


def parse_hook(text):
    entries = collections.OrderedDict()
    bad = []
    for line in text.splitlines():
        if not line.startswith("armc_fix "):
            continue
        m = HOOK_LINE_RE.match(line)
        if not m or m.group(1) in entries:
            bad.append(line)
            continue
        entries[m.group(1)] = (int(m.group(2)), int(m.group(3)), m.group(4))
    sm = re.search(r"setPlacementStatus (\w+)", text)
    cm = re.search(r"\$::armc_fixed != (\d+)", text)
    return (entries, sm.group(1) if sm else None,
            int(cm.group(1)) if cm else None, bad)


def source_line(name):
    return "source [file join [file dirname [info script]] %s]" % name


# ------------------------------------------------------------------- checks

def run_checks(template, chosen, layout, design, cells, geo, macro_wh,
               config, hook_text, wrapper_text, arma_text, inv_count):
    res = Results()
    units = design["units"]
    rows = design["rows"]
    regs = sorted(layout.get("regions") or [], key=lambda r: r["index"])
    step, rh = geo["step"], geo["row_height"]
    tpl = template.get("template") or {}

    # -- K01: the template file says what this needs it to say -----------
    span_ok = (geo["cell_hi"] <= tpl.get("sites", 0)
               and all(s < geo["cell_lo"] or s >= geo["cell_hi"]
                       for s in geo["reserved"])
               and geo["cell_lo"] >= 0)
    ok = (chosen and layout.get("chosen") is True
          and len(regs) == layout.get("count") == 16
          and tpl.get("rows") == 4 and tpl.get("cells_per_row") == 8
          and tpl.get("cell_sites") == 3
          and tpl.get("first_row_orient") in LEF2OA
          and span_ok
          and geo["rows"] * geo["cells_per_row"] == len(ring_names(inv_count)))
    res.add("K01", "the template names a chosen layout of sixteen regions "
            "and a 4 by 8 grid that fits between the reserved sites", ok,
            "layout %s chosen %s, %d regions, %s rows x %s cells, sites %s "
            "to %s, reserved %s, ring %d cells"
            % (chosen, layout.get("chosen"), len(regs), tpl.get("rows"),
               tpl.get("cells_per_row"), geo["cell_lo"], geo["cell_hi"],
               geo["reserved"], len(ring_names(inv_count))))

    # -- K02: every region row exists, full width, in the right phase ----
    missing = []
    wrong = []
    for r in regs:
        x0 = int(round(r["x0_um"] * units))
        y0 = int(round(r["y0_um"] * units))
        x1 = x0 + geo["sites"] * step
        for k in range(geo["rows"]):
            y = y0 + k * rh
            first = geo["first_orient"]
            want = first if k % 2 == 0 else FLIP[first]
            hit = [rw for rw in rows if rw.y == y and rw.x <= x0
                   and rw.x + rw.nsites * rw.step >= x1 and rw.step == step]
            if not hit:
                missing.append((r["index"], k))
            elif hit[0].orient != want:
                wrong.append((r["index"], k, hit[0].orient))
    ok = not missing and not wrong and regs
    res.add("K02", "every region's four rows exist in the DEF at full "
            "width, alternating from the template's first orientation", ok,
            "%d region rows, %d missing, %d in the wrong phase"
            % (len(regs) * geo["rows"], len(missing), len(wrong)))

    # -- K03: the taps sit on the reserved sites and nowhere else --------
    taps = [c for c in design["cells"] if c.master == TAP_MASTER
            and c.x is not None]
    on_cells = []
    off_reserved = []
    for r in regs:
        x0 = int(round(r["x0_um"] * units))
        y0 = int(round(r["y0_um"] * units))
        for k in range(geo["rows"]):
            y = y0 + k * rh
            for t in taps:
                if t.y != y or not (x0 <= t.x < x0 + geo["sites"] * step):
                    continue
                site = (t.x - x0) // step
                if geo["cell_lo"] <= site < geo["cell_hi"]:
                    on_cells.append((r["index"], k, site))
                if site not in geo["reserved"]:
                    off_reserved.append((r["index"], k, site))
    ok = not on_cells and not off_reserved and taps
    res.add("K03", "inside every region the well taps stand only on the "
            "reserved sites, none on a cell site", ok,
            "%d tap cells in the DEF, %d on a cell site, %d off the "
            "reserved sites" % (len(taps), len(on_cells), len(off_reserved)))

    # -- K04: nothing fixed stands in the cell sites ---------------------
    # Arm A by name, the macros by master, and then everything else the
    # DEF holds FIXED or COVER apart from the taps K03 owns: the endcaps
    # at the row ends, mostly. Their widths are not read from a LEF, so
    # each is taken as four sites wide, which is wider than any of them.
    cw = geo["cell_sites"] * step
    mw, mh = macro_wh
    arma = [c for c in design["cells"] if ARM_A_RE.match(c.inst)
            and c.x is not None]
    macros = [c for c in design["cells"] if c.master == MACRO_MASTER
              and c.x is not None]
    others = [c for c in design["cells"] if c.status in ("FIXED", "COVER")
              and c.master not in (MACRO_MASTER, TAP_MASTER)
              and not ARM_A_RE.match(c.inst) and c.x is not None]
    clash = []
    for r in regs:
        x0 = int(round(r["x0_um"] * units))
        y0 = int(round(r["y0_um"] * units))
        lo = x0 + geo["cell_lo"] * step
        hi = x0 + geo["cell_hi"] * step
        y1 = y0 + geo["rows"] * rh
        for c in arma:
            if c.y >= y0 and c.y < y1 and c.x < hi and c.x + cw > lo:
                clash.append(("arm_a", c.inst))
        for c in macros:
            if c.x < hi and c.x + mw > lo and c.y < y1 and c.y + mh > y0:
                clash.append(("macro", c.inst))
        for c in others:
            if c.y >= y0 and c.y < y1 and c.x < hi and c.x + 4 * step > lo:
                clash.append(("fixed", c.inst))
    ok = not clash and len(arma) == 512 and len(macros) == 16
    res.add("K04", "no Arm A cell, no Arm B macro and no other fixed cell "
            "stands in any region's cell sites", ok,
            "%d Arm A cells, %d macros and %d other fixed cells in the "
            "DEF, %d clashes"
            % (len(arma), len(macros), len(others), len(clash)))

    # -- K05: every region is outside the soft box round Arm A -----------
    box = (config.get(BOX_KEY) or [[]])[0]
    inside = []
    if len(box) == 4:
        bx0, by0, bx1, by1 = [int(round(float(v) * units)) for v in box]
        for r in regs:
            x0 = int(round(r["x0_um"] * units))
            y0 = int(round(r["y0_um"] * units))
            x1 = x0 + geo["sites"] * step
            y1 = y0 + geo["rows"] * rh
            if x0 < bx1 and x1 > bx0 and y0 < by1 and y1 > by0:
                inside.append(r["index"])
    ok = len(box) == 4 and not inside
    res.add("K05", "every region lies outside the soft obstruction "
            "config.json draws round Arm A", ok,
            "box %s, %d region(s) overlapping it" % (box, len(inside)))

    # -- K06: the names are the RTL's, once each, and none is Arm A's ----
    want = set(ring_names(inv_count))
    per_ring = collections.defaultdict(list)
    for c in cells:
        per_ring[c["ring"]].append(c["cell"])
    bad_ring = [i for i, names in per_ring.items()
                if len(names) != len(want) or set(names) != want]
    insts = [c["inst"] for c in cells]
    dup = len(insts) - len(set(insts))
    arma_names = set(re.findall(r"arma_fix \{([^{}\s]+)\}", arma_text))
    arma_names = set(n.replace("\\", "") for n in arma_names)
    shared = sorted(set(insts) & arma_names)
    ok = (len(cells) == 16 * len(want) and not bad_ring and dup == 0
          and not shared and all(ARM_C_RE.match(i) for i in insts))
    res.add("K06", "512 cells, 32 per ring named as ro_armc.v names them, "
            "each once, and none of them an Arm A name", ok,
            "%d cells, %d rings off, %d duplicates, %d shared with Arm A"
            % (len(cells), len(bad_ring), dup, len(shared)))

    # -- K07: on the grid, inside the region, no two on one site ---------
    die = design["die"]
    offgrid = []
    outside = []
    occ = collections.Counter()
    for c in cells:
        r = next(x for x in regs if x["index"] == c["ring"])
        x0 = int(round(r["x0_um"] * units))
        y0 = int(round(r["y0_um"] * units))
        if (c["x"] - x0) % step or c["x"] % GRIDIFY or c["y"] % GRIDIFY \
                or (c["y"] - y0) % rh:
            offgrid.append(c["inst"])
        s = (c["x"] - x0) // step
        if not (geo["cell_lo"] <= s and s + geo["cell_sites"] <= geo["cell_hi"]
                and y0 <= c["y"] < y0 + geo["rows"] * rh
                and die[0] <= c["x"] and c["x"] + cw <= die[2]
                and die[1] <= c["y"] and c["y"] + rh <= die[3]):
            outside.append(c["inst"])
        for k in range(geo["cell_sites"]):
            occ[(c["y"], c["x"] + k * step)] += 1
    overlap = sum(1 for v in occ.values() if v > 1)
    ok = not offgrid and not outside and overlap == 0
    res.add("K07", "every cell sits on its row's site grid, inside its "
            "region's cell span and the die, and no site is used twice",
            ok, "%d off grid, %d outside, %d sites used twice"
            % (len(offgrid), len(outside), overlap))

    # -- K08: the order is the declared one and identical in every ring --
    by = {(c["ring"], c["cell"]): c for c in cells}
    tap_driver = "g_inv[%d].u_inv" % (inv_count // 2 - 1)
    chain = ["u_nand"] + ["g_inv[%d].u_inv" % i for i in range(inv_count)]
    far = []
    buf_far = []
    shape = None
    same = True
    for ring in sorted(per_ring):
        def d(a, b):
            ca, cb = by[(ring, a)], by[(ring, b)]
            return abs(ca["x"] - cb["x"]), abs(ca["y"] - cb["y"])
        for a, b in zip(chain, chain[1:]):
            dx, dy = d(a, b)
            if dx > 2 * cw or dy > rh:      # one cell over, or the row turn
                far.append((ring, a, b, dx, dy))
        dx, dy = d("u_buf", tap_driver)
        if dx > cw or dy > rh:
            buf_far.append((ring, dx, dy))
        o = by[(ring, "u_nand")]
        rel = tuple(sorted((c["cell"], c["x"] - o["x"], c["y"] - o["y"],
                            c["orient"]) for c in cells if c["ring"] == ring))
        if shape is None:
            shape = rel
        elif rel != shape:
            same = False
    fb = None
    if cells:
        r0 = min(per_ring)
        a, b = by[(r0, "u_nand")], by[(r0, chain[-1])]
        fb = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5 / units
    ok = not far and not buf_far and same and cells
    res.add("K08", "chain neighbours are adjacent, the buffer sits beside "
            "the inverter it taps, and all sixteen rings are one shape", ok,
            "%d chain steps apart, %d buffers apart, one shape: %s, loop "
            "closes over %.2f um" % (len(far), len(buf_far), same, fb or 0))

    # -- K09: the hook on disk is exactly the rendering, read back --------
    entries, status, guard, badlines = parse_hook(hook_text)
    want = {escape(c["inst"]): (c["x"], c["y"], LEF2OA[c["orient"]])
            for c in cells}
    missing = [n for n in want if n not in entries]
    extra = [n for n in entries if n not in want]
    moved = [n for n in want if n in entries and entries[n] != want[n]]
    ok = (not missing and not extra and not moved and not badlines
          and status == STATUS and guard == len(want) and want)
    res.add("K09", "the hook file fixes every cell FIRM at the template "
            "coordinate and orientation, nothing else, and guards the count",
            ok, "%d wanted, %d in the hook, %d missing, %d extra, %d moved, "
            "%d unparsed, status %s, guard %s"
            % (len(want), len(entries), len(missing), len(extra),
               len(moved), len(badlines), status, guard))

    # -- K10: the wrapper sources it third -------------------------------
    live = tuple(l.strip() for l in wrapper_text.splitlines()
                 if l.strip() and not l.strip().startswith("#"))
    ok = (len(live) == 3 and live[0] == source_line("pdn_cfg.tcl")
          and live[1] == source_line("arma_place.tcl")
          and live[2] == source_line(HOOK_NAME))
    res.add("K10", "src/pdn_hook.tcl sources the recipe, Arm A and then "
            "this file, relative to itself, and nothing else", ok,
            "%d live line(s); third is %r" % (len(live),
                                              live[2] if len(live) > 2
                                              else None))

    # -- K11: regions do not overlap and span what the template records --
    boxes = []
    for r in regs:
        x0 = int(round(r["x0_um"] * units))
        y0 = int(round(r["y0_um"] * units))
        boxes.append((x0, y0, x0 + geo["sites"] * step, y0 + geo["rows"] * rh))
    pairs = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]:
                pairs += 1
    bbox = None
    if boxes:
        bbox = [min(b[0] for b in boxes) / units,
                min(b[1] for b in boxes) / units,
                max(b[2] for b in boxes) / units,
                max(b[3] for b in boxes) / units]
    want_bbox = layout.get("bbox_um")
    ok = pairs == 0 and bbox is not None and want_bbox is not None and \
        all(abs(a - b) < 1e-6 for a, b in zip(bbox, want_bbox))
    res.add("K11", "no two regions overlap and their bounding box is the "
            "one the template records", ok,
            "%d overlapping pairs, bbox %s, recorded %s"
            % (pairs, bbox, want_bbox))

    # -- K12: the rendering is a function of its inputs ------------------
    ok = render_hook(cells) == render_hook(list(reversed(cells)))
    res.add("K12", "the hook renders the same bytes from the same cells "
            "whatever order they arrive in", ok, "%d bytes"
            % len(render_hook(cells)))
    return res


# ------------------------------------------------------------- built DEF

def verify_built(cells, def_path):
    """The same question placement_fidelity.py asks of Arm A, asked of
    Arm C on a DEF the build wrote. Returns (Results, report dict)."""
    design = read_def(def_path)
    comps = {c.inst: c for c in design["cells"]}
    res = Results()
    absent, moved, turned, unplaced, resized = [], [], [], [], []
    for c in cells:
        d = comps.get(c["inst"])
        if d is None:
            absent.append(c["inst"])
            continue
        if d.status == "UNPLACED" or d.x is None:
            unplaced.append(c["inst"])
            continue
        if (d.x, d.y) != (c["x"], c["y"]):
            moved.append((c["inst"], d.x - c["x"], d.y - c["y"]))
        if d.orient != c["orient"]:
            turned.append((c["inst"], d.orient))
        if d.master != c["master"]:
            resized.append((c["inst"], d.master))
    n = len(cells)
    res.add("K13", "every Arm C cell the hook fixed is in the DEF",
            not absent, "%d of %d present" % (n - len(absent), n))
    res.add("K14", "every one stands at its coordinate, to the dbu",
            not moved, "%d moved" % len(moved))
    res.add("K15", "every one carries its orientation", not turned,
            "%d turned" % len(turned))
    res.add("K16", "none is UNPLACED", not unplaced,
            "%d unplaced" % len(unplaced))
    res.add("K17", "every one is still the cell the RTL instantiates, "
            "not a resized master", not resized,
            "%d resized" % len(resized))
    held = n - len(absent) - len(unplaced) - len(set(
        m[0] for m in moved) | set(t[0] for t in turned))
    rep = {"def": def_path, "cells": n, "held": held,
           "absent": absent[:12], "moved": moved[:12], "turned": turned[:12],
           "unplaced": unplaced[:12], "resized": resized[:12]}
    return res, rep


def annotate(res, rep):
    """A GitHub annotation, the one thing a signed-out reader sees."""
    def enc(s):
        return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    head = "Arm C held %d of %d cells FIRM" % (rep["held"], rep["cells"])
    body = []
    for r in res.rows:
        body.append("%s %s: %s" % ("ok  " if r["pass"] else "FAIL",
                                  r["id"], r["detail"]))
    for k in ("moved", "turned", "resized", "absent", "unplaced"):
        for item in rep[k][:20]:
            body.append("%s %s" % (k, item))
        if len(rep[k]) > 20:
            body.append("%s ... and %d more" % (k, len(rep[k]) - 20))
    level = "notice" if not res.failed() else "warning"
    print("::%s title=%s::%s" % (level, enc(head), enc("\n".join(body))))
    print(head)
    for line in body:
        print("   " + line)


# ------------------------------------------------------------------ fixture

def _fixture(tmp, regions=16, tap_shift=0, tap_on_cell=False,
             arm_a_in_region=False, macro_in_region=False, box=None,
             drop_row=False, flip_row=False, hook_edit=None,
             wrapper_edit=None, template_edit=None, inv_count=30,
             endcap_in_region=False):
    """A die the size of the real one in count if not in shape: 46 rows
    of 1100 sites, taps every 56 sites in alternating phase like the real
    one, 16 template regions in two bands of eight on rows 1..8, the 16
    Arm A rings (512 cells) on rows 10..13 and the 16 macros below them,
    all clear of the regions."""
    units, step, rh = 1000, 460, 2720
    nrow = 46
    nsites = 1100
    rows = []
    for k in range(nrow):
        rows.append("ROW ROW_%d unithd 0 %d %s DO %d BY 1 STEP %d 0 ;"
                    % (k, k * rh, "N" if k % 2 == 0 else "FS", nsites, step))
    cells = []
    tap_i = 0
    for k in range(nrow):
        phase = (11 if k % 2 else 39) + tap_shift
        s = phase
        while s < nsites:
            cells.append("- tap%d %s + FIXED ( %d %d ) %s ;"
                         % (tap_i, TAP_MASTER, s * step, k * rh,
                            "N" if k % 2 == 0 else "FS"))
            tap_i += 1
            s += 56
    # region i at site 56*(i%8), band i//8 on rows 1..4 or 5..8 (rows 1
    # and 5 are FS, the template's first orientation)
    reg_list = []
    for i in range(regions):
        x0 = 56 * (i % 8) * step
        y0 = (1 + 4 * (i // 8)) * rh
        reg_list.append({"index": i, "x0_um": x0 / units, "y0_um": y0 / units,
                         "x1_um": (x0 + 56 * step) / units,
                         "y1_um": (y0 + 4 * rh) / units, "where": "strip"})
    # Arm A: 16 rings of 32 cells, two rows of 16 each, on rows 10..13
    names = (["u_nand"] + ["g_inv[%d].u_inv" % i for i in range(1, 31)]
             + ["u_buf"])
    for ring in range(16):
        for k, nm in enumerate(names):
            r, c = divmod(k, 16)
            x = ((ring % 8) * 60 + 3 * c) * step
            y = (10 + 2 * (ring // 8) + r) * rh
            if arm_a_in_region and ring == 0 and k == 0:
                x, y = (12 * step, 2 * rh)
            cells.append("- u_puf.u_core.g_ro_bank\\[%d\\].u_ro.%s %s "
                         "+ PLACED ( %d %d ) N ;"
                         % (ring, nm.replace("[", "\\[").replace("]", "\\]"),
                            MASTERS.get(nm, INV_MASTER), x, y))
    # the 16 macros, 60 x 40 um each, two rows of eight from row 15 down
    for m in range(16):
        mx = (m % 8) * 131 * step
        my = (15 + 15 * (m // 8)) * rh
        if macro_in_region and m == 0:
            mx, my = (20 * step, 3 * rh)
        cells.append("- u_rob%d %s + FIXED ( %d %d ) N ;"
                     % (m, MACRO_MASTER, mx, my))
    if drop_row:
        rows = [r for r in rows if not r.startswith("ROW ROW_3 ")]
    if flip_row:
        rows = [r.replace("ROW ROW_3 unithd 0 %d FS" % (3 * rh),
                          "ROW ROW_3 unithd 0 %d N" % (3 * rh)) for r in rows]
    if tap_on_cell:
        cells.append("- tapx %s + FIXED ( %d %d ) FS ;"
                     % (TAP_MASTER, 20 * step, 1 * rh))
    if endcap_in_region:
        cells.append("- PHY_9 sky130_fd_sc_hd__decap_3 + FIXED ( %d %d ) N ;"
                     % (30 * step, 2 * rh))
    d = ["VERSION 5.8 ;", "DESIGN top ;",
         "UNITS DISTANCE MICRONS %d ;" % units,
         "DIEAREA ( 0 0 ) ( %d %d ) ;" % (nsites * step, nrow * rh)]
    d += rows
    d += ["COMPONENTS %d ;" % len(cells)] + cells
    d += ["END COMPONENTS", "END DESIGN"]
    paths = {}
    paths["def"] = os.path.join(tmp, "f.def")
    open(paths["def"], "w").write("\n".join(d) + "\n")
    paths["lef"] = os.path.join(tmp, "m.lef")
    open(paths["lef"], "w").write(
        "MACRO ro_macro_hard\n  SIZE 60.0 BY 40.0 ;\nEND\n")
    paths["rtl"] = os.path.join(tmp, "ro_armc.v")
    open(paths["rtl"], "w").write(
        "module ro_armc #(parameter integer N_INV = %d)();endmodule\n"
        % inv_count)
    paths["config"] = os.path.join(tmp, "config.json")
    # the soft box sits over the Arm A rows, as the real one does
    json.dump({BOX_KEY: [box or [0.0, 27.2, 220.8, 38.08]]},
              open(paths["config"], "w"))
    tpl = {
        "chosen_layout": "column",
        "layouts": {"column": {"chosen": True, "count": regions,
                               "regions": reg_list,
                               "bbox_um": [
                                   min(r["x0_um"] for r in reg_list),
                                   min(r["y0_um"] for r in reg_list),
                                   max(r["x1_um"] for r in reg_list),
                                   max(r["y1_um"] for r in reg_list)]}},
        "template": {"sites": 56, "rows": 4, "cells_per_row": 8,
                     "cell_sites": 3, "cell_sites_from_to": [12, 35],
                     "reserved_tap_sites": [11, 39],
                     "first_row_orient": "FS",
                     "width_um": 56 * step / units,
                     "height_um": 4 * rh / units},
    }
    if template_edit:
        template_edit(tpl)
    paths["template"] = os.path.join(tmp, "t.json")
    json.dump(tpl, open(paths["template"], "w"))
    paths["arma"] = os.path.join(tmp, "arma_place.tcl")
    open(paths["arma"], "w").write(
        "arma_fix {u_puf.u_core.g_ro_bank\\[0\\].u_ro.u_nand} 1 1 R0\n")
    wrapper = "\n".join([source_line("pdn_cfg.tcl"),
                         source_line("arma_place.tcl"),
                         source_line(HOOK_NAME)]) + "\n"
    if wrapper_edit:
        wrapper = wrapper_edit(wrapper)
    paths["wrapper"] = os.path.join(tmp, "pdn_hook.tcl")
    open(paths["wrapper"], "w").write(wrapper)
    paths["hook"] = os.path.join(tmp, HOOK_NAME)
    paths["hook_edit"] = hook_edit
    return paths


def run_fixture(tmp, **kw):
    p = _fixture(tmp, **kw)
    template, chosen, layout = load_template(p["template"])
    design = read_def(p["def"])
    inv = n_inv(p["rtl"])
    cells, geo = placements(template, layout, inv, design["units"])
    text = render_hook(cells)
    if p["hook_edit"]:
        text = p["hook_edit"](text)
    open(p["hook"], "w").write(text)
    res = run_checks(template, chosen, layout, design, cells, geo,
                     macro_size(p["lef"], design["units"]),
                     json.load(open(p["config"])), open(p["hook"]).read(),
                     open(p["wrapper"]).read(), open(p["arma"]).read(), inv)
    return cells, res


def _no_choice(t):
    t["layouts"]["column"]["chosen"] = False


def _bad_bbox(t):
    t["layouts"]["column"]["bbox_um"][2] += 1.0


def _overlap(t):
    t["layouts"]["column"]["regions"][1]["x0_um"] = \
        t["layouts"]["column"]["regions"][0]["x0_um"] + 1.38


def _move_one(text):
    return text.replace("} 5520 2720 MX", "} 5980 2720 MX", 1)


def _drop_guard(text):
    return text.replace("$::armc_fixed != 512", "$::armc_fixed != 511")


def _two_lines(w):
    return "\n".join(w.splitlines()[:2]) + "\n"


FAULTS = (
    ("K01", "the layout is present but not marked chosen",
     lambda tmp: run_fixture(tmp, template_edit=_no_choice)),
    ("K02", "a region row the DEF does not have",
     lambda tmp: run_fixture(tmp, drop_row=True)),
    ("K03", "a tap standing on a cell site",
     lambda tmp: run_fixture(tmp, tap_on_cell=True)),
    ("K04", "an Arm A cell inside a region",
     lambda tmp: run_fixture(tmp, arm_a_in_region=True)),
    ("K04", "a macro over a region",
     lambda tmp: run_fixture(tmp, macro_in_region=True)),
    ("K04", "an endcap standing in a region's cell sites",
     lambda tmp: run_fixture(tmp, endcap_in_region=True)),
    ("K05", "the soft box drawn over a region",
     lambda tmp: run_fixture(tmp, box=[0.0, 0.0, 30.0, 20.0])),
    ("K09", "one line of the hook moved a site",
     lambda tmp: run_fixture(tmp, hook_edit=_move_one)),
    ("K09", "the guard asking for one cell fewer",
     lambda tmp: run_fixture(tmp, hook_edit=_drop_guard)),
    ("K10", "the wrapper without its third line",
     lambda tmp: run_fixture(tmp, wrapper_edit=_two_lines)),
    ("K11", "the recorded bounding box a micron out",
     lambda tmp: run_fixture(tmp, template_edit=_bad_bbox)),
)


def selftest():
    ok = True
    tmp = tempfile.mkdtemp(prefix="armc_fix_")
    try:
        cells, res = run_fixture(tmp)
        if res.failed():
            print("  FAIL clean fixture: %s" % ", ".join(res.failed()))
            for r in res.rows:
                if not r["pass"]:
                    print("        %s %s" % (r["id"], r["detail"]))
            ok = False
        else:
            print("  ok    clean fixture passes all %d checks"
                  % len(res.rows))
        # the order, by hand: 16 rings x 32, buffer above g_inv[14]
        by = {(c["ring"], c["cell"]): c for c in cells}
        b, t = by[(0, "u_buf")], by[(0, "g_inv[14].u_inv")]
        if not (b["x"] == t["x"] and b["y"] - t["y"] == 2720
                and by[(0, "u_nand")]["col"] == 0
                and by[(0, "u_nand")]["row"] == 0
                and by[(0, "g_inv[29].u_inv")]["col"] == 0
                and by[(0, "g_inv[29].u_inv")]["row"] == 3
                and len(cells) == 512):
            print("  FAIL the order is not the serpentine described")
            ok = False
        else:
            print("  ok    buffer above its tap driver, loop closes at "
                  "column 0")
        # the built-DEF reading, on a DEF made from the rendering
        def_text = ["VERSION 5.8 ;", "UNITS DISTANCE MICRONS 1000 ;",
                    "DIEAREA ( 0 0 ) ( 506000 125120 ) ;",
                    "ROW R unithd 0 0 N DO 1100 BY 1 STEP 460 0 ;",
                    "COMPONENTS %d ;" % len(cells)]
        for c in cells:
            def_text.append("- %s %s + FIXED ( %d %d ) %s ;"
                            % (escape(c["inst"]), c["master"], c["x"], c["y"],
                               c["orient"]))
        def_text += ["END COMPONENTS", "END DESIGN"]
        p = os.path.join(tmp, "built.def")
        open(p, "w").write("\n".join(def_text) + "\n")
        r, rep = verify_built(cells, p)
        if r.failed() or rep["held"] != len(cells):
            print("  FAIL a faithful DEF reads as %s" % r.failed())
            ok = False
        else:
            print("  ok    a faithful built DEF reads %d of %d held"
                  % (rep["held"], len(cells)))
        for cid, what, fn in FAULTS:
            sub = tempfile.mkdtemp(prefix="f_", dir=tmp)
            try:
                _c, r = fn(sub)
            except Exception as e:
                print("  FAIL %s crashed on %s: %s" % (cid, what, e))
                ok = False
                continue
            failed = r.failed()
            if failed == [cid]:
                print("  ok    %s trips on %s" % (cid, what))
            else:
                print("  FAIL %s: %s tripped %s" % (cid, what,
                                                    failed or "nothing"))
                for row in r.rows:
                    if not row["pass"]:
                        print("        %s %s" % (row["id"], row["detail"]))
                ok = False
        # built-DEF faults, planted one at a time
        base = open(p).read()
        c3, c5, c7, c9, c11 = (cells[i] for i in (3, 5, 7, 9, 11))
        plants = (
            ("K14", base.replace("( %d %d )" % (c3["x"], c3["y"]),
                                 "( %d %d )" % (c3["x"] + 460, c3["y"]), 1)),
            ("K15", base.replace(") %s ;" % c5["orient"],
                                 ") %s ;" % FLIP[c5["orient"]], 1)),
            ("K13", base.replace("- %s " % escape(c7["inst"]), "- gone ", 1)),
            ("K16", base.replace("+ FIXED ( %d %d ) %s"
                                 % (c9["x"], c9["y"], c9["orient"]),
                                 "+ UNPLACED", 1)),
            ("K17", base.replace("%s + FIXED ( %d %d )"
                                 % (c11["master"], c11["x"], c11["y"]),
                                 "sky130_fd_sc_hd__inv_2 + FIXED ( %d %d )"
                                 % (c11["x"], c11["y"]), 1)))
        for cid, text in plants:
            q = os.path.join(tmp, cid + ".def")
            open(q, "w").write(text)
            r, _rep = verify_built(cells, q)
            if r.failed() == [cid]:
                print("  ok    %s trips on a built DEF with that fault" % cid)
            else:
                print("  FAIL %s on a built DEF tripped %s"
                      % (cid, r.failed()))
                ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", help="write the record here")
    ap.add_argument("--emit", help="directory to write %s into" % HOOK_NAME)
    ap.add_argument("--def", dest="def_path", default=DEF,
                    help="the frozen DEF the checks read")
    ap.add_argument("--hook", default=HOOK_DEST,
                    help="the %s the checks read back" % HOOK_NAME)
    ap.add_argument("--verify-def", help="a DEF a build wrote; report "
                    "whether Arm C stayed where this file put it; a glob "
                    "is accepted")
    ap.add_argument("--annotate", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="with --verify-def, exit 1 on any moved cell")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    template, chosen, layout = load_template(TEMPLATE)
    design = read_def(a.def_path)
    inv = n_inv(RTL)
    cells, geo = placements(template, layout, inv, design["units"])

    if a.verify_def:
        paths = sorted(glob.glob(a.verify_def)) or [a.verify_def]
        if not os.path.exists(paths[0]):
            print("no DEF at %s" % a.verify_def)
            if a.annotate:
                print("::error title=Arm C placement::no DEF at %s"
                      % a.verify_def)
            return 1 if a.strict else 0
        res, rep = verify_built(cells, paths[0])
        if a.annotate:
            annotate(res, rep)
        else:
            print("Arm C held %d of %d cells" % (rep["held"], rep["cells"]))
            for r in res.rows:
                print("  %s %-4s %s: %s" % ("pass" if r["pass"] else "FAIL",
                                            r["id"], r["name"], r["detail"]))
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump({"report": rep, "checks": res.rows}, fh,
                          indent=1, sort_keys=True)
                fh.write("\n")
        return 1 if (a.strict and res.failed()) else 0

    text = render_hook(cells)
    if a.emit:
        if not os.path.isdir(a.emit):
            os.makedirs(a.emit)
        out = os.path.join(a.emit, HOOK_NAME)
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("  wrote %s" % out)
    hook_text = open(a.hook, encoding="utf-8").read() \
        if os.path.exists(a.hook) else ""
    res = run_checks(template, chosen, layout, design, cells, geo,
                     macro_size(LEF, design["units"]),
                     json.load(open(CONFIG, encoding="utf-8")), hook_text,
                     open(WRAPPER, encoding="utf-8").read(),
                     open(ARMA_HOOK, encoding="utf-8").read(), inv)
    for r in res.rows:
        print("  %s %-4s %s" % ("pass" if r["pass"] else "FAIL", r["id"],
                                r["name"]))
        if not r["pass"]:
            print("            %s" % r["detail"])
    bad = res.failed()
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    if a.json:
        by_ring = collections.defaultdict(list)
        for c in sorted(cells, key=lambda c: (c["ring"], c["walk"])):
            by_ring[c["ring"]].append(
                {"cell": c["cell"], "row": c["row"], "col": c["col"],
                 "x_um": c["x"] / design["units"],
                 "y_um": c["y"] / design["units"], "orient": c["orient"]})
        out = {
            "_comment": [
                "Arm C's 512 cells set FIRM at step 21 from the chosen",
                "template layout. Written by chip/gen_armc_fix.py; the",
                "hook itself is dualarm/src/armc_fix.tcl, mirrored to",
                "src/. Nothing in this file is preregistered."],
            "written": "2026-09-16",
            "layout": chosen,
            "order": ORDER,
            "n_inv": inv,
            "cells": len(cells),
            "rings": len(by_ring),
            "template": geo,
            "hook": HOOK_NAME,
            "hook_sha256": (sha256_file(a.hook) if os.path.exists(a.hook)
                            else None),
            "source": {"template": sha256_file(TEMPLATE),
                       "def": sha256_file(a.def_path),
                       "rtl": sha256_file(RTL)},
            "ring_0": by_ring[min(by_ring)] if by_ring else [],
            "checks": res.rows,
        }
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
