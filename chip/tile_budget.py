#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Where every micron of the placed 2x2 die goes, and what is left for Arm C.

E.1 asks what a third layout treatment costs. Half of that question is how much
room there is, and the only answer on record was the comment above
`tiles: "2x2"` in `info.yaml`: sixteen 60x40 um macros on a 4x4 grid need
334.88 x 225.76 um. That says what the macros need. It says nothing about what
is left over, and the leftover is the number the Arm C decision turns on.

This reads the placed DEF of `dualarm/build_current` and answers it.

No cell widths come from a library file. The sky130 LEF is not in this
repository and adding a PDK to settle one arithmetic question is the wrong
trade, so every width is recovered from the placement itself: a legalized row
is packed edge to edge, so the distance from one cell's origin to the next
cell's origin is the left cell's width. Every master in this design abuts
something somewhere, so every width comes out.

Three things make the recovery trustworthy rather than convenient.

A master must never show two different widths across the abutments it takes
part in. Every row must be exactly full, first cell flush with the row origin
and last cell flush with the row end, no gap and no overlap between. And the
row site area must equal the area of the cells standing on it. Those are one
property seen three ways and they are one check here, because a fault in any of
them shows up in all three and a check that cannot be isolated is not a check.

The independent test is the total. Standard cells at row height, macros at the
height their own LEF declares, summed, must equal `design__instance__area` in
`metrics.json`. OpenLane wrote that number during the same run from its own
database, this script does not read it until the comparison, and the two agree
to within a rounding step.

The reclaimable/held split is the one judgement in the file and it is stated,
not derived. Filler and decap come out and go back around whatever is placed
instead. Taps do not: sky130 wants one within a fixed distance of every cell,
so the tap count follows the row area rather than the occupancy. Antenna diodes
stay. Logic and the Arm A rings stay by definition. Whether all of the decap is
really free is a power-integrity question this script cannot answer and does
not pretend to; see `docs/phaseE_tile_budget.md`.

Usage:
    python3 tile_budget.py --selftest
    python3 tile_budget.py
    python3 tile_budget.py --json /tmp/tile_budget.json
    python3 tile_budget.py --build ../dualarm/build_current

The archived answer is `TILE_BUDGET.json` beside this file. CI regenerates it
and diffs. That works here because, unlike Phase A, every input is committed.
"""

import argparse
import collections
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "dualarm", "build_current")

DESIGN = "tt_um_nikodemetrashvili20_ro_puf"
MACRO_MASTER = "ro_macro_hard"
CELL_PREFIX = "sky130_fd_sc_hd__"
ARM_A_PREFIX = "u_puf.u_core.g_ro_bank"

# The 2x2 claim in info.yaml, in microns. Checked against DIEAREA, not assumed.
TILE_2X2_UM = (334.88, 225.76)

# A standard Tiny Tapeout tile, from the same comment. Used only to express the
# die as a tile count. Nothing downstream depends on it.
TT_TILE_UM = (160.0, 100.0)

# Masters whose area a re-placement can take back. Everything else stays.
RECLAIMABLE = ("decap", "fill")

CLASSES = ("arma_ring", "armb_macro", "decap", "diode", "fill", "logic", "tap")


# ------------------------------------------------------------------ helpers

def sha256_file(path):
    """The bytes a checkout produces, not the bytes on this disk.

    `.gitattributes` opens with `* text=auto`, so git stores a text file
    with LF endings whatever the machine that wrote it used. Hash the raw
    bytes of a CRLF file and the number recorded is one CI can never
    reproduce. That is what put TILE_BUDGET.json's macro_lef entry wrong
    on 31 August and held the evidence gate red for five pushes.

    The test below is git's own and both halves of it matter: a NUL in
    the first 8000 bytes, or a carriage return with no line feed behind
    it, and git leaves the file alone. It reads no attributes, which is
    safe only while no explicit rule contradicts the heuristic, and that
    is what chip/hash_stability.py H03 and H04 are there to require."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if b"\x00" in blob[:8000] or blob.count(b"\r") != blob.count(b"\r\n"):
        return hashlib.sha256(blob).hexdigest()
    return hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()


def unescape(name):
    """The DEF escapes bracket characters one at a time, `g_ro_bank\\[0\\]`.
    The netlist escapes the whole identifier with a single leading backslash.
    Two conventions out of one flow. Drop the backslashes and they agree."""
    return name.replace("\\", "")


def um2(dbu_area, units):
    return dbu_area / float(units) / float(units)


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


# ------------------------------------------------------------------ parsing

Component = collections.namedtuple("Component", "inst master x y orient")
Row = collections.namedtuple("Row", "name site x y orient nsites step")

DIE_RE = re.compile(
    r"^DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*;",
    re.M)
UNITS_RE = re.compile(r"^UNITS DISTANCE MICRONS (\d+)\s*;", re.M)
ROW_RE = re.compile(
    r"^ROW\s+(\S+)\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\w+)\s+DO\s+(\d+)\s+BY\s+"
    r"(\d+)\s+STEP\s+(\d+)\s+(\d+)\s*;", re.M)
COMP_RE = re.compile(
    r"^\s*-\s+(\S+)\s+(\S+)\s+\+.*?\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)\s*;",
    re.M)
COMP_SECTION_RE = re.compile(r"^COMPONENTS (\d+) ;$(.*?)^END COMPONENTS",
                             re.S | re.M)


class Design(object):
    def __init__(self, units, die, rows, comps):
        self.units = units
        self.die = die
        self.rows = rows
        self.comps = comps
        ys = sorted(set(r.y for r in rows))
        gaps = sorted(set(b - a for a, b in zip(ys, ys[1:])))
        self.row_height = gaps[0] if gaps else 0
        self.row_ys = set(ys)

    @property
    def cells(self):
        return [c for c in self.comps if c.master != MACRO_MASTER]

    @property
    def macros(self):
        return [c for c in self.comps if c.master == MACRO_MASTER]

    @property
    def onrow(self):
        return [c for c in self.cells if c.y in self.row_ys]


