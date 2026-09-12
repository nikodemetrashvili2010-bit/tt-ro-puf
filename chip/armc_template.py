#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The hand-placed Arm C: scored against the frozen rule, and where one
template of thirty-two cells could actually go.

G.2's amendment (chip/G2_AMENDMENT.json, 7 September) chose to place all
512 Arm C cells from one template, fixed by hand, routing left free. It
said two things had to happen before that is built: the option has to be
scored against H1 to H6 in G2_CRITERIA.json, and the flow has to be shown
to hold standard cells FIRM. Run 80 (12 September) held all 512 Arm A
cells through src/pdn_hook.tcl, so the second is answered. This script is
the first.

It also asks a question chip/gen_armc.py did not have to ask. Its sixteen
regions in ARMC_REGIONS.json were drawn for a placer that would work round
the well taps inside each one. A template placed FIRM at step 21 arrives
after the taps are in (step 19) and cannot work round anything: a template
cell on a tap site is an overlap the legalizer refuses. So every region has
to see its taps at the same offsets, and this script reads the frozen DEF
to find out whether the recorded regions do (they do not) and where
regions that do would sit.

What it decides and what it does not. The template geometry is derived:
one tap pitch wide, four rows tall, two sites held free for the taps, the
ring's cells packed between them. Two layouts are enumerated, one with
every region in the column beside Arm A and one split across the die the
way gen_armc.py split them, because chip/G2_AMENDMENT.json and
docs/phaseG_design_audit.md pull in opposite directions on that. The
column is chosen, by CHOSEN_LAYOUT below, and the grounds are in the
amendment rather than here because the decision is a G.2 matter and not
a geometric one. Nothing here is read by the build.
gen_placement_cfg.py still emits no Arm C line.

Usage:
    python3 armc_template.py --selftest
    python3 armc_template.py
    python3 armc_template.py --json /tmp/armc_template.json
