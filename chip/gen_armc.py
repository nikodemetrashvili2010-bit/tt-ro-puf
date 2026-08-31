#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Where the sixteen Arm C rings go, and the files the build needs to put
them there.

G.2 chose Arm C: sixteen standard-cell rings under placement and routing
equalization constraints. The build criterion frozen with that decision is
that every Arm C ring ends up in an identical region. This works out where
those regions are, and emits what the build reads.

Three things are decided here and each one is derived rather than picked.

**The region size.** A region has to hold 120.1152 um2 of cells, which is
what an Arm A ring is, and it is charged in full whether the cells fill it or
not. The size is the integer site width whose resulting density comes closest
to the mean density an unconstrained placer already achieved on Arm A. That
matters: if Arm C's regions were tighter or looser than Arm A's placements,
the treatment would be confounded with a density change, and the experiment
is about uniformity, not tightness.

**Arm A has to be pinned.** E.1's rule is to preserve the existing two-arm
result rather than sacrifice it, and a rebuild re-places every standard cell,
so the Arm A on the chip would not be the Arm A the paper measured. The only
way to keep it is to fix all 512 cells at the coordinates they already have.
That is legitimate: the treatment is "these cells were placed by an
unconstrained flow", and replaying that placement leaves the claim true. It
also means Arm A's cells, and nothing else, block where Arm C can go. Every
other standard cell moves in the rebuild, so it blocks nothing.

**Where the sixteen sit.** Eight in the strip beside Arm A, four in the band
below the macro block, four in the band above it. That is not tidiness. Arm A
is pinned in the strip, so putting all of Arm C somewhere else would alias
the treatment with die position, and any supply or temperature gradient would
land entirely on the comparison. Splitting Arm C across three parts of the
die puts that contrast inside one arm, where it can be measured instead of
assumed away.

What this does not do is touch `src/`. The RTL is emitted beside this script
for the build step to install, and it has not been simulated. Structure is
checked here; behaviour is the build's job and G.3's.

Usage:
    python3 gen_armc.py --selftest
    python3 gen_armc.py
    python3 gen_armc.py --json /tmp/armc_regions.json --emit /tmp/armc