def parse_def(text):
    """Read the parts of a DEF this needs. Not a general reader: it wants
    UNITS, DIEAREA, ROW and COMPONENTS, and it refuses a file missing any of
    them instead of carrying on with a default."""
    mu = UNITS_RE.search(text)
    if not mu:
        raise ValueError("no UNITS DISTANCE MICRONS line")
    md = DIE_RE.search(text)
    if not md:
        raise ValueError("no DIEAREA line")
    rows = [Row(g[0], g[1], int(g[2]), int(g[3]), g[4],
                int(g[5]) * int(g[6]), int(g[7])) for g in ROW_RE.findall(text)]
    if not rows:
        raise ValueError("no ROW records")
    ms = COMP_SECTION_RE.search(text)
    if not ms:
        raise ValueError("no COMPONENTS section")
    comps = [Component(g[0], g[1], int(g[2]), int(g[3]), g[4])
             for g in COMP_RE.findall(ms.group(2))]
    if not comps:
        raise ValueError("COMPONENTS section is empty")
    design = Design(int(mu.group(1)), tuple(int(g) for g in md.groups()),
                    rows, comps)
    return design, int(ms.group(1))


LEF_MACRO_RE = re.compile(r"MACRO\s+(\S+)(.*?)END\s+\1", re.S)
LEF_SIZE_RE = re.compile(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;")


def parse_macro_lef(text):
    """Only the SIZE of every MACRO block. The rest is pins and obstructions
    and nothing here needs them."""
    out = {}
    for name, body in LEF_MACRO_RE.findall(text):
        m = LEF_SIZE_RE.search(body)
        if m:
            out[name] = (float(m.group(1)), float(m.group(2)))
    return out


NL_INST_RE = re.compile(
    r"^\s*(sky130_fd_sc_hd__\S+|ro_macro_hard)\s+(\S+)\s*\(", re.M)


def parse_netlist_arms(text):
    """Arm A ring composition and Arm B macro instances from the gate-level
    netlist. The netlist is a second opinion on the DEF, written by the same
    flow into a different file under a different escaping convention. Where
    they disagree that is a check, never a merge."""
    rings = collections.defaultdict(collections.Counter)
    macros = []
    ring_re = re.compile(re.escape(ARM_A_PREFIX) + r"\[(\d+)\]")
    for master, name in NL_INST_RE.findall(text):
        clean = unescape(name)
        if master == MACRO_MASTER:
            macros.append(clean)
            continue
        m = ring_re.match(clean)
        if m:
            rings[int(m.group(1))][master[len(CELL_PREFIX):]] += 1
    return rings, macros


def parse_positions(text):
    lines = [l for l in text.replace("\r\n", "\n").split("\n") if l.strip()]
    head = [h.strip() for h in lines[0].split(",")]
    return head, [dict(zip(head, [p.strip() for p in l.split(",")]))
                  for l in lines[1:]]


# ------------------------------------------------- widths from the placement

def recover_widths(design):
    """Cell width from abutment. Returns (widths, ambiguous).

    Macros are excluded. They are not on rows, they are taller than a row, and
    the distance from a macro's origin to the next thing along is not its
    width. Their size comes from the LEF.
    """
    byrow = collections.defaultdict(list)
    for c in design.cells:
        byrow[c.y].append((c.x, c.master))
    seen = collections.defaultdict(set)
    for y in byrow:
        line = sorted(byrow[y])
        for i in range(len(line) - 1):
            gap = line[i + 1][0] - line[i][0]
            if gap > 0:
                seen[line[i][1]].add(gap)
    ambiguous = dict((m, sorted(g)) for m, g in seen.items() if len(g) > 1)
    return dict((m, min(g)) for m, g in seen.items()), ambiguous


def classify(master, inst):
    """One class per component, and the classes do not overlap.

    Order matters. The physical tests are on the master and the Arm A test is
    on the instance name; a filler is never inside a ring, so the physical
    tests run first and the name test only ever sees real logic.
    """
    if master == MACRO_MASTER:
        return "armb_macro"
    base = master[len(CELL_PREFIX):] if master.startswith(CELL_PREFIX) \
        else master
    for prefix, name in (("decap", "decap"), ("fill", "fill"),
                         ("tap", "tap"), ("diode", "diode")):
        if base.startswith(prefix):
            return name
    if unescape(inst).startswith(ARM_A_PREFIX):
        return "arma_ring"
    return "logic"


def def_ring_composition(design):
    """The same ring table the netlist gives, built from the DEF instead."""
    rings = collections.defaultdict(collections.Counter)
    ring_re = re.compile(re.escape(ARM_A_PREFIX) + r"\[(\d+)\]")
    for c in design.cells:
        clean = unescape(c.inst)
        m = ring_re.match(clean)
        if m:
            base = c.master[len(CELL_PREFIX):] \
                if c.master.startswith(CELL_PREFIX) else c.master
            rings[int(m.group(1))][base] += 1
    return rings


# -------------------------------------------------------------- the budget

def build_budget(design, widths, ambiguous, macro_size, declared, metrics,
                 nl_rings, nl_macros, positions, classifier=classify):
    res = Results()
    u = design.units
    dbu = float(u)
    rh = design.row_height

    # ---------------------------------------------------------- parse level
    res.add("T01", "component count agrees with the DEF header and metrics",
            len(design.comps) == declared
            == metrics.get("design__instance__count"),
            "%d parsed, %d declared, %s in metrics"
            % (len(design.comps), declared,
               metrics.get("design__instance__count")))

    strange = sorted(set(c.master for c in design.comps
                         if c.master != MACRO_MASTER
                         and not c.master.startswith(CELL_PREFIX)))
    res.add("T02", "every master is the declared macro or a sky130 hd cell",
            not strange, "unexpected: %s" % (", ".join(strange) or "none"))

    res.add("T03", "the DEF and the netlist hold the same number of macros",
            len(design.macros) == len(nl_macros),
            "%d in DEF, %d in netlist" % (len(design.macros), len(nl_macros)))

    # ------------------------------------------------------------- geometry
    offrow = [c for c in design.cells if c.y not in design.row_ys]
    res.add("T04", "every standard cell sits on a declared row",
            not offrow, "%d off-row: %s"
            % (len(offrow), ", ".join(c.inst for c in offrow[:3])))

    rows_by_y = collections.defaultdict(list)
    for r in design.rows:
        rows_by_y[r.y].append(r)
    misaligned = 0
    for c in design.onrow:
        for r in rows_by_y[c.y]:
            if r.x <= c.x < r.x + r.nsites * r.step:
                if (c.x - r.x) % r.step:
                    misaligned += 1
                break
    res.add("T05", "every standard cell is aligned to its row's site grid",
            misaligned == 0, "%d off the grid" % misaligned)

    # T06 is three statements of one property. A width that is ambiguous is a
    # row that does not pack; a row that does not pack has the wrong area. No
    # planted fault can separate them, so they are one check with one message.
    byrow = collections.defaultdict(list)
    for c in design.onrow:
        byrow[c.y].append((c.x, c.master))
    faults = []
    if ambiguous:
        faults.append("two widths for %s" % ", ".join(sorted(ambiguous))[:60])
    for r in design.rows:
        span = [p for p in sorted(byrow.get(r.y, []))
                if r.x <= p[0] < r.x + r.nsites * r.step]
        if not span:
            faults.append("%s empty" % r.name)
            continue
        if span[0][0] != r.x:
            faults.append("%s starts at %d not %d" % (r.name, span[0][0], r.x))
        end = span[-1][0] + widths.get(span[-1][1], 0)
        if end != r.x + r.nsites * r.step:
            faults.append("%s ends at %d not %d"
                          % (r.name, end, r.x + r.nsites * r.step))
        for i in range(len(span) - 1):
            if span[i][0] + widths.get(span[i][1], 0) != span[i + 1][0]:
                faults.append("%s breaks at %d" % (r.name, span[i][0]))
                break
    row_area = sum(r.nsites * r.step for r in design.rows) * rh
    onrow_area = sum(widths.get(c.master, 0) * rh for c in design.onrow)
    if row_area != onrow_area:
        faults.append("row area %d != cell area %d" % (row_area, onrow_area))
    res.add("T06", "rows pack flush: one width a master, no gap, area agrees",
            not faults, "%d fault(s): %s"
            % (len(faults), "; ".join(faults[:3]) or "none"))

    # ---------------------------------------------------------- the macros
    msize = macro_size.get(MACRO_MASTER)
    res.add("T07", "the macro LEF declares the 60 x 40 um cell info.yaml sizes",
            msize is not None and abs(msize[0] - 60.0) < 1e-9
            and abs(msize[1] - 40.0) < 1e-9, "LEF says %s" % (msize,))

    mw = int(round(msize[0] * u)) if msize else 0
    mh = int(round(msize[1] * u)) if msize else 0
    ms = design.macros
    overlaps = 0
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            a, b = ms[i], ms[j]
            if (a.x < b.x + mw and b.x < a.x + mw
                    and a.y < b.y + mh and b.y < a.y + mh):
                overlaps += 1
    res.add("T08", "no two macros overlap", overlaps == 0,
            "%d overlapping pairs" % overlaps)

    row_hits = 0
    for m in ms:
        for r in design.rows:
            if (m.x < r.x + r.nsites * r.step and r.x < m.x + mw
                    and m.y < r.y + rh and r.y < m.y + mh):
                row_hits += 1
    res.add("T09", "no macro sits on a row span", row_hits == 0,
            "%d macro/row overlaps" % row_hits)

    x0, y0, x1, y1 = design.die
    outside = []
    for c in design.comps:
        w = mw if c.master == MACRO_MASTER else widths.get(c.master, 0)
        h = mh if c.master == MACRO_MASTER else rh
        if c.x < x0 or c.y < y0 or c.x + w > x1 or c.y + h > y1:
            outside.append(c.inst)
    res.add("T10", "everything placed is inside DIEAREA", not outside,
            "%d outside: %s" % (len(outside), ", ".join(outside[:3])))

    die_um = ((x1 - x0) / dbu, (y1 - y0) / dbu)
    res.add("T11", "die size is the 2x2 figure info.yaml claims",
            abs(die_um[0] - TILE_2X2_UM[0]) < 1e-6
            and abs(die_um[1] - TILE_2X2_UM[1]) < 1e-6,
            "%.2f x %.2f um" % die_um)

    # ------------------------------------------------------------- the area
    n_by_class = collections.Counter()
    a_by_class = collections.Counter()
    for c in design.comps:
        k = classifier(c.master, c.inst)
        n_by_class[k] += 1
        a_by_class[k] += (mw * mh if k == "armb_macro"
                          else widths.get(c.master, 0) * rh)

    total_a = um2(sum(a_by_class.values()), u)
    res.add("T12", "placed area equals design__instance__area in metrics",
            abs(total_a - metrics.get("design__instance__area", -1)) < 0.05,
            "%.1f here, %s in metrics"
            % (total_a, metrics.get("design__instance__area")))

    # T13 cannot be tripped by any input file: classify returns a name from
    # CLASSES for every master it is given. It guards the classifier, so the
    # selftest trips it from the other side, by patching classify itself.
    res.add("T13", "the classes partition every component exactly once",
            sum(n_by_class.values()) == len(design.comps)
            and set(n_by_class) <= set(CLASSES),
            "%d of %d in %s" % (sum(n_by_class.values()), len(design.comps),
                                ",".join(sorted(n_by_class))))

    # --------------------------------------------------------- the two arms
    def_rings = def_ring_composition(design)
    same = (set(def_rings) == set(nl_rings)
            and all(def_rings[k] == nl_rings[k] for k in def_rings))
    shapes = set(tuple(sorted(c.items())) for c in def_rings.values())
    res.add("T14", "the DEF and the netlist agree on every Arm A ring",
            bool(def_rings) and same and len(shapes) == 1,
            "%d rings, %d shape(s), netlist %s"
            % (len(def_rings), len(shapes),
               "agrees" if same else "disagrees"))

    per_ring = sum(dict(list(shapes)[0]).values()) if shapes else 0
    _, prows = positions
    ok_pos = (len(prows) == len(def_rings)
              and all(p.get("ncells") == str(per_ring) for p in prows)
              and sorted(int(p["ro"]) for p in prows)
              == list(range(len(def_rings))))
    res.add("T15", "the positions CSV agrees with the DEF about the rings",
            ok_pos, "%d rows, ncells %s"
            % (len(prows), ",".join(sorted(set(p.get("ncells", "?")
                                               for p in prows)))))

    mxs = sorted(set(m.x for m in ms))
    mys = sorted(set(m.y for m in ms))
    grid = set((x, y) for x in mxs for y in mys)
    pitch_x = set(b - a for a, b in zip(mxs, mxs[1:]))
    pitch_y = set(b - a for a, b in zip(mys, mys[1:]))
    res.add("T16", "the Arm B macros are a 4x4 grid at one pitch",
            len(mxs) == 4 and len(mys) == 4 and len(pitch_x) == 1
            and len(pitch_y) == 1
            and set((m.x, m.y) for m in ms) == grid,
            "%d x by %d y, pitch %s / %s"
            % (len(mxs), len(mys),
               [p / dbu for p in pitch_x], [p / dbu for p in pitch_y]))

    # ------------------------------------------------------------ reporting
    free_dbu = sum(a_by_class[k] for k in RECLAIMABLE)
    held_dbu = onrow_area - free_dbu
    band_sites = max(r.nsites for r in design.rows)
    band_ys = set(r.y for r in design.rows if r.nsites == band_sites)

    regions = {"band": collections.Counter(), "strip": collections.Counter()}
    for c in design.onrow:
        where = "band" if c.y in band_ys else "strip"
        regions[where][classifier(c.master, c.inst)] += \
            widths.get(c.master, 0) * rh

    def region_block(name):
        got = regions[name]
        free = sum(got[k] for k in RECLAIMABLE)
        tot = sum(got.values())
        return {"rows": len([r for r in design.rows
                             if (r.y in band_ys) == (name == "band")]),
                "row_area_um2": round(um2(tot, u), 3),
                "free_um2": round(um2(free, u), 3),
                "held_um2": round(um2(tot - free, u), 3),
                "by_class_um2": dict((k, round(um2(v, u), 3))
                                     for k, v in sorted(got.items()))}

    arma = [c for c in design.cells
            if unescape(c.inst).startswith(ARM_A_PREFIX)]
    die_area = (x1 - x0) * (y1 - y0)
    macro_right = max((m.x + mw for m in ms), default=0)

    # The die is not rows plus macros. What is left over is the channel the
    # 48 um macro pitch leaves under a 40 um macro, plus the margin between
    # the outermost row or macro and the die edge.
    #
    # The macro block's bounding box is a construction, not an object, and a
    # row can run straight through it. One does: ROW_22 sits in the 8 um gap
    # between the second and third rows of macros and crosses the whole
    # block, 240.0 by 2.72 um. Charging that area to the channel and to the
    # rows at once counts it twice, which is what the first version of this
    # did, so the overlap is measured and subtracted.
    #
    # The margin is a residual and cannot be anything else, so the four
    # figures adding to the die is true by construction and is not evidence.
    # What makes the split real is T09, which requires that no macro overlaps
    # any row, and this number being reported rather than assumed zero.
    block = (min(m.x for m in ms), min(m.y for m in ms),
             macro_right, max(m.y for m in ms) + mh) if ms else (0, 0, 0, 0)
    block_area = (block[2] - block[0]) * (block[3] - block[1])
    rows_in_block = 0
    for r in design.rows:
        ox = max(0, min(r.x + r.nsites * r.step, block[2]) - max(r.x, block[0]))
        oy = max(0, min(r.y + rh, block[3]) - max(r.y, block[1]))
        rows_in_block += ox * oy
    channels = block_area - a_by_class["armb_macro"] - rows_in_block
    margin = die_area - block_area - (row_area - rows_in_block)

    budget = {
        "design": DESIGN,
        "die": {"width_um": round(die_um[0], 3),
                "height_um": round(die_um[1], 3),
                "area_um2": round(um2(die_area, u), 3),
                "standard_tiles_wide": round(die_um[0] / TT_TILE_UM[0], 3),
                "standard_tiles_tall": round(die_um[1] / TT_TILE_UM[1], 3)},
        "rows": {"count": len(design.rows),
                 "height_um": round(rh / dbu, 3),
                 "site_width_um": round(design.rows[0].step / dbu, 3),
                 "sites": sum(r.nsites for r in design.rows),
                 "area_um2": round(um2(row_area, u), 3),
                 "fraction_of_die": round(row_area / float(die_area), 5)},
        "macros": {"count": len(ms),
                   "width_um": msize[0] if msize else None,
                   "height_um": msize[1] if msize else None,
                   "area_um2": round(um2(a_by_class["armb_macro"], u), 3),
                   "fraction_of_die": round(
                       a_by_class["armb_macro"] / float(die_area), 5),
                   "right_edge_um": round(macro_right / dbu, 3),
                   "block_bbox_um": [round(v / dbu, 3) for v in block],
                   "block_channel_um2": round(um2(channels, u), 3)},
        "unplaceable": {"macro_block_channels_um2": round(um2(channels, u), 3),
                        "die_margin_um2": round(um2(margin, u), 3),
                        "row_area_inside_macro_block_um2": round(
                            um2(rows_in_block, u), 3),
                        "fraction_of_die": round(
                            (channels + margin) / float(die_area), 5)},
        "placed": {"instances": len(design.comps),
                   "area_um2": round(total_a, 3),
                   "by_class": dict(
                       (k, {"count": n_by_class[k],
                            "area_um2": round(um2(a_by_class[k], u), 3)})
                       for k in sorted(n_by_class))},
        "free": {"reclaimable_classes": list(RECLAIMABLE),
                 "area_um2": round(um2(free_dbu, u), 3),
                 "held_area_um2": round(um2(held_dbu, u), 3),
                 "fraction_of_row_area": round(free_dbu / float(row_area), 5),
                 "fraction_of_die": round(free_dbu / float(die_area), 5),
                 "by_region": dict((r, region_block(r))
                                   for r in ("band", "strip"))},
        "arm_a": {"rings": len(def_rings),
                  "cells_per_ring": per_ring,
                  "composition": dict(sorted(list(shapes)[0]))
                  if shapes else {},
                  "area_um2": round(um2(a_by_class["arma_ring"], u), 3),
                  "area_per_ring_um2": round(
                      um2(a_by_class["arma_ring"], u)
                      / max(len(def_rings), 1), 4),
                  "bbox_um": [round(min(c.x for c in arma) / dbu, 3),
                              round(min(c.y for c in arma) / dbu, 3),
                              round(max(c.x + widths.get(c.master, 0)
                                        for c in arma) / dbu, 3),
                              round((max(c.y for c in arma) + rh) / dbu, 3)]
                  if arma else None,
                  "clear_of_macros": bool(arma) and
                  min(c.x for c in arma) >= macro_right},
        "checks": res.rows,
    }
    return budget, res


# ------------------------------------------------------------------ fixture

# A miniature of the real design rather than a toy: the real site width, the
# real row height, the real die, the real 4x4 macro grid at the real pitch,
# and four rows in the strip beside it. Every check that is a statement about
# this design's shape can therefore be exercised, and nothing has to be
# excused on the grounds that the fixture is not the real thing.

FX_UNITS = 1000
FX_SITE = 460
FX_RH = 2720
FX_SITES = 24                       # 24 * 460 = 11040 dbu a row
FX_ROW_Y = [2720, 5440, 8160, 10880]
FX_ROW_X = 245640
FX_MACRO_X = [3220, 63220, 123220, 183220]
FX_MACRO_Y = [20000, 68000, 116000, 164000]

W_INV, W_NAND, W_BUF, W_DECAP = 1380, 1380, 1380, 1380
W_FILL, W_DIODE, W_TAP = 920, 920, 460


def _cell(name, base):
    return CELL_PREFIX + base, name


def fixture_rows():
    """Four rows, each exactly 11040 dbu wide. Every master abuts something to
    its right somewhere, or its width could not be recovered at all."""
    inv, nand, buf = "inv_1", "nand2_1", "buf_1"
    dec, fil, dio, tap = "decap_3", "fill_2", "diode_2", "tapvpwrvgnd_1"
    # The buffer sits in the middle rather than at the end. It is the only
    # buf_1 in the fixture, and a master that ends a row and appears nowhere
    # else abuts nothing, so its width could never be recovered.
    ring = [("%s[0].u_ro.u_nand" % ARM_A_PREFIX, nand)]
    ring += [("%s[0].u_ro.g_inv[%d].u_inv" % (ARM_A_PREFIX, i), inv)
             for i in range(1, 4)]
    ring += [("%s[0].u_ro.u_buf" % ARM_A_PREFIX, buf)]
    ring += [("%s[0].u_ro.g_inv[%d].u_inv" % (ARM_A_PREFIX, i), inv)
             for i in range(4, 7)]
    r1 = [("logic_1_0", inv), ("TAP_1_1", tap), ("logic_1_2", inv),
          ("FILLER_1_3", fil), ("logic_1_4", inv), ("TAP_1_5", tap),
          ("logic_1_6", inv), ("FILLER_1_7", fil), ("logic_1_8", inv),
          ("logic_1_9", inv)]
    r2 = [("FILLER_2_0", dec), ("TAP_2_1", tap), ("FILLER_2_2", dec),
          ("FILLER_2_3", dec), ("ANTENNA_2_4", dio), ("FILLER_2_5", dec),
          ("TAP_2_6", tap), ("FILLER_2_7", dec), ("FILLER_2_8", dec),
          ("FILLER_2_9", fil)]
    r3 = [("FILLER_3_0", dec), ("FILLER_3_1", dec), ("FILLER_3_2", dec),
          ("TAP_3_3", tap), ("FILLER_3_4", dec), ("FILLER_3_5", dec),
          ("FILLER_3_6", dec), ("FILLER_3_7", dec), ("FILLER_3_8", fil)]
    return [ring, r1, r2, r3]


def make_fixture():
    width = {"inv_1": W_INV, "nand2_1": W_NAND, "buf_1": W_BUF,
             "decap_3": W_DECAP, "fill_2": W_FILL, "diode_2": W_DIODE,
             "tapvpwrvgnd_1": W_TAP}
    lines = ["VERSION 5.8 ;", 'DIVIDERCHAR "/" ;', 'BUSBITCHARS "[]" ;',
             "DESIGN fixture ;",
             "UNITS DISTANCE MICRONS %d ;" % FX_UNITS,
             "DIEAREA ( 0 0 ) ( %d %d ) ;"
             % (int(TILE_2X2_UM[0] * FX_UNITS), int(TILE_2X2_UM[1] * FX_UNITS))]
    for i, y in enumerate(FX_ROW_Y):
        lines.append("ROW ROW_%d unithd %d %d N DO %d BY 1 STEP %d 0 ;"
                     % (i, FX_ROW_X, y, FX_SITES, FX_SITE))
    comps = []
    for ri, row in enumerate(fixture_rows()):
        x = FX_ROW_X
        for name, base in row:
            escaped = name.replace("[", "\\[").replace("]", "\\]")
            comps.append("    - %s %s%s + PLACED ( %d %d ) N ;"
                         % (escaped, CELL_PREFIX, base, x, FX_ROW_Y[ri]))
            x += width[base]
        assert x == FX_ROW_X + FX_SITES * FX_SITE, (ri, x)
    n = 0
    for y in FX_MACRO_Y:
        for x in FX_MACRO_X:
            comps.append("    - u_rob%d %s + FIXED ( %d %d ) N ;"
                         % (n, MACRO_MASTER, x, y))
            n += 1
    lines.append("COMPONENTS %d ;" % len(comps))
    lines.extend(comps)
    lines.append("END COMPONENTS")
    lines.append("END DESIGN")
    return "\n".join(lines) + "\n"


FIXTURE_LEF = """VERSION 5.7 ;
MACRO ro_macro_hard
  CLASS BLOCK ;
  SIZE 60.000 BY 40.000 ;
END ro_macro_hard
END LIBRARY
"""


def fixture_netlist():
    out = ["module fixture (clk);"]
    out.append("  %snand2_1 \\%s[0].u_ro.u_nand (.A(a), .Y(y));"
               % (CELL_PREFIX, ARM_A_PREFIX))
    for i in range(1, 7):
        out.append("  %sinv_1 \\%s[0].u_ro.g_inv[%d].u_inv (.A(a), .Y(y));"
                   % (CELL_PREFIX, ARM_A_PREFIX, i))
    out.append("  %sbuf_1 \\%s[0].u_ro.u_buf (.A(a), .X(y));"
               % (CELL_PREFIX, ARM_A_PREFIX))
    for n in range(16):
        out.append("  %s u_rob%d (.en(e), .out(o));" % (MACRO_MASTER, n))
    out.append("endmodule")
    return "\n".join(out) + "\n"


FIXTURE_POS = "ro,x_um,y_um,ncells,ring_cap_fF\n0,250.0,3.0,8,10.00\n"


def fixture_metrics(deftext, leftext):
    """What metrics.json would say about this fixture, worked out the long way
    so the fixture cannot quietly disagree with itself. Faults that change the
    DEF or the LEF call this again, which is what keeps T01 and T12 clean while
    some other check is the one under test."""
    design, _ = parse_def(deftext)
    widths, _ = recover_widths(design)
    size = parse_macro_lef(leftext)[MACRO_MASTER]
    a = 0
    for c in design.comps:
        if c.master == MACRO_MASTER:
            a += int(round(size[0] * design.units)) \
                * int(round(size[1] * design.units))
        else:
            a += widths.get(c.master, 0) * design.row_height
    return {"design__instance__count": len(design.comps),
            "design__instance__area": round(um2(a, design.units), 1)}


def run_fixture(deftext, leftext, nltext, postext, metrics,
                classifier=classify):
    design, declared = parse_def(deftext)
    widths, ambiguous = recover_widths(design)
    rings, nlmacros = parse_netlist_arms(nltext)
    return build_budget(design, widths, ambiguous, parse_macro_lef(leftext),
                        declared, metrics, rings, nlmacros,
                        parse_positions(postext), classifier=classifier)


# ------------------------------------------------------------------- faults

def _renumber(deftext):
    n = len(re.findall(r"^    - ", deftext, re.M))
    return re.sub(r"^COMPONENTS \d+ ;$", "COMPONENTS %d ;" % n, deftext,
                  count=1, flags=re.M)


def f_count(d, l, n, p, m, c):
    m = dict(m)
    m["design__instance__count"] += 1
    return d, l, n, p, m, c


def f_foreign_master(d, l, n, p, m, c):
    # A master from somewhere that is not the sky130 hd library. It keeps its
    # neighbours, so its width is still recovered and the row still packs.
    return (d.replace("FILLER_3_0 sky130_fd_sc_hd__decap_3",
                      "FILLER_3_0 acme_hd__decap_3", 1), l, n, p, m, c)


def f_netlist_macro(d, l, n, p, m, c):
    return d, l, n.replace("  ro_macro_hard u_rob15", "  // u_rob15", 1), \
        p, m, c


def f_offrow(d, l, n, p, m, c):
    # A cell parked between the rows and the macro band. It breaks no row.
    extra = d.replace("END COMPONENTS",
                      "    - STRAY_1 %sfill_2 + PLACED ( %d 15000 ) N ;\n"
                      "END COMPONENTS" % (CELL_PREFIX, FX_ROW_X))
    extra = _renumber(extra)
    return extra, l, n, p, fixture_metrics(extra, l), c


def f_site_grid(d, l, n, p, m, c):
    # Same span, finer site. 24 x 460 becomes 30 x 368, so the row area is
    # untouched and every cell is suddenly off the grid.
    return (d.replace("ROW ROW_1 unithd %d 5440 N DO 24 BY 1 STEP 460 0 ;"
                      % FX_ROW_X,
                      "ROW ROW_1 unithd %d 5440 N DO 30 BY 1 STEP 368 0 ;"
                      % FX_ROW_X, 1), l, n, p, m, c)


def f_row_short(d, l, n, p, m, c):
    out = [line for line in d.split("\n") if "FILLER_3_8" not in line]
    txt = _renumber("\n".join(out))
    return txt, l, n, p, fixture_metrics(txt, l), c


def f_lef_size(d, l, n, p, m, c):
    # Height, not width. A wider macro would also overlap its neighbour and
    # trip T08, and a fault that trips two checks tells you nothing.
    l2 = l.replace("SIZE 60.000 BY 40.000", "SIZE 60.000 BY 41.000")
    return d, l2, n, p, fixture_metrics(d, l2), c


def f_macro_overlap(d, l, n, p, m, c):
    # A seventeenth macro on top of the first, in the DEF and the netlist, at
    # a position already in the grid so the grid check still holds.
    d2 = _renumber(d.replace(
        "END COMPONENTS",
        "    - u_robx %s + FIXED ( %d %d ) N ;\nEND COMPONENTS"
        % (MACRO_MASTER, FX_MACRO_X[0], FX_MACRO_Y[0])))
    n2 = n.replace("endmodule",
                   "  %s u_robx (.en(e), .out(o));\nendmodule" % MACRO_MASTER)
    return d2, l, n2, p, fixture_metrics(d2, l), c


def f_macro_on_row(d, l, n, p, m, c):
    # Slide the whole array right and down until its corner lands on the rows.
    # Moving one macro would break the grid check as well.
    d2 = d
    for i, x in enumerate(FX_MACRO_X):
        d2 = d2.replace("FIXED ( %d " % x, "FIXED ( %d " % (x + 62420))
    for y in FX_MACRO_Y:
        d2 = d2.replace(" %d ) N ;" % y, " %d ) N ;" % (y - 17280))
    return d2, l, n, p, m, c


def f_outside_die(d, l, n, p, m, c):
    d2 = d
    for x in reversed(FX_MACRO_X):
        d2 = d2.replace("FIXED ( %d " % x, "FIXED ( %d " % (x + 100000))
    return d2, l, n, p, m, c


def f_die_size(d, l, n, p, m, c):
    # Bigger, not smaller. A smaller die would also push things outside it.
    return (d.replace("DIEAREA ( 0 0 ) ( 334880 225760 ) ;",
                      "DIEAREA ( 0 0 ) ( 400000 300000 ) ;", 1),
            l, n, p, m, c)


def f_area(d, l, n, p, m, c):
    m = dict(m)
    m["design__instance__area"] = round(m["design__instance__area"] + 1.0, 1)
    return d, l, n, p, m, c


def f_classifier(d, l, n, p, m, c):
    def broken(master, inst):
        if master.endswith("diode_2"):
            return "mystery"
        return classify(master, inst)
    return d, l, n, p, m, broken


def f_ring_shape(d, l, n, p, m, c):
    # The composition is counted by master, not by instance name, so the
    # fault has to change a master. One inverter in the netlist grows a drive
    # strength the DEF never placed.
    return d, l, n.replace("%sinv_1 \\%s[0].u_ro.g_inv[6]"
                           % (CELL_PREFIX, ARM_A_PREFIX),
                           "%sinv_2 \\%s[0].u_ro.g_inv[6]"
                           % (CELL_PREFIX, ARM_A_PREFIX), 1), p, m, c


def f_positions(d, l, n, p, m, c):
    return d, l, n, p.replace(",8,10.00", ",9,10.00", 1), m, c


def f_macro_grid(d, l, n, p, m, c):
    # One macro nudged off the lattice. It overlaps nothing and stays on no
    # row, so the grid check is the only thing that can see it.
    return (d.replace("u_rob15 %s + FIXED ( %d %d )"
                      % (MACRO_MASTER, FX_MACRO_X[3], FX_MACRO_Y[3]),
                      "u_rob15 %s + FIXED ( %d %d )"
                      % (MACRO_MASTER, FX_MACRO_X[3] + 500, FX_MACRO_Y[3]), 1),
            l, n, p, m, c)


FAULTS = [
    ("T01", "metrics disagrees about the instance count", f_count),
    ("T02", "a master from another library", f_foreign_master),
    ("T03", "the netlist lost a macro", f_netlist_macro),
    ("T04", "a cell parked between the rows and the macros", f_offrow),
    ("T05", "the same row span cut on a finer site", f_site_grid),
    ("T06", "a row left short at the right end", f_row_short),
    ("T07", "the macro LEF declares a taller cell", f_lef_size),
    ("T08", "a seventeenth macro on top of the first", f_macro_overlap),
    ("T09", "the macro array slid onto the rows", f_macro_on_row),
    ("T10", "the macro array slid off the die", f_outside_die),
    ("T11", "a die that is not the 2x2 figure", f_die_size),
    ("T12", "metrics disagrees about the placed area", f_area),
    ("T13", "a classifier that invents a class", f_classifier),
    ("T14", "a ring the netlist and the DEF describe differently",
     f_ring_shape),
    ("T15", "the positions CSV disagrees about cells a ring", f_positions),
    ("T16", "one macro nudged off the lattice", f_macro_grid),
]


def selftest():
    base = (make_fixture(), FIXTURE_LEF, fixture_netlist(), FIXTURE_POS)
    metrics = fixture_metrics(base[0], base[1])
    print("tile_budget selftest")
    print("  fixture: %d rows of %d sites in the strip, a 4x4 macro grid, "
          "%d components" % (len(FX_ROW_Y), FX_SITES,
                             metrics["design__instance__count"]))

    _, res = run_fixture(base[0], base[1], base[2], base[3], metrics)
    ok = True
    if res.failed():
        print("  FAIL: the clean fixture already fails %s"
              % ", ".join(res.failed()))
        for r in res.rows:
            if not r["pass"]:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  clean fixture passes all %d checks" % len(res.rows))

    for want, label, fn in FAULTS:
        d, l, n, p, m, c = fn(base[0], base[1], base[2], base[3], metrics,
                              classify)
        try:
            _, r2 = run_fixture(d, l, n, p, m, classifier=c)
            tripped = set(r2.failed())
        except Exception as exc:
            tripped = {"parse(%s)" % exc}
        if tripped == {want}:
            print("  ok    %-4s %s" % (want, label))
        elif want in tripped:
            print("  FAIL  %-4s %s -- also tripped %s"
                  % (want, label, ", ".join(sorted(tripped - {want}))))
            ok = False
        else:
            print("  FAIL  %-4s %s -- tripped %s"
                  % (want, label, ", ".join(sorted(tripped)) or "nothing"))
            ok = False

    for label, broken in (("no DIEAREA", base[0].replace("DIEAREA", "XXX")),
                          ("no ROW records",
                           re.sub(r"^ROW .*$", "", base[0], flags=re.M)),
                          ("an empty COMPONENTS section",
                           re.sub(r"^    - .*$", "", base[0], flags=re.M))):
        try:
            parse_def(broken)
            print("  FAIL  parse accepted a DEF with %s" % label)
            ok = False
        except ValueError:
            print("  ok    parse refuses a DEF with %s" % label)

    print("\n  %s" % ("all %d faults isolated" % len(FAULTS) if ok
                      else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------- main

def load_build(build):
    paths = {
        "def": os.path.join(build, DESIGN + ".def"),
        "netlist": os.path.join(build, DESIGN + ".nl.v"),
        "metrics": os.path.join(build, "metrics.json"),
        "positions": os.path.join(build, "dualarm_positions.csv"),
        "macro_lef": os.path.join(ROOT, "dualarm", "src",
                                  MACRO_MASTER + ".lef"),
    }
    for p in paths.values():
        if not os.path.exists(p):
            raise SystemExit("missing input: %s" % p)
    with open(paths["def"], "r", encoding="utf-8") as fh:
        design, declared = parse_def(fh.read())
    with open(paths["macro_lef"], "r", encoding="utf-8") as fh:
        sizes = parse_macro_lef(fh.read())
    with open(paths["netlist"], "r", encoding="utf-8") as fh:
        rings, nlmacros = parse_netlist_arms(fh.read())
    with open(paths["metrics"], "r", encoding="utf-8") as fh:
        metrics = json.load(fh)
    with open(paths["positions"], "r", encoding="utf-8") as fh:
        positions = parse_positions(fh.read())
    widths, ambiguous = recover_widths(design)
    hashes = dict((k, sha256_file(v)) for k, v in sorted(paths.items()))
    return (design, widths, ambiguous, sizes, declared, metrics, rings,
            nlmacros, positions, hashes)


def report(b, res):
    print("Tile budget for %s" % b["design"])
    print("  die            %.2f x %.2f um = %.1f um2 (%.2f x %.2f standard "
          "tiles)" % (b["die"]["width_um"], b["die"]["height_um"],
                      b["die"]["area_um2"], b["die"]["standard_tiles_wide"],
                      b["die"]["standard_tiles_tall"]))
    print("  Arm B macros   %d at %g x %g um = %.1f um2 (%.1f%% of the die)"
          % (b["macros"]["count"], b["macros"]["width_um"],
             b["macros"]["height_um"], b["macros"]["area_um2"],
             100 * b["macros"]["fraction_of_die"]))
    print("  placeable rows %d rows, %d sites = %.1f um2 (%.1f%% of the die)"
          % (b["rows"]["count"], b["rows"]["sites"], b["rows"]["area_um2"],
             100 * b["rows"]["fraction_of_die"]))
    print()
    print("  %-11s %7s %12s" % ("class", "count", "area um2"))
    for k in sorted(b["placed"]["by_class"]):
        v = b["placed"]["by_class"][k]
        print("  %-11s %7d %12.1f%s"
              % (k, v["count"], v["area_um2"],
                 "   reclaimable" if k in RECLAIMABLE else ""))
    print("  %-11s %7d %12.1f" % ("total", b["placed"]["instances"],
                                  b["placed"]["area_um2"]))
    print()
    print("  free for a third arm  %.1f um2, %.1f%% of the row area and "
          "%.1f%% of the die" % (b["free"]["area_um2"],
                                 100 * b["free"]["fraction_of_row_area"],
                                 100 * b["free"]["fraction_of_die"]))
    for r in ("band", "strip"):
        g = b["free"]["by_region"][r]
        print("    %-5s %2d rows  %8.1f um2 free of %8.1f um2"
              % (r, g["rows"], g["free_um2"], g["row_area_um2"]))
    print()
    a = b["arm_a"]
    print("  Arm A  %d rings of %d cells (%s)"
          % (a["rings"], a["cells_per_ring"],
             " + ".join("%d %s" % (v, k)
                        for k, v in sorted(a["composition"].items()))))
    print("         %.1f um2 in all, %.2f um2 a ring, %s the macro block"
          % (a["area_um2"], a["area_per_ring_um2"],
             "clear of" if a["clear_of_macros"] else "OVERLAPPING"))
    print()
    for r in res.rows:
        print("  %-4s %-60s %s" % (r["id"], r["name"],
                                   "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    for r in res.rows:
        if not r["pass"]:
            print("       %s: %s" % (r["id"], r["detail"]))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", default=BUILD,
                    help="build directory (default dualarm/build_current)")
    ap.add_argument("--json", help="write the budget to this path")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    (design, widths, ambiguous, sizes, declared, metrics, rings, nlmacros,
     positions, hashes) = load_build(a.build)
    budget, res = build_budget(design, widths, ambiguous, sizes, declared,
                               metrics, rings, nlmacros, positions)
    budget["source"] = {
        "build": os.path.relpath(a.build, ROOT).replace(os.sep, "/"),
        "sha256": hashes,
    }
    rc = report(budget, res)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(budget, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())