"""

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEF = os.path.join(ROOT, "dualarm", "build_current",
                   "tt_um_nikodemetrashvili20_ro_puf.def")
CRITERIA = os.path.join(HERE, "G2_CRITERIA.json")
COST = os.path.join(HERE, "ARMC_COST.json")
REGIONS = os.path.join(HERE, "ARMC_REGIONS.json")
CONFIG = os.path.join(ROOT, "dualarm", "src", "config.json")

# SHA-256 of G2_CRITERIA.json as frozen on 2026-08-27, the same constant
# g2_decision.py carries. The rule is not re-read from that script.
FROZEN_SHA256 = \
    "c4e3d3049d0e99b21974bf77413c83a7da90a3a5c18a61bafad5079757a62c77"

# The one input that is an estimate. The frozen rule priced the original
# Arm C at four days (two of constraint writing, two of iteration) and the
# ladder at two. This is written on 12 September, after the mechanism was
# proven on Arm A, and it is not frozen: it rests on what the hook build
# took on the 11th. It was 3 in the first version of this file and is 4
# because the cell order inside the template has never been checked
# against a routed ring, and that is a plausible second build rather than
# a remote one.
BUILD_DAYS = 4
BUILD_DAYS_BASIS = (
    "One day to extend gen_placement_cfg.py so it emits the 512 Arm C "
    "lines into the same hook from the chosen layout, with the checker "
    "and the ring walk reading both arms. One build. Two days held back "
    "because the order of the 32 cells inside the template is a default "
    "nothing has checked against a routed ring, and a congested or "
    "badly ordered template costs a rebuild. Arm A's hook took one day "
    "on 11 September and held on its first run, but its coordinates came "
    "from a build that had already routed.")

# Which of the two layouts the build should use. Chosen 2026-09-12, the
# same day both were enumerated, by the session at Nikoloz's explicit
# delegation ("you choose best choice"). It is NOT part of the frozen
# G.2 rule and must never be cited as preregistered; the reasoning and
# what it costs are in chip/G2_AMENDMENT.json under resolution, and in
# docs/phaseG_run80.md.
CHOSEN_LAYOUT = "column"

ROWS_TALL = 4
ARM_A_PREFIX = "u_puf.u_core.g_ro_bank"
TAP_MASTER = "sky130_fd_sc_hd__tapvpwrvgnd_1"
ENDCAP_PREFIX = "PHY_"
TEMPLATE_ORIENT = "FS"     # the row Arm A's bottom ring cell sits on
BOX_KEY = "PL_SOFT_OBSTRUCTIONS"

OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


# ------------------------------------------------------------------ the DEF

Row = collections.namedtuple("Row", "y x nsites step orient")
Cell = collections.namedtuple("Cell", "name master x y orient")

ROW_RE = re.compile(r"^ROW \S+ \S+ (-?\d+) (-?\d+) (\S+) DO (\d+) BY \d+ "
                    r"STEP (\d+) \d+", re.M)
COMP_RE = re.compile(r"- (\S+) (\S+)(.*?);", re.S)
PLACE_RE = re.compile(r"\+ (?:FIXED|PLACED) \( (-?\d+) (-?\d+) \) (\S+)")


def read_def(path):
    """Rows, placed components, units and die, with a regex over the text.

    Shares nothing with tile_budget.py's reader, which is the point: the
    regions this audits were drawn by code that used that one.
    """
    text = open(path, encoding="utf-8", errors="replace").read()
    units = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", text).group(1))
    die = tuple(int(v) for v in re.search(
        r"DIEAREA \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)",
        text).groups())
    rows = [Row(int(y), int(x), int(n), int(st), o)
            for x, y, o, n, st in ROW_RE.findall(text)]
    body = re.search(r"COMPONENTS \d+ ;(.*?)END COMPONENTS", text, re.S)
    cells = []
    for name, master, rest in COMP_RE.findall(body.group(1) if body else ""):
        m = PLACE_RE.search(rest)
        if m:
            cells.append(Cell(name, master, int(m.group(1)),
                              int(m.group(2)), m.group(3)))
    return {"units": units, "die": die, "rows": rows, "cells": cells}


def packed_widths(design, masters):
    """Each master's width from the filled DEF: the gap to the next cell
    on its row. A master that packs to two different widths is reported as
    such rather than guessed at."""
    byrow = collections.defaultdict(list)
    for c in design["cells"]:
        byrow[c.y].append(c)
    seen = collections.defaultdict(set)
    for cs in byrow.values():
        cs.sort(key=lambda c: c.x)
        for a, b in zip(cs, cs[1:]):
            if a.master in masters and b.x > a.x:
                seen[a.master].add(b.x - a.x)
    return dict((m, sorted(seen.get(m, ()))) for m in masters)


# ------------------------------------------------------------- the geometry

def row_kinds(design):
    """Every row by y, told band from strip by site count. The band rows
    run the full width of the die; the strip rows are the fragment beside
    the macro block. Anything else is a third kind and gets reported."""
    widths = sorted(set(r.nsites for r in design["rows"]))
    widest = widths[-1]
    kinds = {}
    for r in design["rows"]:
        kinds[r.y] = "band" if r.nsites == widest else "strip"
    return kinds, widths


def tap_phase(design, site, half):
    """The residue, modulo half a tap pitch, of every tap on every row.

    Returns {y: sorted residues} and the tap sites per row. A single-phase
    row has one residue; a boundary row carries both phases but they are
    one residue apart by exactly half a pitch, so it has one too.
    """
    taps = collections.defaultdict(list)
    for c in design["cells"]:
        if c.master == TAP_MASTER:
            taps[c.y].append(c.x // site)
    res = dict((y, sorted(set(s % half for s in xs)))
               for y, xs in taps.items())
    return res, taps


def pitch_from_taps(taps):
    """The gap between neighbouring taps that occurs most often over the
    whole die, in sites. Boundary rows carry both phases and so show half
    of it; every other row shows the pitch itself."""
    gaps = collections.Counter()
    for xs in taps.values():
        xs = sorted(xs)
        for a, b in zip(xs, xs[1:]):
            gaps[b - a] += 1
    return gaps.most_common(1)[0][0] if gaps else 0


def free_sites(design, site, widths, arma):
    """Sites a template may use on each row: the row's own span, less the
    endcap at each end, less every Arm A cell. Taps are not subtracted;
    the template holds their sites free itself."""
    endcap = collections.defaultdict(set)
    for c in design["cells"]:
        if c.name.startswith(ENDCAP_PREFIX):
            w = widths.get(c.master, [site])[0] // site
            endcap[c.y] |= set(range(c.x // site, c.x // site + w))
    blocked = collections.defaultdict(set)
    for c in arma:
        w = widths[c.master][0] // site
        blocked[c.y] |= set(range(c.x // site, c.x // site + w))
    out = {}
    span = {}
    for r in design["rows"]:
        lo, hi = r.x // site, r.x // site + r.nsites
        span[r.y] = (lo, hi)
        out[r.y] = set(range(lo, hi)) - endcap[r.y] - blocked[r.y]
    return out, span, endcap


def groups(design, kinds, rh, orient=TEMPLATE_ORIENT, tall=ROWS_TALL):
    """Four-row groups, tiled from the first row of the template's
    orientation in each run of consecutive rows of one kind. Groups never
    straddle two kinds and never overlap each other."""
    byy = dict((r.y, r) for r in design["rows"])
    ys = sorted(byy)
    out = []
    i = 0
    while i < len(ys):
        j = i
        while (j + 1 < len(ys) and ys[j + 1] - ys[j] == rh
               and kinds[ys[j + 1]] == kinds[ys[i]]):
            j += 1
        run = ys[i:j + 1]
        k = 0
        while k < len(run) and byy[run[k]].orient != orient:
            k += 1
        while k + tall <= len(run):
            out.append({"rows": run[k:k + tall], "kind": kinds[run[k]]})
            k += tall
        i = j + 1
    return out


def slots_for(design, grp, free, phase, r, width, half, site, rh, box,
              centroid, mid_y):
    """Every x where a template fits this group with its taps on the
    reserved sites: the sites free on all four rows, and x0 congruent to
    the row kind's tap residue less r, modulo half a pitch."""
    common = set.intersection(*[free[y] for y in grp["rows"]])
    want = (phase - r) % half
    out = []
    for x0 in sorted(common):
        if x0 % half != want:
            continue
        if not all(x0 + k in common for k in range(width)):
            continue
        x_um = x0 * site
        y_um = grp["rows"][0]
        x1 = x_um + width * site
        y1 = y_um + ROWS_TALL * rh
        inside = (x_um < box[2] and x1 > box[0]
                  and y_um < box[3] and y1 > box[1])
        cx, cy = x_um + width * site / 2.0, y_um + ROWS_TALL * rh / 2.0
        d = ((cx - centroid[0]) ** 2 + (cy - centroid[1]) ** 2) ** 0.5
        where = grp["kind"]
        if where == "band":
            where = "band_low" if y_um < mid_y else "band_high"
        out.append({"x0_site": x0, "x": x_um, "y": y_um, "where": where,
                    "inside_box": inside, "dist": d,
                    "rows": list(grp["rows"])})
    return out


def taps_seen(slot, taps, site, width, r, half):
    """The tap offsets inside a slot, per row, against the reserved two."""
    seen = []
    ok = True
    for y in slot["rows"]:
        offs = sorted(t - slot["x0_site"] for t in taps.get(y, [])
                      if slot["x0_site"] <= t < slot["x0_site"] + width)
        seen.append(offs)
        if not set(offs) <= {r, r + half}:
            ok = False
    return seen, ok


def best_reserve(design, grps, free, phase_by_kind, width, half, site, rh,
                 box, centroid, mid_y):
    """The reserved offset that lets the most strip templates fit, ties to
    the smallest. Counted greedily left to right per group."""
    best = None
    for r in range(0, half):
        n = 0
        for g in grps:
            if g["kind"] != "strip":
                continue
            sl = slots_for(design, g, free, phase_by_kind["strip"], r,
                           width, half, site, rh, box, centroid, mid_y)
            last = None
            for s in sl:
                if last is None or s["x0_site"] >= last + width:
                    n += 1
                    last = s["x0_site"]
        if best is None or n > best[0]:
            best = (n, r)
    return best[1], best[0]