"""

import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import tile_budget as tb                                    # noqa: E402

BUILD = os.path.join(ROOT, "dualarm", "build_current")
COST_JSON = os.path.join(HERE, "ARMC_COST.json")

N_RINGS = 16
ROWS_TALL = 4                # a region is four rows, like most Arm A rings
GAP_SITES = 2                # sites left between neighbouring regions

# How the sixteen are shared out. The strip is where Arm A is pinned; the two
# bands are the full-width rows below and above the macro block.
QUOTA = (("strip", 8), ("band_low", 4), ("band_high", 4))

# Arm A's ring, from the netlist: thirty inverters, one buffer, one enable
# NAND. Arm C is the same circuit under a different name so the flow cannot
# share cells between the arms.
RING_INVERTERS = 30


def um(v, u):
    return v / float(u)


def um2(v, u):
    return v / float(u) / float(u)


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


# ---------------------------------------------------------------- geometry

def row_table(design):
    """Rows grouped by y, each with its spans and whether it is a band row.

    A band row runs the full width of the die above or below the macro block.
    A strip row is the narrow column beside it. They are told apart by site
    count, which is how `tile_budget.py` splits them too.
    """
    spans = collections.defaultdict(list)
    for r in design.rows:
        spans[r.y].append((r.x, r.x + r.nsites * r.step, r.nsites))
    widest = max(r.nsites for r in design.rows)
    return spans, widest


def free_sites(design, widths, spans, blocked_class="arma_ring"):
    """Site indices free in each row once Arm A is pinned.

    Nothing else blocks. Filler, decap, taps and the control logic are all
    re-placed by the rebuild, so they constrain the total area and not the
    position of anything.
    """
    site = design.rows[0].step
    blocked = collections.defaultdict(list)
    for c in design.onrow:
        if tb.classify(c.master, c.inst) == blocked_class:
            blocked[c.y].append((c.x, c.x + widths.get(c.master, 0)))
    out = {}
    for y, sp in spans.items():
        cells = set()
        for lo, hi, _n in sp:
            cells |= set(range(lo // site, hi // site))
        for a, b in blocked.get(y, ()):
            cells -= set(range(a // site, -(-b // site)))
        out[y] = cells
    return out, blocked


def choose_width(target_density, cell_area_um2, rows_tall, site, rh, units):
    """The integer site width whose density lands closest to Arm A's mean.

    Ties go to the wider region, because a region that is a shade too loose
    costs area and one that is a shade too tight cannot be legalised.
    """
    best = None
    for sites in range(4, 400):
        area = um2(sites * site * rows_tall * rh, units)
        dens = cell_area_um2 / area
        err = abs(dens - target_density)
        if best is None or err < best[0] - 1e-12:
            best = (err, sites, area, dens)
    return best[1], best[2], best[3]


def candidate_slots(design, spans, freed, widest, sites, rows_tall=ROWS_TALL,
                    gap=GAP_SITES):
    """Every place a region of this shape fits, left to right, bottom up.

    A group is `rows_tall` consecutive rows of one kind. Mixing a band row
    and a strip row into one region would give a region that is not the same
    shape as its neighbours once the row spans differ, so groups never
    straddle the two.
    """
    site = design.rows[0].step
    rh = design.row_height
    ys = sorted(spans)
    band = set(y for y in ys if any(n == widest for _lo, _hi, n in spans[y]))
    # Low or high is decided against the middle of the die, not against the
    # macro block. The block's own extent moves if a macro moves, and a
    # classification that depends on where a macro happens to be turns any
    # macro fault into a quota fault as well.
    mid_y = (design.die[1] + design.die[3]) // 2
    out = []
    i = 0
    while i + rows_tall <= len(ys):
        grp = ys[i:i + rows_tall]
        if (grp[-1] - grp[0] != rh * (rows_tall - 1)
                or len(set((y in band) for y in grp)) != 1):
            i += 1
            continue
        where = ("band_low" if grp[0] < mid_y else "band_high") \
            if grp[0] in band else "strip"
        common = set.intersection(*[freed[y] for y in grp])
        cur = sorted(common)
        j = 0
        while j < len(cur):
            st = cur[j]
            if all(st + k in common for k in range(sites)):
                out.append({"x": st * site, "y": grp[0], "where": where})
                j += sites + gap
            else:
                j += 1
        i += rows_tall
    return out


def pick_slots(slots, centroid, quota=QUOTA, n=N_RINGS):
    """The declared selection rule, applied.

    In the strip, the ones nearest Arm A's centroid, because that is the
    comparison the paper leans on and shared die position makes it cleaner.
    In each band, evenly spread across the width, because there the point is
    to sample position rather than to match it.
    """
    by_where = collections.defaultdict(list)
    for s in slots:
        by_where[s["where"]].append(s)
    chosen = []
    for where, want in quota:
        pool = sorted(by_where.get(where, []), key=lambda s: (s["x"], s["y"]))
        if len(pool) < want:
            continue
        if where == "strip":
            pool = sorted(pool, key=lambda s: ((s["x"] - centroid[0]) ** 2
                                               + (s["y"] - centroid[1]) ** 2,
                                               s["x"], s["y"]))[:want]
        else:
            step = (len(pool) - 1) / float(want - 1) if want > 1 else 0
            pool = [pool[int(round(k * step))] for k in range(want)]
        chosen.extend(sorted(pool, key=lambda s: (s["y"], s["x"])))
    return chosen[:n]


# ------------------------------------------------------------------ emitted

def tcl_pin_arm_a(design, widths, arma):
    """OpenROAD `place_cell` lines fixing every Arm A cell where it is.

    `place_cell` is the command; the region binding for Arm C is not emitted
    as a command because the name differs between flow versions and inventing
    one would be worse than saying so. See the writeup.
    """
    lines = ["# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili",
             "# SPDX-License-Identifier: Apache-2.0",
             "#",
             "# Arm A, pinned. Generated by chip/gen_armc.py, do not edit.",
             "# %d cells at the coordinates dualarm/build_current already has."
             % len(arma),
             "# Without this the rebuild re-places Arm A and the two-arm",
             "# result the paper measured is not the one on the die.",
             ""]
    u = design.units
    for c in sorted(arma, key=lambda c: (c.y, c.x)):
        lines.append('place_cell -inst_name {%s} -origin {%.3f %.3f} '
                     '-orient %s -status FIRM'
                     % (tb.unescape(c.inst), um(c.x, u), um(c.y, u),
                        c.orient))
    return "\n".join(lines) + "\n"


def tcl_regions(design, regions, sites, rows_tall=ROWS_TALL):
    site = design.rows[0].step
    rh = design.row_height
    u = design.units
    lines = ["# Arm C regions. Generated by chip/gen_armc.py, do not edit.",
             "# %d identical rectangles, %.2f x %.2f um each." %
             (len(regions), um(sites * site, u), um(rows_tall * rh, u)),
             "#",
             "# The command that binds a cell group to a region is not",
             "# written here on purpose. It differs between OpenLane and",
             "# OpenROAD versions and this file is generated from geometry,",
             "# not from a toolchain the script has run. Fill it in against",
             "# the flow the build actually uses and check the log says all",
             "# %d groups were constrained." % len(regions), ""]
    for i, r in enumerate(regions):
        lines.append("# ring %-2d %-9s x %8.3f  y %8.3f  to  x %8.3f  y %8.3f"
                     % (i, r["where"], um(r["x"], u), um(r["y"], u),
                        um(r["x"] + sites * site, u),
                        um(r["y"] + rows_tall * rh, u)))
        lines.append("set armc_region(%d) {%.3f %.3f %.3f %.3f}"
                     % (i, um(r["x"], u), um(r["y"], u),
                        um(r["x"] + sites * site, u),
                        um(r["y"] + rows_tall * rh, u)))
    return "\n".join(lines) + "\n"


def verilog_ring():
    """Arm C's ring. The same circuit as `src/ro_macro.v` under its own name,
    so synthesis cannot share cells between the two arms."""
    return """// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Arm C ring oscillator. Generated by chip/gen_armc.py, do not edit.