def packed(pool, width):
    """The most templates each group can hold without overlap: left to
    right, each one starting where the last ended or later. For windows
    of one width that greedy walk is the maximum, and it is the walk
    best_reserve counted."""
    keep = []
    last = {}
    for s in sorted(pool, key=lambda s: (s["y"], s["x"])):
        if s["y"] not in last or s["x0_site"] >= last[s["y"]] + width:
            keep.append(s)
            last[s["y"]] = s["x0_site"]
    return keep


def pick_nearest(pool, want, width):
    """Nearest to Arm A's centroid first, drawn from each group's packed
    set so that no group wastes a slot to a badly placed neighbour."""
    keep = packed(pool, width)
    keep.sort(key=lambda s: (s["dist"], s["y"], s["x"]))
    return keep[:want]


def pick_spread(pool, want, width):
    """Evenly across the width, the way gen_armc.py spread the bands."""
    keep = sorted(packed(pool, width), key=lambda s: (s["x"], s["y"]))
    if len(keep) < want or want == 0:
        return keep[:want]
    if want == 1:
        return [keep[len(keep) // 2]]
    step = (len(keep) - 1) / float(want - 1)
    return [keep[int(round(k * step))] for k in range(want)]


def layout_summary(regions, width, site, rh, centroid, die, units):
    if not regions:
        return {"regions": [], "count": 0}
    xs0 = [s["x"] for s in regions]
    ys0 = [s["y"] for s in regions]
    x0, x1 = min(xs0), max(xs0) + width * site
    y0, y1 = min(ys0), max(ys0) + ROWS_TALL * rh
    cx = sum(s["x"] + width * site / 2.0 for s in regions) / len(regions)
    cy = sum(s["y"] + ROWS_TALL * rh / 2.0 for s in regions) / len(regions)
    u = float(units)
    return {
        "count": len(regions),
        "regions": [{"index": i, "where": s["where"],
                     "x0_um": round(s["x"] / u, 3),
                     "y0_um": round(s["y"] / u, 3),
                     "x1_um": round((s["x"] + width * site) / u, 3),
                     "y1_um": round((s["y"] + ROWS_TALL * rh) / u, 3),
                     "inside_arm_a_box": s["inside_box"],
                     "dist_to_arm_a_um": round(s["dist"] / u, 3),
                     "tap_offsets": s["taps"]}
                    for i, s in enumerate(regions)],
        "bbox_um": [round(v / u, 3) for v in (x0, y0, x1, y1)],
        "span_um": [round((x1 - x0) / u, 3), round((y1 - y0) / u, 3)],
        "span_pct_of_die": [round(100.0 * (x1 - x0) / (die[2] - die[0]), 1),
                            round(100.0 * (y1 - y0) / (die[3] - die[1]), 1)],
        "centroid_um": [round(cx / u, 3), round(cy / u, 3)],
        "centroid_offset_from_arm_a_um": [round((cx - centroid[0]) / u, 3),
                                          round((cy - centroid[1]) / u, 3)],
        "max_dist_to_arm_a_um": round(max(s["dist"] for s in regions) / u,
                                      3),
        "inside_arm_a_box": sum(1 for s in regions if s["inside_box"]),
        "by_where": dict(collections.Counter(s["where"] for s in regions)),
    }


# ---------------------------------------------------------------- the score

def score(criteria, cost, n_rings, region_um2, committed_tiles, build_days):
    """The hand-placed option's six fields, and the frozen rule applied."""
    priced = [r for r in cost["priced"]["armc"] if r["rings"] == n_rings]
    decode = sorted(set(r["added_decode_um2"] for r in priced))
    pins = sorted(set(r["extra_select_bits"] for r in priced))
    free = cost["free_area_um2"]
    total = n_rings * region_um2 + (decode[0] if decode else 0.0)
    meas = cost["measured"]
    fields = {
        "pct_of_free": round(100.0 * total / free, 2) if free else None,
        "tiles_required": committed_tiles if total <= free
        else committed_tiles + 1,
        "existing_oscillators": meas["arm_a"]["rings"]
        + meas["arm_b"]["macros"],
        "new_oscillators": n_rings,
        "extra_input_pins": pins[0] if pins else None,
        "build_days": build_days,
    }
    hard = []
    survives = True
    for h in criteria.get("hard", []):
        f, op = h.get("field"), h.get("op")
        v = fields.get(f)
        if f not in fields or op not in OPS:
            # Malformed. T02 reports it; it is not a pass and not a fail.
            hard.append({"id": h.get("id"), "name": h.get("name"),
                         "field": f, "op": op, "threshold": h.get("value"),
                         "value": v, "pass": None, "margin": None})
            continue
        ok = v is not None and OPS[op](v, h["value"])
        if not ok:
            survives = False
        margin = None
        if v is not None and op in ("<=", "<"):
            margin = round(h["value"] - v, 3)
        elif v is not None and op in (">=", ">"):
            margin = round(v - h["value"], 3)
        hard.append({"id": h.get("id"), "name": h.get("name"), "field": f,
                     "op": op, "threshold": h.get("value"), "value": v,
                     "pass": bool(ok), "margin": margin})
    return {
        "option": "Arm C, %d rings, one hand-placed template" % n_rings,
        "fields": fields,
        "area": {"region_um2": round(region_um2, 4),
                 "regions_um2": round(n_rings * region_um2, 3),
                 "added_decode_um2": decode[0] if decode else None,
                 "total_um2": round(total, 3),
                 "free_area_um2": free},
        "hard": hard,
        "survives": survives,
        "build_days_basis": BUILD_DAYS_BASIS,
        "build_days_is_an_estimate": True,
        "decode_rows_agree": len(decode) == 1 and len(pins) == 1,
    }


# ------------------------------------------------------------------- driver

def run(def_path=DEF, criteria_path=CRITERIA, cost_path=COST,
        regions_path=REGIONS, config_path=CONFIG,
        frozen_sha=FROZEN_SHA256, build_days=BUILD_DAYS,
        chosen=CHOSEN_LAYOUT):
    res = Results()
    design = read_def(def_path)
    criteria = json.load(open(criteria_path, encoding="utf-8"))
    cost = json.load(open(cost_path, encoding="utf-8"))
    regions = json.load(open(regions_path, encoding="utf-8"))
    config = json.load(open(config_path, encoding="utf-8"))
    units = design["units"]
    die = design["die"]
    site = design["rows"][0].step if design["rows"] else 460
    ys = sorted(set(r.y for r in design["rows"]))
    rh = min(b - a for a, b in zip(ys, ys[1:])) if len(ys) > 1 else 0

    got = sha256_file(criteria_path)
    res.add("T01", "the criteria file is the one that was frozen",
            got == frozen_sha, "sha256 %s" % got[:12])

    unknown = [h.get("id") for h in criteria.get("hard", [])
               if h.get("op") not in OPS
               or h.get("field") not in ("pct_of_free", "tiles_required",
                                         "existing_oscillators",
                                         "new_oscillators",
                                         "extra_input_pins", "build_days")]
    res.add("T02", "every hard constraint names a field the option carries "
                   "and an operator this script implements",
            criteria.get("hard") and not unknown,
            ", ".join(str(u) for u in unknown) or
            "%d constraints" % len(criteria.get("hard", [])))

    # Arm A, and its masters' widths from the packing.
    arma = [c for c in design["cells"] if c.name.startswith(ARM_A_PREFIX)]
    masters = sorted(set(c.master for c in arma))
    widths = packed_widths(design, masters + sorted(set(
        c.master for c in design["cells"]
        if c.name.startswith(ENDCAP_PREFIX))))
    multi = sorted(m for m, w in widths.items() if len(w) != 1)
    res.add("T12", "every master this script sizes packs to one width",
            not multi, ", ".join(m.replace("sky130_fd_sc_hd__", "")
                                 for m in multi) or
            ", ".join("%s %d" % (m.replace("sky130_fd_sc_hd__", ""), w[0])
                      for m, w in sorted(widths.items()) if w))
    if multi:
        for m in multi:
            widths[m] = [widths[m][0]] if widths[m] else [site]

    want_n = regions.get("arm_a_pinned_cells")
    per_ring = cost["measured"]["arm_a"]["cells_per_ring"]
    res.add("T13", "the DEF holds the recorded number of Arm A cells and "
                   "they are the ring's three masters",
            len(arma) == want_n and len(masters) == 3
            and all(m.endswith(("inv_1", "nand2_1", "buf_1"))
                    for m in masters),
            "%d cells, masters %s" % (len(arma), ", ".join(
                m.replace("sky130_fd_sc_hd__", "") for m in masters)))

    cell_sites = max(widths[m][0] // site for m in masters) if masters else 1
    if any(widths[m][0] % site for m in masters):
        cell_sites += 1

    # The box, from the cells, against the config.
    if arma:
        bx0 = min(c.x for c in arma)
        by0 = min(c.y for c in arma)
        bx1 = max(c.x + widths[c.master][0] for c in arma)
        by1 = max(c.y for c in arma) + rh
    else:
        bx0 = by0 = bx1 = by1 = 0
    box = (bx0, by0, bx1, by1)
    cfg_box = (config.get(BOX_KEY) or [[0, 0, 0, 0]])[0]
    cfg_dbu = tuple(int(round(float(v) * units)) for v in cfg_box)
    res.add("T11", "the soft box in config.json is the Arm A cells' box",
            cfg_dbu == box,
            "cells %s, config %s" % (
                ", ".join("%.2f" % (v / float(units)) for v in box),
                ", ".join("%.2f" % v for v in cfg_box)))
    centroid = (sum(c.x for c in arma) / float(len(arma) or 1),
                sum(c.y for c in arma) / float(len(arma) or 1))
    arma_rows = len(set(c.y for c in arma))

    # Rows, taps, phase.
    kinds, row_widths = row_kinds(design)
    res.add("T15", "the rows come in exactly two widths, band and strip",
            len(row_widths) == 2,
            "widths %s sites" % ", ".join(str(w) for w in row_widths))

    width = regions["region"]["sites"]
    pitch = pitch_from_taps(tap_phase(design, site, 10 ** 9)[1])
    half = pitch // 2 if pitch else 1
    res.add("T04", "a region is exactly one tap pitch wide, so every "
                   "single-phase row inside it holds one tap",
            pitch and width == pitch and pitch % 2 == 0,
            "region %d sites, tap pitch %d" % (width, pitch))

    residues, taps = tap_phase(design, site, half)
    off = sorted(y for y, r in residues.items() if len(r) != 1)
    phase_by_kind = {}
    mixed = []
    for kind in ("band", "strip"):
        rs = set()
        for y, r in residues.items():
            if kinds.get(y) == kind and len(r) == 1:
                rs.add(r[0])
        if len(rs) == 1:
            phase_by_kind[kind] = rs.pop()
        else:
            mixed.append(kind)
            phase_by_kind[kind] = min(rs) if rs else 0
    res.add("T05", "every row's taps sit on one phase, and every row of "
                   "one kind on the same one",
            not off and not mixed,
            ("rows off: %s; " % ", ".join(str(y) for y in off) if off
             else "") + (
                "kinds mixed: %s" % ", ".join(mixed) if mixed else
                "strip %d, band %d, modulo %d sites"
                % (phase_by_kind["strip"], phase_by_kind["band"], half)))

    # Does the ring fit between the two reserved sites.
    per_row = -(-per_ring // ROWS_TALL)
    need = per_row * cell_sites
    res.add("T03", "a ring's cells fit in the sites between the two "
                   "reserved tap sites, four rows tall",
            per_ring % ROWS_TALL == 0 and need <= half - 1,
            "%d cells a row at %d sites is %d, %d available"
            % (per_row, cell_sites, need, half - 1))

    # Arm A cells and the taps and endcaps must never share a site, or the
    # frozen coordinates could not be replayed after step 19.
    free, span, endcap = free_sites(design, site, widths, arma)
    clash = []
    for c in arma:
        s0 = c.x // site
        cs = set(range(s0, s0 + widths[c.master][0] // site))
        if cs & set(taps.get(c.y, ())) or cs & endcap.get(c.y, set()):
            clash.append(c.name)
    res.add("T06", "no Arm A cell stands on a tap or an endcap",
            not clash, "%d clash" % len(clash) if clash else
            "%d cells, %d taps, %d endcap sites"
            % (len(arma), sum(len(v) for v in taps.values()),
               sum(len(v) for v in endcap.values())))

    mid_y = (die[1] + die[3]) // 2
    grps = groups(design, kinds, rh)
    r, strip_fit = best_reserve(design, grps, free, phase_by_kind, width,
                                half, site, rh, box, centroid, mid_y)
    slots = []
    for g in grps:
        slots.extend(slots_for(design, g, free, phase_by_kind[g["kind"]],
                               r, width, half, site, rh, box, centroid,
                               mid_y))
    for s in slots:
        s["taps"], s["taps_ok"] = taps_seen(s, taps, site, width, r, half)

    # Two layouts, neither chosen.
    n_rings = regions["rings"]
    quota = regions.get("quota", {})
    strip_pool = [s for s in slots if s["where"] == "strip"
                  and not s["inside_box"]]
    col = pick_nearest(strip_pool, n_rings, width)
    three = pick_nearest(strip_pool, quota.get("strip", 0), width)
    three += pick_spread([s for s in slots if s["where"] == "band_low"],
                         quota.get("band_low", 0), width)
    three += pick_spread([s for s in slots if s["where"] == "band_high"],
                         quota.get("band_high", 0), width)
    res.add("T07", "the column layout found all sixteen beside Arm A",
            len(col) == n_rings,
            "%d of %d, from %d packed strip slots outside the box"
            % (len(col), n_rings, len(packed(strip_pool, width))))
    res.add("T08", "the quota sums to the ring count and every part "
                   "found its share",
            sum(quota.values()) == n_rings and all(
                sum(1 for s in three if s["where"] == w) == n
                for w, n in quota.items()),
            ", ".join("%s %d of %d" % (w, sum(1 for s in three
                                              if s["where"] == w), n)
                      for w, n in sorted(quota.items())))
    bad = [s for s in col + three if not s["taps_ok"]]
    res.add("T09", "every chosen region sees its taps on the reserved "
                   "sites and nowhere else, or sees none",
            not bad, "%d regions off" % len(bad) if bad else
            "%d regions" % (len(col) + len(three)))

    # The recorded regions, audited the same way.
    audit = []
    patterns = set()
    for reg in regions.get("regions", []):
        x0 = int(round(reg["x0_um"] * units)) // site
        y0 = int(round(reg["y0_um"] * units))
        rws = [y0 + k * rh for k in range(ROWS_TALL)]
        fake = {"x0_site": x0, "rows": rws}
        seen, _ok = taps_seen(fake, taps, site, width, r, half)
        pat = tuple(tuple(v) for v in seen)
        patterns.add(pat)
        first = [rw for rw in design["rows"] if rw.y == y0]
        ov = (reg["x0_um"] * units < box[2]
              and reg["x1_um"] * units > box[0]
              and reg["y0_um"] * units < box[3]
              and reg["y1_um"] * units > box[1])
        audit.append({"index": reg["index"], "where": reg["where"],
                      "tap_offsets": [list(v) for v in seen],
                      "first_row_orient": first[0].orient if first
                      else "none",
                      "overlaps_arm_a_box": ov})

    region_um2 = (width * site * ROWS_TALL * rh) / float(units) ** 2
    sc = score(criteria, cost, n_rings, region_um2,
               criteria.get("committed", {}).get("tiles", 4), build_days)
    res.add("T10", "the hand-placed option clears every hard constraint",
            sc["survives"] and sc["decode_rows_agree"],
            ", ".join("%s %s" % (h["id"], "ok" if h["pass"] else "FAIL")
                      for h in sc["hard"]))

    # The chosen layout has to name one of the two that were enumerated,
    # or the record carries a decision pointing at nothing. Whether that
    # layout found all sixteen is not asked here: T07 owns that for the
    # column and T08 owns it for the three-part, and a check that asked
    # again would fire alongside whichever of them caught it.
    built = {"column": col, "three_part": three}
    res.add("T14", "the layout the build is to use names one of the two",
            chosen in built,
            "%s, %d regions" % (chosen, len(built.get(chosen, ()))))

    res.rows.sort(key=lambda r: r["id"])
    u = float(units)
    out = {
        "_comment": [
            "The hand-placed Arm C, scored against the frozen G.2 rule",
            "and laid out as a template that a FIRM placement at step 21",
            "can replay. Written by chip/armc_template.py from the frozen",
            "two-arm DEF. Nothing in the build reads this file. The two",
            "layouts are candidates and neither is chosen; see",
            "docs/phaseG_run80.md for what the choice turns on.",
        ],
        "gate": "G.2 amendment",
        "source": {"def": sha256_file(def_path),
                   "criteria": got,
                   "cost": sha256_file(cost_path),
                   "regions": sha256_file(regions_path)},
        "checks": res.rows,
        "score": sc,
        "template": {
            "sites": width, "rows": ROWS_TALL,
            "width_um": round(width * site / u, 3),
            "height_um": round(ROWS_TALL * rh / u, 3),
            "area_um2": round(region_um2, 4),
            "tap_pitch_sites": pitch,
            "reserved_tap_sites": [r, r + half],
            "reserve_chosen_for": "%d strip templates fit at this offset, "
                                  "the most of any" % strip_fit,
            "cells_per_row": per_row,
            "cell_sites": cell_sites,
            "cell_sites_from_to": [r + 1, r + per_row * cell_sites],
            "first_row_orient": TEMPLATE_ORIENT,
            "order": "serpentine: the enable NAND then inverters 0 to 6 "
                     "left to right on the first row, 7 to 14 right to "
                     "left on the second, 15 to 22 left to right, 23 to "
                     "29 and the output buffer right to left. Default, "
                     "open until the build.",
        },
        "tap_phase": {"half_pitch_sites": half,
                      "strip_residue": phase_by_kind.get("strip"),
                      "band_residue": phase_by_kind.get("band")},
        "arm_a": {"cells": len(arma), "rows": arma_rows,
                  "box_um": [round(v / u, 3) for v in box],
                  "centroid_um": [round(centroid[0] / u, 3),
                                  round(centroid[1] / u, 3)]},
        "recorded_regions": {
            "file": os.path.basename(regions_path),
            "distinct_tap_patterns": len(patterns),
            "one_template_fits_all": len(patterns) == 1,
            "overlap_arm_a_box": sum(1 for a in audit
                                     if a["overlaps_arm_a_box"]),
            "first_row_orients": dict(collections.Counter(
                a["first_row_orient"] for a in audit)),
            "per_region": audit,
        },
        "slots": {
            "reserved_offset": r,
            "templates": dict(collections.Counter(
                s["where"] + ("_inside_box" if s["inside_box"] else "")
                for s in packed(slots, width))),
            "windows_before_packing": dict(collections.Counter(
                s["where"] for s in slots)),
            "groups": [{"kind": g["kind"], "y0_um": round(g["rows"][0] / u,
                                                          3)}
                       for g in grps],
        },
        "chosen_layout": chosen,
        "chosen_layout_decided": "2026-09-12, after the freeze, not part "
                                 "of the G.2 rule. See G2_AMENDMENT.json.",
        "layouts": {
            "column": dict(layout_summary(col, width, site, rh, centroid,
                                          die, units),
                           chosen=chosen == "column",
                           what="all sixteen in the strip beside Arm A, "
                                "nearest its centroid first, none inside "
                                "its box"),
            "three_part": dict(layout_summary(three, width, site, rh,
                                              centroid, die, units),
                               chosen=chosen == "three_part",
                               what="gen_armc.py's split, eight in the "
                                    "strip and four in each band, "
                                    "re-sited so one template fits"),
        },
    }
    return out, res


def render(out, res):
    lines = []
    for r in res.rows:
        lines.append("  %s %-4s %s: %s" % ("ok  " if r["pass"] else "FAIL",
                                           r["id"], r["name"], r["detail"]))
    sc = out["score"]
    lines.append("")
    lines.append("%s: %s" % (sc["option"],
                             "survives" if sc["survives"] else "REJECTED"))
    for h in sc["hard"]:
        lines.append("  %s %s %s %s %s (margin %s)"
                     % (h["id"], h["field"], h["value"], h["op"],
                        h["threshold"], h["margin"]))
    t = out["template"]
    lines.append("")
    lines.append("template %d sites x %d rows, taps held at %s, cells at "
                 "%s to %s" % (t["sites"], t["rows"],
                               t["reserved_tap_sites"],
                               t["cell_sites_from_to"][0],
                               t["cell_sites_from_to"][1]))
    rr = out["recorded_regions"]
    lines.append("recorded regions: %d tap patterns, %d overlap the box, "
                 "first rows %s"
                 % (rr["distinct_tap_patterns"], rr["overlap_arm_a_box"],
                    rr["first_row_orients"]))
    for name, lay in sorted(out["layouts"].items()):
        lines.append("%s%s: %d regions, span %s um (%s%% of die), centroid "
                     "off Arm A by %s um, max %s um away, %d in the box"
                     % (name, " (chosen)" if lay.get("chosen") else "",
                        lay["count"], lay.get("span_um"),
                        lay.get("span_pct_of_die"),
                        lay.get("centroid_offset_from_arm_a_um"),
                        lay.get("max_dist_to_arm_a_um"),
                        lay.get("inside_arm_a_box", 0)))
    return "\n".join(lines)


# ----------------------------------------------------------------- selftest

def fixture(tmp, mutate=None):
    """A small design with the real shape: five full rows below and five
    above, thirteen narrow rows between, rows alternating N and FS the
    way the die does, taps at a 56-site pitch staggered by 28 with the
    band and strip on different phases, an endcap at every row end with a
    filler packed against it, and two Arm A rings of eight cells packed
    in the strip. `mutate` edits the dict of texts before they are
    written."""
    site, rh, units = 460, 2720, 1000
    pitch, half = 56, 28
    band_sites, strip_sites = 300, 188
    band_x = 2760
    strip_x = band_x + 112 * site
    rows = []
    for i in range(5 + 13 + 5):
        strip = 5 <= i < 18
        rows.append(((i + 1) * rh, strip_x if strip else band_x,
                     strip_sites if strip else band_sites,
                     "N" if i % 2 == 0 else "FS"))
    die = (0, 0, band_x + band_sites * site + band_x, (len(rows) + 1) * rh)
    cells = []
    tapn = 0
    for (ry, rx, n, o) in rows:
        s0, s1 = rx // site, rx // site + n
        cells.append(("PHY_%d_a" % ry, "sky130_fd_sc_hd__decap_3",
                      s0 * site, ry, o))
        cells.append(("FILLER_%d" % ry, "sky130_fd_sc_hd__fill_2",
                      (s0 + 3) * site, ry, o))
        cells.append(("PHY_%d_b" % ry, "sky130_fd_sc_hd__decap_3",
                      (s1 - 3) * site, ry, o))
        base = 34 if n == band_sites else 2
        t = base if o == "N" else base + half
        while t < s1 - 3:
            if t >= s0 + 5:
                cells.append(("TAP_%d" % tapn,
                              "sky130_fd_sc_hd__tapvpwrvgnd_1",
                              t * site, ry, o))
                tapn += 1
            t += pitch
    # Two rings of eight in the strip's fifth (FS) and sixth (N) rows,
    # clear of those rows' taps (142, 198, 254 and 170, 226, 282).
    strip_rows = [r for r in rows if r[2] == strip_sites]
    arma = []
    for ring, ((ry, rx, n, o), start) in enumerate(
            zip(strip_rows[4:6], (208, 236))):
        x = start * site
        for k in range(8):
            master = ("sky130_fd_sc_hd__nand2_1" if k == 0 else
                      "sky130_fd_sc_hd__buf_1" if k == 7 else
                      "sky130_fd_sc_hd__inv_1")
            name = ("u_puf.u_core.g_ro_bank\\[%d\\].u_ro.%s" % (
                ring, "u_nand" if k == 0 else "u_buf" if k == 7
                else "g_inv\\[%d\\].u_inv" % (k - 1)))
            arma.append((name, master, x, ry, o))
            x += 3 * site
        cells.append(("_after%d_" % ring, "sky130_fd_sc_hd__fill_2", x, ry,
                      o))
    cells += arma
    bx0 = min(c[2] for c in arma)
    by0 = min(c[3] for c in arma)
    bx1 = max(c[2] for c in arma) + 3 * site
    by1 = max(c[3] for c in arma) + rh
    lines = ["VERSION 5.8 ;", "DESIGN fixture ;",
             "UNITS DISTANCE MICRONS %d ;" % units,
             "DIEAREA ( %d %d ) ( %d %d ) ;" % die]
    for i, (ry, rx, n, o) in enumerate(rows):
        lines.append("ROW ROW_%d unithd %d %d %s DO %d BY 1 STEP %d 0 ;"
                     % (i, rx, ry, o, n, site))
    lines.append("COMPONENTS %d ;" % len(cells))
    for name, master, x, ry, o in cells:
        lines.append("- %s %s + PLACED ( %d %d ) %s ;"
                     % (name, master, x, ry, o))
    lines.append("END COMPONENTS")
    lines.append("END DESIGN")
    crit = {
        "hard": [
            {"id": "H1", "name": "fits", "field": "pct_of_free",
             "op": "<=", "value": 75.0},
            {"id": "H2", "name": "tiles", "field": "tiles_required",
             "op": "<=", "value": 4},
            {"id": "H3", "name": "keeps", "field": "existing_oscillators",
             "op": "==", "value": 32},
            {"id": "H4", "name": "eight", "field": "new_oscillators",
             "op": ">=", "value": 4},
            {"id": "H5", "name": "pins", "field": "extra_input_pins",
             "op": "<=", "value": 1},
            {"id": "H6", "name": "days", "field": "build_days",
             "op": "<=", "value": 5},
        ],
        "committed": {"tiles": 4},
    }
    n_rings = 4
    cost = {
        "free_area_um2": 4000.0,
        "measured": {"arm_a": {"rings": 16, "cells_per_ring": 8},
                     "arm_b": {"macros": 16}},
        "priced": {"armc": [
            {"rings": n_rings, "added_decode_um2": 50.0,
             "extra_select_bits": 1, "density_label": "mean"},
            {"rings": n_rings, "added_decode_um2": 50.0,
             "extra_select_bits": 1, "density_label": "tight"},
            {"rings": 8, "added_decode_um2": 70.0,
             "extra_select_bits": 1, "density_label": "mean"}]},
    }
    # Two recorded regions at different offsets from the tap grid, so
    # the audit has two patterns to find.
    regs = {
        "rings": n_rings,
        "arm_a_pinned_cells": len(arma),
        "quota": {"strip": 2, "band_low": 1, "band_high": 1},
        "region": {"sites": pitch, "rows": 4},
        "regions": [
            {"index": 0, "where": "strip", "x0_um": 135 * site / 1000.0,
             "x1_um": 191 * site / 1000.0,
             "y0_um": strip_rows[1][0] / 1000.0,
             "y1_um": (strip_rows[1][0] + 4 * rh) / 1000.0},
            {"index": 1, "where": "strip", "x0_um": 143 * site / 1000.0,
             "x1_um": 199 * site / 1000.0,
             "y0_um": strip_rows[9][0] / 1000.0,
             "y1_um": (strip_rows[9][0] + 4 * rh) / 1000.0},
        ],
    }
    cfg = {BOX_KEY: [[bx0 / 1000.0, by0 / 1000.0, bx1 / 1000.0,
                      by1 / 1000.0]]}
    texts = {"def": "\n".join(lines) + "\n",
             "criteria": json.dumps(crit, indent=1, sort_keys=True),
             "cost": json.dumps(cost, indent=1, sort_keys=True),
             "regions": json.dumps(regs, indent=1, sort_keys=True),
             "config": json.dumps(cfg, indent=1)}
    if mutate:
        mutate(texts)
    paths = {}
    for k, v in texts.items():
        p = os.path.join(tmp, k + ".txt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(v)
        paths[k] = p
    return paths


def run_fixture(tmp, mutate=None, sha=None, build_days=BUILD_DAYS,
                chosen=CHOSEN_LAYOUT):
    paths = fixture(tmp, mutate)
    want = sha if sha is not None else sha256_file(paths["criteria"])
    return run(paths["def"], paths["criteria"], paths["cost"],
               paths["regions"], paths["config"], want, build_days,
               chosen)


def _edit_json(key, fn):
    def m(t):
        obj = json.loads(t[key])
        fn(obj)
        t[key] = json.dumps(obj, indent=1, sort_keys=True)
    return m


def _edit_def(fn):
    def m(t):
        t["def"] = fn(t["def"])
    return m


def _swap(text, old, new):
    if text.count(old) != 1:
        raise ValueError("fixture anchor %r found %d times"
                         % (old, text.count(old)))
    return text.replace(old, new, 1)


def _bad_op(o):
    o["hard"][0]["op"] = "~="


def _too_many(o):
    o["measured"]["arm_a"]["cells_per_ring"] = 40


def _wrong_width(o):
    o["region"]["sites"] = 55


def _tap_off(text):
    # the spare strip row's first tap (site 142 on row 18) one site right
    return _swap(text, "+ PLACED ( 65320 48960 ) FS ;",
                 "+ PLACED ( 65780 48960 ) FS ;")


def _tap_on_arm_a(text):
    # a tap on the first ring's sixth inverter, site 226, which is on the
    # row's own phase so only the clash shows
    m = re.search(r"- u_puf\S+bank\\\[0\\\]\S+u_nand \S+ \+ PLACED "
                  r"\( (\d+) (\d+) \) (\S+) ;", text)
    x = int(m.group(1)) + 18 * 460
    return _swap(text, "END COMPONENTS",
                 "- TAP_X sky130_fd_sc_hd__tapvpwrvgnd_1 + PLACED "
                 "( %d %s ) %s ;\nEND COMPONENTS" % (x, m.group(2),
                                                      m.group(3)))


def _too_many_rings(o):
    # the strip packs seven outside the box; the bands have plenty
    o["rings"] = 8
    o["quota"] = {"strip": 2, "band_low": 3, "band_high": 3}


def _quota_short(o):
    o["quota"] = {"strip": 1, "band_low": 1, "band_high": 1}


def _days_cut(o):
    o["hard"][5]["value"] = 2


def _box_moved(o):
    o[BOX_KEY][0][0] += 1.0


def _two_widths(text):
    # the filler packed after the first ring's buffer moved to site 300,
    # still on its row, so buf_1 packs to two widths and nothing else
    return _swap(text, "- _after0_ sky130_fd_sc_hd__fill_2 + PLACED "
                 "( 106720 27200 ) FS ;",
                 "- _after0_ sky130_fd_sc_hd__fill_2 + PLACED "
                 "( 138000 27200 ) FS ;")


def _count_wrong(o):
    o["arm_a_pinned_cells"] = 15


def _third_width(text):
    # the spare strip row, one site short
    return _swap(text, "ROW ROW_17 unithd 54280 48960 FS DO 188 BY 1",
                 "ROW ROW_17 unithd 54280 48960 FS DO 187 BY 1")


FAULTS = (
    ("T01", "the criteria file edited after freezing",
     lambda tmp: run_fixture(tmp, sha="0" * 64)),
    ("T02", "a rule using an operator this script has no code for",
     lambda tmp: run_fixture(tmp, _edit_json("criteria", _bad_op))),
    ("T03", "a ring too long for the sites between the taps",
     lambda tmp: run_fixture(tmp, _edit_json("cost", _too_many))),
    ("T04", "a region one site narrower than the tap pitch",
     lambda tmp: run_fixture(tmp, _edit_json("regions", _wrong_width))),
    ("T05", "one tap a site off its row's phase",
     lambda tmp: run_fixture(tmp, _edit_def(_tap_off))),
    ("T06", "a tap standing on an Arm A cell",
     lambda tmp: run_fixture(tmp, _edit_def(_tap_on_arm_a))),
    ("T07", "more rings than the strip has room for beside Arm A",
     lambda tmp: run_fixture(tmp, _edit_json("regions", _too_many_rings))),
    ("T08", "a quota that does not add up to the ring count",
     lambda tmp: run_fixture(tmp, _edit_json("regions", _quota_short))),
    ("T10", "a build budget the estimate does not meet",
     lambda tmp: run_fixture(tmp, _edit_json("criteria", _days_cut))),
    ("T11", "the config box a micron off the cells",
     lambda tmp: run_fixture(tmp, _edit_json("config", _box_moved))),
    ("T12", "a master packing to two widths",
     lambda tmp: run_fixture(tmp, _edit_def(_two_widths))),
    ("T13", "the recorded Arm A count wrong",
     lambda tmp: run_fixture(tmp, _edit_json("regions", _count_wrong))),
    ("T14", "a chosen layout that is not one of the two",
     lambda tmp: run_fixture(tmp, chosen="whichever")),
    ("T15", "a row of a third width",
     lambda tmp: run_fixture(tmp, _edit_def(_third_width))),
)


def selftest():
    ok = True
    tmp = tempfile.mkdtemp(prefix="armc_template_")
    try:
        out, res = run_fixture(tmp)
        if res.failed():
            print("  FAIL clean fixture: %s" % ", ".join(res.failed()))
            for r in res.rows:
                if not r["pass"]:
                    print("        %s %s" % (r["id"], r["detail"]))
            ok = False
        else:
            print("  ok    clean fixture passes all %d checks"
                  % len(res.rows))
        # The fixture's own arithmetic, by hand.
        t = out["template"]
        if t["reserved_tap_sites"] != [t["reserved_tap_sites"][0],
                                       t["reserved_tap_sites"][0] + 28]:
            print("  FAIL reserved sites %s" % t["reserved_tap_sites"])
            ok = False
        if out["tap_phase"] != {"half_pitch_sites": 28,
                                "strip_residue": 2, "band_residue": 6}:
            print("  FAIL tap phase %s" % out["tap_phase"])
            ok = False
        if out["recorded_regions"]["distinct_tap_patterns"] != 2:
            print("  FAIL recorded regions should show two patterns: %s"
                  % out["recorded_regions"]["distinct_tap_patterns"])
            ok = False
        lay = out["layouts"]
        if (lay["column"]["inside_arm_a_box"] != 0
                or lay["three_part"]["by_where"] !=
                {"strip": 2, "band_low": 1, "band_high": 1}):
            print("  FAIL layouts: %s / %s"
                  % (lay["column"]["inside_arm_a_box"],
                     lay["three_part"]["by_where"]))
            ok = False
        sc = out["score"]["fields"]
        # 4 regions of 56*460*4*2720 dbu2 = 280.2688 um2, plus 50 decode,
        # over 4000 free
        want = round(100.0 * (4 * 280.2688 + 50.0) / 4000.0, 2)
        if sc["pct_of_free"] != want or sc["existing_oscillators"] != 32 \
                or sc["extra_input_pins"] != 1 or sc["tiles_required"] != 4:
            print("  FAIL score fields %s" % sc)
            ok = False
        out2, _ = run_fixture(tmp)
        if json.dumps(out, sort_keys=True) != json.dumps(out2,
                                                         sort_keys=True):
            print("  FAIL two runs on one fixture disagree")
            ok = False
        for cid, what, fn in FAULTS:
            sub = tempfile.mkdtemp(prefix="f_", dir=tmp)
            try:
                _o, r = fn(sub)
            except Exception as e:        # a crash is not a detection
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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", help="write the record here")
    ap.add_argument("--def", dest="def_path", default=DEF)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    out, res = run(a.def_path)
    print(render(out, res))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
            fh.write("\n")
    return 1 if res.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