//
// Electrically identical to src/ro_macro.v: an enable NAND and %d
// inverters. It carries its own module name so that synthesis keeps the two
// arms separate, and its own `keep` attributes so the optimiser cannot merge
// a stage away. The treatment that makes it Arm C is not in this file, it is
// the placement constraint in armc_place.tcl.
//
// NOT SIMULATED. Lint and gate-level test it in the build step.

`timescale 1ps/1ps
`default_nettype none

module ro_armc #(
    parameter integer N_INV = %d,
    parameter integer IDX   = 0
) (
    input  wire en,
    output wire out
);
    (* keep *) wire [N_INV:0] n;

    (* keep *) sky130_fd_sc_hd__nand2_1 u_nand (
        .A(en), .B(n[N_INV]), .Y(n[0]));

    genvar i;
    generate
        for (i = 0; i < N_INV; i = i + 1) begin : g_inv
            (* keep *) sky130_fd_sc_hd__inv_1 u_inv (
                .A(n[i]), .Y(n[i+1]));
        end
    endgenerate

    (* keep *) sky130_fd_sc_hd__buf_1 u_buf (.A(n[N_INV]), .X(out));
endmodule

`default_nettype wire
""" % (RING_INVERTERS, RING_INVERTERS)


def verilog_select(n_per_arm, arms):
    """The select arithmetic the third arm forces, as a note the build reads.

    `ro_puf.v` today builds `ro_sel = {arm, ro_idx}` with a one-bit arm and a
    five-bit select. Three arms need two arm bits and six, and the extra bit
    is `ui[7]`, which E.1b checked is genuinely unconnected today.
    """
    total = n_per_arm * arms
    bits = 1
    while (1 << bits) < total:
        bits += 1
    arm_bits = 1
    while (1 << arm_bits) < arms:
        arm_bits += 1
    return {"oscillators": total, "select_bits": bits, "arm_bits": arm_bits,
            "idx_bits": bits - arm_bits}


# ------------------------------------------------------------------- checks

def run_checks(design, widths, regions, sites, arma, cost, freed, spans,
               rows_tall=ROWS_TALL, quota=QUOTA):
    res = Results()
    site = design.rows[0].step
    rh = design.row_height
    u = design.units
    rw, rhgt = sites * site, rows_tall * rh

    res.add("A01", "sixteen regions were placed", len(regions) == N_RINGS,
            "%d placed" % len(regions))

    overlaps = 0
    for i in range(len(regions)):
        for j in range(i + 1, len(regions)):
            a, b = regions[i], regions[j]
            if (a["x"] < b["x"] + rw and b["x"] < a["x"] + rw
                    and a["y"] < b["y"] + rhgt and b["y"] < a["y"] + rhgt):
                overlaps += 1
    res.add("A02", "no two regions overlap", overlaps == 0,
            "%d overlapping pairs" % overlaps)

    # Sitting on a pinned Arm A cell and sitting off the rows are the same
    # failure seen twice: `freed` holds only the sites that are both on a row
    # and clear of Arm A, so no fault can trip one without the other. One
    # check, two faults, same as T06 in tile_budget.py.
    short, off_row = 0, 0
    for r in regions:
        for k in range(rows_tall):
            y = r["y"] + k * rh
            if y not in freed:
                off_row += 1
                continue
            need = set(range(r["x"] // site, r["x"] // site + sites))
            if not need <= freed[y]:
                short += 1
    res.add("A03", "every region covers row sites free of pinned Arm A cells",
            short == 0 and off_row == 0,
            "%d rows short of free sites, %d off any row" % (short, off_row))

    off_grid = sum(1 for r in regions if r["x"] % site)
    res.add("A04", "every region starts on the site grid", off_grid == 0,
            "%d off the grid" % off_grid)

    hits = 0
    for r in regions:
        for m in design.macros:
            if (r["x"] < m.x + 60000 and m.x < r["x"] + rw
                    and r["y"] < m.y + 40000 and m.y < r["y"] + rhgt):
                hits += 1
    res.add("A05", "no region overlaps a macro", hits == 0,
            "%d overlaps" % hits)

    cell = cost["measured"]["arm_a"]["area_per_ring_um2"]
    dens = cell / um2(rw * rhgt, u)
    target = cost["measured"]["arm_a"]["density"]["mean"]
    res.add("A06", "the region density matches Arm A's mean to within a point",
            abs(dens - target) <= 0.01,
            "%.5f against %.5f" % (dens, target))

    # What a ring needs is measured off the pinned cells, not taken from a
    # constant, so this holds on any design the script is pointed at.
    per_ring = collections.defaultdict(int)
    for c in arma:
        mo = re.match(r"u_puf\.u_core\.g_ro_bank\[(\d+)\]",
                      tb.unescape(c.inst))
        if mo:
            per_ring[int(mo.group(1))] += widths.get(c.master, 0)
    need = max(per_ring.values()) if per_ring else 0
    res.add("A07", "a ring's cells fit inside a region's row length",
            need <= rw * rows_tall,
            "%d dbu of cells in %d dbu of row" % (need, rw * rows_tall))

    where = collections.Counter(r["where"] for r in regions)
    res.add("A08", "the regions are split across the die as declared",
            all(where[k] == v for k, v in quota),
            ", ".join("%s %d" % (k, where[k]) for k, _v in quota))

    total = um2(len(regions) * rw * rhgt, u)
    free = cost["free_area_um2"]
    res.add("A09", "the regions fit the free area with the G.2 reserve intact",
            total <= 0.75 * free,
            "%.1f um2, %.2f%% of %.1f" % (total, 100 * total / free, free))

    sel = verilog_select(N_RINGS, 3)
    res.add("A10", "three arms of sixteen need one more select bit than two",
            sel["select_bits"] == 6 and sel["arm_bits"] == 2
            and sel["idx_bits"] == 4,
            "%d oscillators, %d bits" % (sel["oscillators"],
                                         sel["select_bits"]))

    res.add("A11", "all 512 Arm A cells are pinned, none left out",
            len(arma) == 512, "%d cells" % len(arma))
    return res


# ------------------------------------------------------------------ fixture

def fixture_design():
    """The tile_budget fixture, which already has one Arm A ring on four
    strip rows and a 4x4 macro grid. Enough to exercise every check that is
    about geometry rather than about sixteen of something."""
    return tb.parse_def(tb.make_fixture())[0]


def run_fixture(sites=12, rows_tall=2, quota=(("band_low", 2),), n=2,
                gap=0, mutate_regions=None, mutate_design=None,
                mutate_cost=None):
    d = fixture_design()
    if mutate_design:
        d = mutate_design(d)
    w, _ = tb.recover_widths(d)
    spans, widest = row_table(d)
    freed, _ = free_sites(d, w, spans)
    arma = [c for c in d.onrow if tb.classify(c.master, c.inst) == "arma_ring"]
    slots = candidate_slots(d, spans, freed, widest, sites,
                            rows_tall=rows_tall, gap=gap)
    cen = (sum(c.x for c in arma) / max(len(arma), 1),
           sum(c.y for c in arma) / max(len(arma), 1))
    regions = pick_slots(slots, cen, quota=quota, n=n)
    if mutate_regions:
        regions = mutate_regions(list(regions))
    site = d.rows[0].step
    rh = d.row_height
    cell = 120.1152
    area = um2(sites * site * rows_tall * rh, d.units)
    cost = {"measured": {"arm_a": {"area_per_ring_um2": cell,
                                   "density": {"mean": cell / area}}},
            "free_area_um2": 1e6}
    if mutate_cost:
        mutate_cost(cost)
    res = run_checks(d, w, regions, sites, arma, cost, freed, spans,
                     rows_tall=rows_tall, quota=quota)
    return res, regions, d, w, freed, spans, arma, cost


def selftest():
    print("gen_armc selftest")
    ok = True
    # The fixture has one ring and two regions, so the two checks that count
    # sixteen of something cannot pass on it. They are excused by name rather
    # than quietly, and each is exercised on the real design instead.
    excused = {"A01", "A11"}
    res, regions, d, w, freed, spans, arma, cost = run_fixture()
    dirty = set(res.failed()) - excused
    if dirty:
        print("  FAIL: clean fixture fails %s" % ", ".join(sorted(dirty)))
        for r in res.rows:
            if not r["pass"] and r["id"] in dirty:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  clean fixture passes %d of %d checks (A01 and A11 count "
              "sixteen rings and 512 cells; the fixture has one and eight)"
              % (len(res.rows) - len(excused), len(res.rows)))

    def dup(rs):
        return [rs[0], dict(rs[0])]

    def shove(rs):
        rs[1] = dict(rs[1], x=rs[1]["x"] + 1)
        return rs

    def onto_arma(rs):
        a = sorted(arma, key=lambda c: (c.y, c.x))[0]
        rs[1] = dict(rs[1], x=a.x, y=a.y)
        return rs

    def off_row(rs):
        rs[1] = dict(rs[1], y=rs[1]["y"] + 1)
        return rs

    def macro_onto_region(design):
        # One macro moved on top of where the regions land. Moving a region
        # onto a macro instead would put it off the rows as well, and A03
        # would answer for it.
        moved, done = [], False
        for c in design.comps:
            if c.master == tb.MACRO_MASTER and not done:
                moved.append(c._replace(x=tb.FX_ROW_X, y=8160))
                done = True
            else:
                moved.append(c)
        return tb.Design(design.units, design.die, design.rows, moved)

    faults = [
        ("A02", "two regions on the same rectangle", dict(mutate_regions=dup)),
        ("A03", "a region dropped on a pinned Arm A cell",
         dict(mutate_regions=onto_arma)),
        ("A03", "a region parked between two rows",
         dict(mutate_regions=off_row)),
        ("A04", "a region a single unit off the site grid",
         dict(mutate_regions=shove)),
        ("A05", "the macro array moved on top of the regions",
         dict(mutate_design=macro_onto_region)),
        ("A06", "a region far looser than the density Arm A reached",
         dict(mutate_cost=lambda c: c["measured"]["arm_a"]["density"].update(
             mean=0.9))),
        ("A07", "a region too short to hold the ring's cells",
         dict(sites=2, quota=(("band_low", 1),), n=1)),
        ("A08", "a quota the die cannot fill",
         dict(quota=(("band_low", 2), ("strip", 1)), n=3)),
    ]
    for want, label, kwargs in faults:
        r2 = run_fixture(**kwargs)[0]
        tripped = set(r2.failed()) - excused
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

    # A09 and A10 cannot be reached from the fixture's geometry. A09 guards
    # the G.2 reserve and A10 is arithmetic on the arm count, so both are
    # faulted from their own side.
    r3 = run_fixture()[0]
    d3 = fixture_design()
    w3, _ = tb.recover_widths(d3)
    spans3, _ = row_table(d3)
    freed3, _ = free_sites(d3, w3, spans3)
    arma3 = [c for c in d3.onrow
             if tb.classify(c.master, c.inst) == "arma_ring"]
    tiny = {"measured": {"arm_a": {"area_per_ring_um2": 120.1152,
                                   "density": {"mean": 120.1152 / um2(
                                       12 * 460 * 2 * 2720, d3.units)}}},
            "free_area_um2": 1.0}
    r4 = run_checks(d3, w3, r3 and [] or [], 12, arma3, tiny, freed3, spans3,
                    rows_tall=2, quota=())
    _, regions5, d5, w5, freed5, spans5, arma5, cost5 = run_fixture()
    r5 = run_checks(d5, w5, regions5, 12, arma5, tiny, freed5, spans5,
                    rows_tall=2, quota=(("band_low", 2),))
    if set(r5.failed()) - excused == {"A09"}:
        print("  ok    A09  regions larger than the free area allows")
    else:
        print("  FAIL  A09  tripped %s"
              % (", ".join(sorted(set(r5.failed()) - excused)) or "nothing"))
        ok = False

    global N_RINGS
    keep = N_RINGS
    N_RINGS = 24
    r6 = run_fixture()[0]
    N_RINGS = keep
    if "A10" in set(r6.failed()):
        print("  ok    A10  an arm size the select width cannot carry")
    else:
        print("  FAIL  A10  did not trip on 24 rings an arm")
        ok = False

    # The width chooser, against arithmetic that does not call it.
    for target in (0.35, 0.4276, 0.55):
        sites, area, dens = choose_width(target, 120.1152, 4, 460, 2720, 1000)
        near = min(abs(120.1152 / um2(s * 460 * 4 * 2720, 1000) - target)
                   for s in range(4, 400))
        assert abs(abs(dens - target) - near) < 1e-12, (target, sites)
    print("  ok    width  the chooser lands on the closest integer width")

    sel = verilog_select(16, 3)
    good = (sel == {"oscillators": 48, "select_bits": 6, "arm_bits": 2,
                    "idx_bits": 4})
    print("  %-5s select 48 oscillators need 6 bits, 2 of them the arm"
          % ("ok" if good else "FAIL"))
    ok = ok and good

    print("\n  %s" % ("all faults isolated" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------- main

def load():
    paths = {"def": os.path.join(BUILD, tb.DESIGN + ".def"),
             "cost": COST_JSON}
    for p in paths.values():
        if not os.path.exists(p):
            raise SystemExit("missing input: %s" % p)
    with open(paths["def"], "r", encoding="utf-8") as fh:
        design, _ = tb.parse_def(fh.read())
    with open(paths["cost"], "r", encoding="utf-8") as fh:
        cost = json.load(fh)
    widths, _ = tb.recover_widths(design)
    return design, widths, cost, paths


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json")
    ap.add_argument("--emit", help="directory for the generated tcl and rtl")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    design, widths, cost, paths = load()
    site = design.rows[0].step
    rh = design.row_height
    u = design.units
    spans, widest = row_table(design)
    freed, blocked = free_sites(design, widths, spans)
    arma = [c for c in design.onrow
            if tb.classify(c.master, c.inst) == "arma_ring"]
    centroid = (sum(c.x for c in arma) / float(len(arma)),
                sum(c.y for c in arma) / float(len(arma)))

    target = cost["measured"]["arm_a"]["density"]["mean"]
    cell = cost["measured"]["arm_a"]["area_per_ring_um2"]
    sites, area, dens = choose_width(target, cell, ROWS_TALL, site, rh, u)
    slots = candidate_slots(design, spans, freed, widest, sites)
    regions = pick_slots(slots, centroid)
    res = run_checks(design, widths, regions, sites, arma, cost, freed, spans)

    rw, rhgt = sites * site, ROWS_TALL * rh
    print("Arm C build kit")
    print("  region  %.2f x %.2f um, %d sites by %d rows, %.4f um2"
          % (um(rw, u), um(rhgt, u), sites, ROWS_TALL, um2(rw * rhgt, u)))
    print("          density %.5f against Arm A's mean %.5f"
          % (dens, target))
    print("  Arm A   %d cells pinned, centroid %.2f %.2f um"
          % (len(arma), um(centroid[0], u), um(centroid[1], u)))
    counts = collections.Counter(s["where"] for s in slots)
    print("  slots   %d available: %s"
          % (len(slots), ", ".join("%s %d" % kv for kv in sorted(
              counts.items()))))
    print()
    print("  %-4s %-10s %10s %10s %10s %10s"
          % ("ring", "where", "x0 um", "y0 um", "x1 um", "y1 um"))
    for i, r in enumerate(regions):
        print("  %-4d %-10s %10.3f %10.3f %10.3f %10.3f"
              % (i, r["where"], um(r["x"], u), um(r["y"], u),
                 um(r["x"] + rw, u), um(r["y"] + rhgt, u)))
    print()
    for r in res.rows:
        print("  %-4s %-58s %s" % (r["id"], r["name"],
                                   "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    for r in res.rows:
        if not r["pass"]:
            print("       %s: %s" % (r["id"], r["detail"]))

    if a.emit:
        if not os.path.isdir(a.emit):
            os.makedirs(a.emit)
        files = {
            "armc_place.tcl": (tcl_pin_arm_a(design, widths, arma) + "\n"
                               + tcl_regions(design, regions, sites)),
            "ro_armc.v": verilog_ring(),
        }
        for name, body in sorted(files.items()):
            with open(os.path.join(a.emit, name), "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(body)
            print("  wrote %s" % os.path.join(a.emit, name))

    if a.json:
        sel = verilog_select(N_RINGS, 3)
        out = {
            "rings": N_RINGS,
            "region": {"sites": sites, "rows": ROWS_TALL,
                       "width_um": round(um(rw, u), 3),
                       "height_um": round(um(rhgt, u), 3),
                       "area_um2": round(um2(rw * rhgt, u), 4),
                       "density": round(dens, 5),
                       "arm_a_mean_density": target},
            "quota": dict(QUOTA),
            "slots_available": dict(collections.Counter(
                s["where"] for s in slots)),
            "arm_a_pinned_cells": len(arma),
            "arm_a_centroid_um": [round(um(centroid[0], u), 3),
                                  round(um(centroid[1], u), 3)],
            "select": sel,
            "regions": [{"index": i, "where": r["where"],
                         "x0_um": round(um(r["x"], u), 3),
                         "y0_um": round(um(r["y"], u), 3),
                         "x1_um": round(um(r["x"] + rw, u), 3),
                         "y1_um": round(um(r["y"] + rhgt, u), 3)}
                        for i, r in enumerate(regions)],
            "total_region_area_um2": round(um2(len(regions) * rw * rhgt, u),
                                           3),
            "free_area_um2": cost["free_area_um2"],
            "source": {"def": tb.sha256_file(paths["def"]),
                       "cost": tb.sha256_file(paths["cost"])},
            "checks": res.rows,
        }
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
