#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""What a third arm costs, priced against what the two existing arms cost.

E.1's checklist wants area, routing, power, mux and interface cost for Arm C
before anything is built. The trap in a study like that is inventing the unit
costs. So none are invented here. Every one is measured off
`dualarm/build_current`, which already contains sixteen automatically placed
rings and sixteen hardened macros wired into the same counter, and the model
then multiplies measured costs by a ring count.

What gets measured:

- Arm A, per ring: cells, standard-cell area, signal nets, routed wire length,
  extracted wire capacitance, and the bounding box the placer actually used.
- Arm B, per macro: the same for the two nets that leave each macro.
- The enable decode: every cell in the transitive fanin of the thirty-two
  oscillator enables, back to the select register and the window enable.
- Routing headroom: routed length per layer against the track capacity the
  DEF itself declares, with each layer's preferred direction derived from
  which way its own wires run rather than assumed.
- Leakage per square micron, from `metrics.json`.

What gets priced, at several sizes each:

- **Arm C**, standard-cell rings under placement and routing equalization.
  The constraint is what costs the area: every ring has to sit in an
  identical fixed region, so the region is charged in full whether cells fill
  it or not. Arm A's own rings are the calibration. They range from 219.0 to
  382.9 um2 of bounding box for the same 120.1 um2 of cells, which is a
  density of 0.31 to 0.55, and that spread is exactly what Arm C exists to
  remove.
- **The load ladder**, the fallback: M otherwise identical rings, rung j
  carrying j deliberate load cells. It needs no placement constraint, because
  the load is a preregistered regressor and layout scatter is residual.

One number this cannot settle is how many femtofarads one load cell adds.
The SPEF is written with `PIN_CAP NONE`, so it carries wire capacitance and
no gate capacitance, and no file in the build has the missing half. That is a
SPICE question and `sim/spice/gono/gen_instance_decks.py` already has the
machinery. It does not block the area answer and it does not block G.2; it
blocks the ladder's rung spacing, which is a build-time number.

Usage:
    python3 armc_cost.py --selftest
    python3 armc_cost.py
    python3 armc_cost.py --json /tmp/armc_cost.json
"""

import argparse
import collections
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import tile_budget as tb                                    # noqa: E402

BUILD = os.path.join(ROOT, "dualarm", "build_current")
BUDGET_JSON = os.path.join(HERE, "TILE_BUDGET.json")

# sky130_fd_sc_hd output pin names, plus the macro's. This is a stated table,
# not a derivation, and A.1 was corrected in August for exactly that habit. It
# is safe here only because it is checked globally: under this table every
# signal net in the design must have exactly one driver, and the only nets
# with none must be the top-level input ports. Both are checks (C01, C02). The
# proper derivation, from the library's own functional views, lives in
# `extraction/ring_topology.py` and belongs in `extraction/cell_library.py`
# when that module is split out.
OUTPUT_PINS = frozenset(("X", "Y", "Q", "Q_N", "SUM", "COUT", "COUT_N",
                         "HI", "LO", "out"))

ROUTING_LAYERS = ("li1", "met1", "met2", "met3", "met4", "met5")

ARM_A_NET = re.compile(r"^u_puf\.u_core\.g_ro_bank\[(\d+)\]\.u_ro\.(.+)$")
ARM_B_NET = re.compile(r"^armb_(en|out)\[(\d+)\]$")

# Where the enable decode stops. Beyond these the logic is the window timer
# and the pin synchronizers, which a third arm does not change.
DECODE_BOUNDARY = re.compile(
    r"^u_puf\.u_core\.(active_sel\[\d+\]|en_window)$")

# Ring counts to price. Eight is E.1's stated floor for a comparison worth
# making; sixteen matches the two arms already on the die.
SIZES = (8, 12, 16)

# Region densities to price Arm C at, taken from what the placer achieved on
# Arm A without any constraint: its tightest ring, its mean, and its loosest.
DENSITY_LABELS = ("tight", "mean", "loose")


def pct(a, b):
    return 100.0 * a / b if b else float("nan")


# ------------------------------------------------------------ DEF: routing

TRACK_RE = re.compile(
    r"^TRACKS (X|Y) (-?\d+) DO (\d+) STEP (\d+) LAYER (\S+) ;", re.M)
NETS_RE = re.compile(r"^NETS (\d+) ;$(.*?)^END NETS", re.S | re.M)
POINT_RE = re.compile(r"\(\s*(\*|-?\d+)\s+(\*|-?\d+)\s*\)")


def parse_tracks(text):
    """Track declarations. `TRACKS X` means tracks are spaced along x, so the
    wires that sit on them run vertically."""
    out = collections.defaultdict(dict)
    for d, start, n, step, layer in TRACK_RE.findall(text):
        out[layer][d] = {"start": int(start), "count": int(n),
                         "step": int(step)}
    return dict(out)


def parse_routing(text):
    """Every signal net's routed length, split by layer and by direction.

    A DEF routing path is a layer name and a run of points, where `*` repeats
    the previous coordinate. Segments are Manhattan, so a step contributes its
    x delta to the horizontal total and its y delta to the vertical one. A
    single-point entry is a via, not a wire, and contributes nothing.
    """
    ms = NETS_RE.search(text)
    if not ms:
        raise ValueError("no NETS section")
    nets = {}
    bbox = [None, None, None, None]
    for chunk in re.split(r"\n    - ", "\n" + ms.group(2)):
        if not chunk.strip():
            continue
        name = tb.unescape(chunk.split()[0])
        horiz = collections.Counter()
        vert = collections.Counter()
        for path in re.split(r"\bNEW\b|\+ ROUTED", chunk)[1:]:
            toks = path.split()
            if not toks or toks[0] not in ROUTING_LAYERS:
                continue
            layer = toks[0]
            prev = None
            for px, py in POINT_RE.findall(path):
                if prev is None:
                    if px == "*" or py == "*":
                        continue
                    prev = (int(px), int(py))
                    _grow(bbox, prev)
                    continue
                x = prev[0] if px == "*" else int(px)
                y = prev[1] if py == "*" else int(py)
                horiz[layer] += abs(x - prev[0])
                vert[layer] += abs(y - prev[1])
                prev = (x, y)
                _grow(bbox, prev)
        nets[name] = {"h": dict(horiz), "v": dict(vert)}
    return nets, int(ms.group(1)), tuple(bbox)


def _grow(bbox, p):
    if bbox[0] is None:
        bbox[0], bbox[1], bbox[2], bbox[3] = p[0], p[1], p[0], p[1]
        return
    bbox[0] = min(bbox[0], p[0])
    bbox[1] = min(bbox[1], p[1])
    bbox[2] = max(bbox[2], p[0])
    bbox[3] = max(bbox[3], p[1])


def net_length(entry):
    return sum(entry["h"].values()) + sum(entry["v"].values())


# --------------------------------------------------------- netlist as graph

NL_INST_RE = re.compile(
    r"^\s*(sky130_fd_sc_hd__\w+|ro_macro_hard)\s+(\\?\S+?)\s*\((.*?)\)\s*;",
    re.S | re.M)
NL_CONN_RE = re.compile(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)")


def parse_netlist(text):
    """Instances with their pin-to-net connections, and the driver and sink
    tables that follow from the output-pin list above."""
    insts = {}
    for m in NL_INST_RE.finditer(text):
        name = tb.unescape(m.group(2)).strip()
        conns = [(p, tb.unescape(n).strip())
                 for p, n in NL_CONN_RE.findall(m.group(3))]
        insts[name] = {"master": m.group(1), "conns": conns}
    drivers = collections.defaultdict(list)
    sinks = collections.defaultdict(list)
    for name, info in insts.items():
        for pin, net in info["conns"]:
            if not net or net.startswith("1'b"):
                continue
            (drivers if pin in OUTPUT_PINS else sinks)[net].append((name, pin))
    return insts, dict(drivers), dict(sinks)


def fanin_cone(insts, drivers, targets, boundary):
    """Every instance in the transitive fanin of `targets`, and every net the
    walk halted on.

    It halts on two things: a net the boundary pattern matches, and a net with
    no driver. Returning both together is what lets C09 say the decode ends at
    the select register rather than wandering off into the clock tree.
    """
    cone = set()
    seen = set()
    stopped = set()
    stack = list(targets)
    while stack:
        net = stack.pop()
        if net in seen:
            continue
        seen.add(net)
        if boundary.match(net) or net not in drivers:
            stopped.add(net)
            continue
        for name, _pin in drivers[net]:
            if name in cone:
                continue
            cone.add(name)
            for pin, nn in insts[name]["conns"]:
                if pin not in OUTPUT_PINS and nn and not nn.startswith("1'b"):
                    stack.append(nn)
    return cone, stopped


# ------------------------------------------------------------------- SPEF

SPEF_NAME_RE = re.compile(r"^\*(\d+) (\S+)$", re.M)
SPEF_DNET_RE = re.compile(r"^\*D_NET\s+(\S+)\s+([\d.eE+-]+)", re.M)
SPEF_FLOW_RE = re.compile(r"^\*DESIGN_FLOW(.*)$", re.M)


def parse_spef(text):
    """Total capacitance per net, with the name map resolved.

    The header says `PIN_CAP NONE`, so these are wire capacitances with no
    gate capacitance in them. That is recorded rather than glossed, because
    the load ladder's rung spacing needs the half that is missing.
    """
    names = dict(SPEF_NAME_RE.findall(text))
    flow = SPEF_FLOW_RE.search(text)
    pin_cap = "PIN_CAP NONE" not in (flow.group(1) if flow else "")

    def resolve(tok):
        return tb.unescape(
            re.sub(r"\*(\d+)", lambda m: names.get(m.group(1), m.group(0)),
                   tok))

    caps = dict((resolve(k), float(v)) for k, v in SPEF_DNET_RE.findall(text))
    return caps, pin_cap


# ------------------------------------------------------------- measurement

def measure(design, widths, routing, tracks, insts, drivers, sinks, caps,
            metrics, positions):
    """Every unit cost the model multiplies, plus the checks behind them."""
    res = tb.Results()
    u = design.units
    dbu = float(u)
    rh = design.row_height
    x0, y0, x1, y1 = design.die

    # ------------------------------------------------------ the driver table
    multi = sorted(n for n, v in drivers.items() if len(v) > 1)
    res.add("C01", "every net has exactly one driver under the pin table",
            not multi, "%d with more than one: %s"
            % (len(multi), ", ".join(multi[:3])))

    undriven = sorted(n for n in sinks if n not in drivers)
    ports = [n for n in undriven
             if re.match(r"^(clk|ena|rst_n|ui_in\[\d+\]|uio_in\[\d+\])$", n)]
    res.add("C02", "the only undriven nets are top-level input ports",
            len(undriven) == len(ports),
            "%d undriven, %d of them ports: %s"
            % (len(undriven), len(ports),
               ", ".join(n for n in undriven if n not in ports)[:60]
               or "none left over"))

    def_names = set(tb.unescape(c.inst) for c in design.comps)
    res.add("C03", "the DEF and the netlist hold the same instances",
            def_names == set(insts),
            "%d in DEF, %d in netlist, %d differ"
            % (len(def_names), len(insts),
               len(def_names ^ set(insts))))

    # ------------------------------------------------------------ Arm A ring
    ring_cells = collections.defaultdict(list)
    for c in design.cells:
        m = re.match(r"u_puf\.u_core\.g_ro_bank\[(\d+)\]", tb.unescape(c.inst))
        if m:
            ring_cells[int(m.group(1))].append(c)
    ring_nets = collections.defaultdict(list)
    ring_inner = collections.defaultdict(float)
    for name in routing:
        m = ARM_A_NET.match(name)
        if m:
            ring_nets[int(m.group(1))].append(name)
            if m.group(2).startswith("n["):
                ring_inner[int(m.group(1))] += caps.get(name, 0.0)

    ncells = set(len(v) for v in ring_cells.values())
    nnets = set(len(v) for v in ring_nets.values())
    res.add("C04", "every Arm A ring has the same cell count and net count",
            len(ring_cells) == 16 and ncells == {32} and nnets == {33},
            "%d rings, cells %s, nets %s"
            % (len(ring_cells), sorted(ncells), sorted(nnets)))

    _, prows = positions
    worst = 0.0
    for p in prows:
        got = ring_inner.get(int(p["ro"]), 0.0) * 1000.0
        worst = max(worst, abs(got - float(p["ring_cap_fF"])))
    res.add("C05", "the SPEF's ring nodes reproduce dualarm_positions.csv",
            worst < 0.01, "worst disagreement %.4f fF" % worst)

    # ------------------------------------------------------------- routing
    bad_seg = not (x0 <= routing_bbox[0] and y0 <= routing_bbox[1]
                   and routing_bbox[2] <= x1 and routing_bbox[3] <= y1) \
        if routing_bbox[0] is not None else True
    res.add("C06", "every routed wire lies inside DIEAREA", not bad_seg,
            "routing bbox %s, die %s" % (routing_bbox, design.die))

    per_layer = collections.Counter()
    per_dir = collections.defaultdict(collections.Counter)
    for entry in routing.values():
        for layer, v in entry["h"].items():
            per_layer[layer] += v
            per_dir[layer]["h"] += v
        for layer, v in entry["v"].items():
            per_layer[layer] += v
            per_dir[layer]["v"] += v

    layers = {}
    lopsided = []
    over = []
    for layer in sorted(per_layer):
        if not per_layer[layer]:
            continue
        h, v = per_dir[layer]["h"], per_dir[layer]["v"]
        pref = "h" if h >= v else "v"
        share = max(h, v) / float(h + v)
        if share < 0.90:
            lopsided.append("%s %.2f" % (layer, share))
        # A horizontal wire rides a track spaced along y, and vice versa.
        decl = tracks.get(layer, {}).get("Y" if pref == "h" else "X")
        if decl is None:
            lopsided.append("%s has no tracks for %s" % (layer, pref))
            continue
        span = (x1 - x0) if pref == "h" else (y1 - y0)
        cap = decl["count"] * span
        if per_layer[layer] > cap:
            over.append(layer)
        layers[layer] = {
            "routed_um": round(per_layer[layer] / dbu, 3),
            "horizontal_um": round(h / dbu, 3),
            "vertical_um": round(v / dbu, 3),
            "preferred": pref,
            "tracks": decl["count"],
            "track_pitch_um": round(decl["step"] / dbu, 3),
            "capacity_um": round(cap / dbu, 1),
            "utilisation_pct": round(pct(per_layer[layer], cap), 3),
        }
    res.add("C07", "each routed layer runs one way and has tracks for it",
            not lopsided, "; ".join(lopsided) or "none")
    res.add("C08", "no layer's routed length exceeds its track capacity",
            not over, ", ".join(over) or "none")

    # -------------------------------------------------------- enable decode
    targets = ["u_puf.u_core.g_ro_bank[%d].u_ro.en" % i for i in range(16)]
    targets += ["armb_en[%d]" % i for i in range(16)]
    missing = [t for t in targets if t not in drivers]
    cone, stopped = fanin_cone(insts, drivers, targets, DECODE_BOUNDARY)
    strayed = sorted(n for n in stopped if not DECODE_BOUNDARY.match(n))
    res.add("C09", "the decode cone covers all 32 enables and stops at select",
            not missing and bool(cone) and not strayed,
            "%d enables undriven, %d cells, stopped at %s"
            % (len(missing), len(cone),
               ", ".join(sorted(stopped)[:4]) or "nothing"))

    decode_area = sum(widths.get(insts[c]["master"], 0) * rh for c in cone)
    decode_masters = collections.Counter(insts[c]["master"] for c in cone)
    per_ro = decode_masters.get("sky130_fd_sc_hd__and3_2", 0)
    shared = len(cone) - per_ro

    # ------------------------------------------------------------ unit costs
    ring_area = sum(widths.get(c.master, 0) * rh
                    for cs in ring_cells.values() for c in cs)
    ring_route = dict(
        (i, sum(net_length(routing[n]) for n in ring_nets[i]))
        for i in ring_cells)
    boxes = {}
    for i, cs in ring_cells.items():
        bx0 = min(c.x for c in cs)
        bx1 = max(c.x + widths.get(c.master, 0) for c in cs)
        by0 = min(c.y for c in cs)
        by1 = max(c.y for c in cs) + rh
        cells = sum(widths.get(c.master, 0) * rh for c in cs)
        boxes[i] = {"area": (bx1 - bx0) * (by1 - by0),
                    "rows": len(set(c.y for c in cs)),
                    "density": cells / float((bx1 - bx0) * (by1 - by0))}
    dens = sorted(b["density"] for b in boxes.values())
    densities = dict(zip(DENSITY_LABELS,
                         (dens[-1], sum(dens) / len(dens), dens[0])))

    b_nets = [n for n in routing if ARM_B_NET.match(n)]
    b_route = sum(net_length(routing[n]) for n in b_nets)
    b_cap = sum(caps.get(n, 0.0) for n in b_nets)

    arm_a = {
        "rings": len(ring_cells),
        "cells_per_ring": max(ncells) if ncells else 0,
        "nets_per_ring": max(nnets) if nnets else 0,
        "area_per_ring_um2": round(um(ring_area, u) / len(ring_cells), 4),
        "routed_per_ring_um": round(
            sum(ring_route.values()) / dbu / len(ring_cells), 3),
        "routed_per_ring_range_um": [round(min(ring_route.values()) / dbu, 3),
                                     round(max(ring_route.values()) / dbu, 3)],
        "wire_cap_per_ring_fF": round(
            1000.0 * sum(ring_inner.values()) / len(ring_inner), 4),
        "bbox_um2": {"min": round(um(min(b["area"] for b in boxes.values()),
                                     u), 2),
                     "max": round(um(max(b["area"] for b in boxes.values()),
                                     u), 2),
                     "mean": round(um(sum(b["area"] for b in boxes.values())
                                      / len(boxes), u), 2)},
        "density": dict((k, round(v, 4)) for k, v in densities.items()),
        "rows_spanned": sorted(set(b["rows"] for b in boxes.values())),
    }
    arm_b = {
        "macros": 16,
        "nets_per_macro": len(b_nets) // 16,
        "die_area_per_macro_um2": 60.0 * 40.0,
        "routed_per_macro_um": round(b_route / dbu / 16, 3),
        "wire_cap_per_macro_fF": round(1000.0 * b_cap / 16, 4),
    }
    decode = {
        "cells": len(cone),
        "stops_at": sorted(stopped),
        "area_um2": round(um(decode_area, u), 4),
        "per_oscillator_gates": per_ro,
        "shared_cells": shared,
        "masters": dict(sorted(decode_masters.items())),
    }

    leak = metrics.get("power__leakage__total", 0.0)
    placed = metrics.get("design__instance__area", 1.0)
    power = {
        "leakage_total_W": leak,
        "leakage_per_um2_pW": round(leak * 1e12 / placed, 6),
        "internal_W": metrics.get("power__internal__total"),
        "switching_W": metrics.get("power__switching__total"),
        "total_W": metrics.get("power__total"),
    }
    return res, {"arm_a": arm_a, "arm_b": arm_b, "decode": decode,
                 "layers": layers, "power": power,
                 "routed_total_um": round(sum(per_layer.values()) / dbu, 3),
                 "signal_nets": len(routing)}


def um(dbu_area, units):
    return dbu_area / float(units) / float(units)


routing_bbox = (None, None, None, None)


# ---------------------------------------------------------------- the model

def price(meas, free_um2, inv_area_um2, and3_area_um2, and4_area_um2,
          existing_ros=32):
    """Both options at every size in SIZES. Nothing here reads a file."""
    a = meas["arm_a"]
    cell = a["area_per_ring_um2"]
    route = a["routed_per_ring_um"]
    decode = meas["decode"]

    def interface(n):
        total = existing_ros + n
        bits = int(math.ceil(math.log(total, 2)))
        return {"oscillators": total,
                "select_bits": bits,
                "extra_select_bits": bits - int(math.ceil(
                    math.log(existing_ros, 2))),
                "per_oscillator_gate_um2": (and3_area_um2 if bits <= 5
                                            else and4_area_um2),
                "decode_area_um2": round(
                    total * (and3_area_um2 if bits <= 5 else and4_area_um2)
                    + decode["shared_cells"] * decode["area_um2"]
                    / max(decode["cells"], 1), 3)}

    out = {"armc": [], "ladder": []}
    for n in SIZES:
        iface = interface(n)
        added_decode = iface["decode_area_um2"] - decode["area_um2"]
        for label in DENSITY_LABELS:
            region = cell / a["density"][label]
            total = n * region + added_decode
            out["armc"].append({
                "rings": n, "density_label": label,
                "density": a["density"][label],
                "region_per_ring_um2": round(region, 3),
                "cells_um2": round(n * cell, 3),
                "region_um2": round(n * region, 3),
                "added_decode_um2": round(added_decode, 3),
                "total_um2": round(total, 3),
                "pct_of_free": round(pct(total, free_um2), 2),
                "fits": total <= free_um2,
                "routed_um": round(n * route, 1),
                "select_bits": iface["select_bits"],
                "extra_select_bits": iface["extra_select_bits"],
            })
        loads = n * (n - 1) // 2
        total = n * cell + loads * inv_area_um2 + added_decode
        out["ladder"].append({
            "rungs": n,
            "load_cells": loads,
            "cells_um2": round(n * cell, 3),
            "load_um2": round(loads * inv_area_um2, 3),
            "added_decode_um2": round(added_decode, 3),
            "total_um2": round(total, 3),
            "pct_of_free": round(pct(total, free_um2), 2),
            "load_share_pct": round(pct(loads * inv_area_um2, total), 2),
            "fits": total <= free_um2,
            "routed_um": round(n * route, 1),
            "select_bits": interface(n)["select_bits"],
            "extra_select_bits": interface(n)["extra_select_bits"],
        })
    return out


def model_checks(res, priced, free_um2):
    """Two things the model itself can get wrong."""
    mono = True
    for key, size_key in (("armc", "rings"), ("ladder", "rungs")):
        for label in (DENSITY_LABELS if key == "armc" else (None,)):
            rows = [r for r in priced[key]
                    if label is None or r["density_label"] == label]
            rows.sort(key=lambda r: r[size_key])
            for x, y in zip(rows, rows[1:]):
                if y["total_um2"] < x["total_um2"]:
                    mono = False
    res.add("C10", "both options cost more as they get bigger", mono,
            "monotone" if mono else "a bigger option came out cheaper")

    wrong = [r for r in priced["armc"] + priced["ladder"]
             if r["fits"] != (r["total_um2"] <= free_um2)]
    res.add("C11", "the fits flag agrees with the free area it is measured on",
            not wrong, "%d rows disagree" % len(wrong))
    return res


# ------------------------------------------------------------------ fixture

def fixture_decode_cells():
    """The decode the fixture needs, as (instance, master, connections).

    Both the fixture DEF and the fixture netlist are generated from this one
    list, which is the only way C03 can hold: the real DEF and the real
    netlist carry the same 6477 instances, physical cells included, and a
    fixture whose two files were written by hand would not.
    """
    sel = ("\\u_puf.u_core.active_sel[0] ", "\\u_puf.u_core.active_sel[1] ",
           "\\u_puf.u_core.en_window ")
    out = [("psel0", "buf_1", ".A(ui_in[0]), .X(%s)" % sel[0]),
           ("psel1", "buf_1", ".A(ui_in[1]), .X(%s)" % sel[1]),
           ("pwin", "buf_1", ".A(ui_in[7]), .X(%s)" % sel[2])]
    for i in range(16):
        out.append(("deca%d" % i, "and3_2",
                    ".A(%s), .B(%s), .C(%s), .X(\\%s[%d].u_ro.en )"
                    % (sel + (ARM_A_PREFIX_ESC, i))))
        out.append(("decb%d" % i, "and3_2",
                    ".A(%s), .B(%s), .C(%s), .X(\\armb_en[%d] )"
                    % (sel + (i,))))
    return out


ARM_A_PREFIX_ESC = tb.ARM_A_PREFIX
FX_DECODE_Y = 15000
FX_DECODE_W = 1380
FX_HOG_RUNGS = 20
FX_HOG_RUN = 25000


def fixture_def_with_routing():
    """The tile_budget fixture, plus the decode cells, plus TRACKS and a NETS
    section whose wires run the right way for their layer."""
    base = tb.make_fixture()
    extra = []
    x = tb.FX_ROW_X
    for name, master, _conns in fixture_decode_cells():
        extra.append("    - %s %s%s + PLACED ( %d %d ) N ;"
                     % (name, tb.CELL_PREFIX, master, x, FX_DECODE_Y))
        x += FX_DECODE_W
    base = base.replace("END COMPONENTS",
                        "\n".join(extra) + "\nEND COMPONENTS")
    base = re.sub(r"^COMPONENTS \d+ ;$",
                  "COMPONENTS %d ;" % len(re.findall(r"^    - ", base, re.M)),
                  base, count=1, flags=re.M)

    tracks = ["TRACKS X 230 DO 400 STEP 340 LAYER met1 ;",
              "TRACKS Y 170 DO 300 STEP 340 LAYER met1 ;",
              "TRACKS X 230 DO 400 STEP 460 LAYER met2 ;",
              "TRACKS Y 230 DO 200 STEP 460 LAYER met2 ;"]
    ring = "%s[0].u_ro" % tb.ARM_A_PREFIX
    entries = [("%s.en" % ring, "met1", (250000, 3000), (256000, 3000)),
               ("%s.n[0]" % ring, "met1", (250000, 6000), (254000, 6000)),
               ("%s.out" % ring, "met2", (250000, 3000), (250000, 9000)),
               ("armb_en[0]", "met1", (10000, 22000), (20000, 22000)),
               ("armb_out[0]", "met2", (10000, 22000), (10000, 30000)),
               ("clk", "met1", (5000, 3000), (9000, 3000))]
    nets = ["NETS %d ;" % (len(entries) + 1)]
    for name, layer, p, q in entries:
        esc = name.replace("[", "\\[").replace("]", "\\]")
        nets.append("    - %s ( x A ) ( y B ) + USE SIGNAL" % esc)
        nets.append("      + ROUTED %s ( %d %d ) ( %d %d ) ;"
                    % (layer, p[0], p[1], q[0], q[1]))
    # One net carrying 500 um of met1, spread over twenty rungs. Without it
    # the fixture routes so little that no track count can be made too small
    # to hold it, and C08 would have no fault to answer to.
    nets.append("    - clknet ( x A ) ( y B ) + USE SIGNAL")
    for i in range(FX_HOG_RUNGS):
        y = 40000 + i * 2000
        nets.append("      %s met1 ( 20000 %d ) ( %d %d )"
                    % ("+ ROUTED" if i == 0 else "NEW", y,
                       20000 + FX_HOG_RUN, y))
    nets[-1] += " ;"
    nets.append("END NETS")
    return base.replace("END DESIGN",
                        "\n".join(tracks) + "\n" + "\n".join(nets)
                        + "\nEND DESIGN")


def fixture_netlist_with_decode():
    """A netlist generated from the fixture DEF, so the two hold the same
    instances. Physical cells get no connections, the ring closes on itself,
    and the decode drives all thirty-two enables."""
    design, _ = tb.parse_def(fixture_def_with_routing())
    ring = "%s[0].u_ro" % tb.ARM_A_PREFIX

    def n(i):
        return "\\%s.n[%d] " % (ring, i)

    wired = dict((name, conns) for name, _m, conns in fixture_decode_cells())
    for suffix, src, dst in (("u_nand", 7, 0), ("g_inv[1].u_inv", 0, 1),
                             ("g_inv[2].u_inv", 1, 2),
                             ("g_inv[3].u_inv", 2, 3), ("u_buf", 3, 4),
                             ("g_inv[4].u_inv", 4, 5),
                             ("g_inv[5].u_inv", 5, 6),
                             ("g_inv[6].u_inv", 6, 7)):
        name = "%s.%s" % (ring, suffix)
        if suffix == "u_nand":
            wired[name] = (".A(\\%s.en ), .B(%s), .Y(%s)"
                           % (ring, n(src), n(dst)))
        elif suffix == "u_buf":
            wired[name] = ".A(%s), .X(%s)" % (n(src), n(dst))
        else:
            wired[name] = ".A(%s), .Y(%s)" % (n(src), n(dst))

    out = ["module fixture (clk, ui_in);", "  input clk;",
           "  input [7:0] ui_in;"]
    for c in design.comps:
        clean = tb.unescape(c.inst)
        if clean in wired:
            out.append("  %s \\%s (%s);" % (c.master, clean, wired[clean]))
        elif c.master == tb.MACRO_MASTER:
            i = int(re.search(r"\d+", clean).group(0))
            out.append("  %s %s (.en(\\armb_en[%d] ), .out(\\armb_out[%d] ));"
                       % (c.master, clean, i, i))
        else:
            out.append("  %s %s ();" % (c.master, clean))
    out.append("endmodule")
    return "\n".join(out) + "\n"


def fixture_spef():
    """Wire capacitance for the fixture's ring, in the same name-mapped shape
    the real SPEF uses, so the map resolution is exercised too."""
    head = ['*SPEF "ieee 1481-1999"', '*DESIGN "fixture"',
            '*DESIGN_FLOW "NAME_SCOPE LOCAL" "PIN_CAP NONE"',
            "*C_UNIT 1 PF", "", "*NAME_MAP"]
    ring = "%s[0].u_ro" % tb.ARM_A_PREFIX
    names = ["%s.n[0]" % ring, "%s.en" % ring, "%s.out" % ring,
             "armb_en[0]", "armb_out[0]"]
    for i, n in enumerate(names, start=3):
        head.append("*%d %s" % (i, n))
    head.append("")
    caps = [0.010, 0.0012, 0.0009, 0.0100, 0.0106]
    for i, c in enumerate(caps, start=3):
        head.append("*D_NET *%d %.6f" % (i, c))
        head.append("*END")
    return "\n".join(head) + "\n"


FIXTURE_POS = "ro,x_um,y_um,ncells,ring_cap_fF\n0,250.0,3.0,8,10.00\n"


def run_fixture(deftext, nltext, speftext, postext, metrics):
    global routing_bbox
    design, _ = tb.parse_def(deftext)
    widths, _ = tb.recover_widths(design)
    routing, declared, bbox = parse_routing(deftext)
    routing_bbox = bbox
    tracks = parse_tracks(deftext)
    insts, drivers, sinks = parse_netlist(nltext)
    caps, _ = parse_spef(speftext)
    return measure(design, widths, routing, tracks, insts, drivers, sinks,
                   caps, metrics, tb.parse_positions(postext))


def fx_two_drivers(d, n, s, p, m):
    # A cell already in both files given a second opinion about a net that
    # already has a driver. Adding a cell to the netlist would have moved the
    # instance sets apart as well, and that is C03's business.
    return d, n.replace("FILLER_2_0 ();",
                        "FILLER_2_0 (.X(\\u_puf.u_core.active_sel[0] ));",
                        1), s, p, m


def fx_orphan_net(d, n, s, p, m):
    # A sink on a net nothing drives and no port supplies, placed on a filler
    # so it sits outside the decode cone. Orphaning a decode input instead
    # would stop the cone walk on it and trip C09 too.
    return d, n.replace("FILLER_3_0 ();", "FILLER_3_0 (.A(nowhere));", 1), \
        s, p, m


def fx_def_netlist_gap(d, n, s, p, m):
    return d, n.replace("  ro_macro_hard u_rob15", "  // u_rob15", 1), \
        s, p, m


def fx_ring_net_count(d, n, s, p, m):
    ring = "%s[0].u_ro" % tb.ARM_A_PREFIX
    esc = ring.replace("[", "\\[").replace("]", "\\]")
    extra = ("    - %s.n\\[9\\] ( x A ) ( y B ) + USE SIGNAL\n"
             "      + ROUTED met1 ( 250000 8000 ) ( 251000 8000 ) ;"
             % esc)
    d2 = d.replace("END NETS", extra + "\nEND NETS")
    return re.sub(r"^NETS \d+ ;$", "NETS 7 ;", d2, count=1, flags=re.M), \
        n, s, p, m


def fx_spef_disagrees(d, n, s, p, m):
    return d, n, s.replace("*3 0.010000", "*3 0.011000", 1) \
        if "*3 0.010000" in s else s.replace("0.010000", "0.011000", 1), p, m


def fx_wire_off_die(d, n, s, p, m):
    return d.replace("( 250000 3000 ) ( 256000 3000 )",
                     "( 250000 3000 ) ( 400000 3000 )", 1), n, s, p, m


def fx_wrong_direction(d, n, s, p, m):
    # Stand every second rung of the long met1 net on its end. The layer then
    # runs half one way and half the other, which is the state C07 exists to
    # notice: a router that has lost track of which grain a layer has. One
    # short wire turned sideways would be lost in the rest of the length.
    state = {"i": 0}

    def flip(mo):
        state["i"] += 1
        y = int(mo.group(2))
        if state["i"] % 2:
            return mo.group(0)
        return "%s met1 ( 20000 %d ) ( 20000 %d )" % (mo.group(1), y,
                                                      y + FX_HOG_RUN)

    return re.sub(r"(NEW|\+ ROUTED) met1 \( 20000 (\d+) \) \( \d+ \d+ \)",
                  flip, d), n, s, p, m


def fx_over_capacity(d, n, s, p, m):
    return d.replace("TRACKS Y 170 DO 300 STEP 340 LAYER met1 ;",
                     "TRACKS Y 170 DO 1 STEP 340 LAYER met1 ;", 1), n, s, p, m


def fx_decode_strays(d, n, s, p, m):
    # One decode gate fed from the clock instead of the window enable. The
    # walk then halts on a net the boundary pattern does not match, which is
    # the only thing C09 can see: every enable is still driven and the clock
    # is a port, so nothing else moves.
    return d, n.replace(".C(\\u_puf.u_core.en_window ), .X(\\armb_en[7] ));",
                        ".C(clk), .X(\\armb_en[7] ));", 1), s, p, m


FIXTURE_FAULTS = [
    ("C01", "two cells driving one enable", fx_two_drivers),
    ("C02", "a sink on a net nothing drives", fx_orphan_net),
    ("C03", "an instance the netlist does not have", fx_def_netlist_gap),
    ("C04", "a ring with an extra net", fx_ring_net_count),
    ("C05", "a SPEF that disagrees with the positions CSV", fx_spef_disagrees),
    ("C06", "a wire routed off the die", fx_wire_off_die),
    ("C07", "a layer routed against its own grain", fx_wrong_direction),
    ("C08", "more wire on a layer than it has track for", fx_over_capacity),
    ("C09", "a decode gate fed from the clock", fx_decode_strays),
]


def selftest():
    d = fixture_def_with_routing()
    n = fixture_netlist_with_decode()
    s = fixture_spef()
    p = FIXTURE_POS
    m = {"design__instance__count": 0, "design__instance__area": 1.0,
         "power__leakage__total": 1e-9, "power__total": 1e-6}
    print("armc_cost selftest")
    res, meas = run_fixture(d, n, s, p, m)
    ok = True
    # C04 and C05 are statements about sixteen rings and this fixture has one,
    # so they are expected to fail on it and are the two faults below that
    # carry their own comparison instead.
    expect_dirty = {"C04", "C05"}
    dirty = set(res.failed()) - expect_dirty
    if dirty:
        print("  FAIL: the clean fixture already fails %s"
              % ", ".join(sorted(dirty)))
        for r in res.rows:
            if not r["pass"] and r["id"] in dirty:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  clean fixture passes %d of %d checks (C04 and C05 count "
              "sixteen rings and the fixture has one)"
              % (len(res.rows) - len(expect_dirty), len(res.rows)))

    for want, label, fn in FIXTURE_FAULTS:
        d2, n2, s2, p2, m2 = fn(d, n, s, p, m)
        try:
            r2, _ = run_fixture(d2, n2, s2, p2, m2)
            tripped = set(r2.failed()) - (expect_dirty - {want})
        except Exception as exc:
            tripped = {"raised(%s)" % exc}
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

    # The two model checks get their faults from a damaged model, not a
    # damaged file, because no input file can reach them.
    fake = {"arm_a": {"area_per_ring_um2": 100.0, "routed_per_ring_um": 10.0,
                      "density": {"tight": 0.5, "mean": 0.4, "loose": 0.3}},
            "decode": {"cells": 52, "area_um2": 400.0, "shared_cells": 20}}
    good = price(fake, 10000.0, 3.75, 7.5, 10.0)
    r3 = model_checks(tb.Results(), good, 10000.0)
    if r3.failed():
        print("  FAIL  model checks fail on a clean model: %s"
              % ", ".join(r3.failed()))
        ok = False
    else:
        print("  ok    C10  C11 pass on a clean model")

    broken = json.loads(json.dumps(good))
    broken["armc"][-1]["total_um2"] = 0.0
    r4 = model_checks(tb.Results(), broken, 10000.0)
    if set(r4.failed()) == {"C10"}:
        print("  ok    C10  a bigger option priced cheaper")
    else:
        print("  FAIL  C10  tripped %s" % ", ".join(r4.failed()))
        ok = False

    broken2 = json.loads(json.dumps(good))
    broken2["ladder"][0]["fits"] = not broken2["ladder"][0]["fits"]
    r5 = model_checks(tb.Results(), broken2, 10000.0)
    if set(r5.failed()) == {"C11"}:
        print("  ok    C11  a fits flag that does not match the area")
    else:
        print("  FAIL  C11  tripped %s" % ", ".join(r5.failed()))
        ok = False

    for label, broken_def in (
            ("no NETS section",
             re.sub(r"^NETS \d+ ;$", "XXX 0 ;", d, count=1, flags=re.M)),):
        try:
            parse_routing(broken_def)
            print("  FAIL  parse accepted a DEF with %s" % label)
            ok = False
        except ValueError:
            print("  ok    parse refuses a DEF with %s" % label)

    print("\n  %s" % ("all faults isolated" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------- main

def load(build):
    global routing_bbox
    paths = {
        "def": os.path.join(build, tb.DESIGN + ".def"),
        "netlist": os.path.join(build, tb.DESIGN + ".nl.v"),
        "spef": os.path.join(build, tb.DESIGN + ".nom.spef"),
        "metrics": os.path.join(build, "metrics.json"),
        "positions": os.path.join(build, "dualarm_positions.csv"),
    }
    for p in paths.values():
        if not os.path.exists(p):
            raise SystemExit("missing input: %s" % p)
    with open(paths["def"], "r", encoding="utf-8") as fh:
        deftext = fh.read()
    design, _ = tb.parse_def(deftext)
    widths, _ = tb.recover_widths(design)
    routing, _, bbox = parse_routing(deftext)
    routing_bbox = bbox
    tracks = parse_tracks(deftext)
    with open(paths["netlist"], "r", encoding="utf-8") as fh:
        insts, drivers, sinks = parse_netlist(fh.read())
    with open(paths["spef"], "r", encoding="utf-8") as fh:
        caps, pin_cap = parse_spef(fh.read())
    with open(paths["metrics"], "r", encoding="utf-8") as fh:
        metrics = json.load(fh)
    with open(paths["positions"], "r", encoding="utf-8") as fh:
        positions = tb.parse_positions(fh.read())
    hashes = dict((k, tb.sha256_file(v)) for k, v in sorted(paths.items()))
    return (design, widths, routing, tracks, insts, drivers, sinks, caps,
            pin_cap, metrics, positions, hashes)


def read_budget(design_hash):
    """Day one's answer, and a check that it describes this DEF."""
    if not os.path.exists(BUDGET_JSON):
        raise SystemExit("run tile_budget.py --json chip/TILE_BUDGET.json "
                         "first")
    with open(BUDGET_JSON, "r", encoding="utf-8") as fh:
        b = json.load(fh)
    same = b.get("source", {}).get("sha256", {}).get("def") == design_hash
    ok_math = abs(b["free"]["area_um2"] + b["free"]["held_area_um2"]
                  - b["rows"]["area_um2"]) < 0.01
    return b, same, ok_math


def report(meas, priced, budget, pin_cap):
    a, b, dec = meas["arm_a"], meas["arm_b"], meas["decode"]
    free = budget["free"]["area_um2"]
    print("Unit costs, measured on dualarm/build_current")
    print("  Arm A   %d rings, %d cells and %d nets each"
          % (a["rings"], a["cells_per_ring"], a["nets_per_ring"]))
    print("          %8.4f um2 of cells a ring" % a["area_per_ring_um2"])
    print("          %8.3f um of wire a ring (%.1f to %.1f)"
          % (a["routed_per_ring_um"], a["routed_per_ring_range_um"][0],
             a["routed_per_ring_range_um"][1]))
    print("          %8.4f fF of ring-node wire capacitance a ring"
          % a["wire_cap_per_ring_fF"])
    print("          bounding box %.1f to %.1f um2, density %.3f to %.3f, "
          "%s rows" % (a["bbox_um2"]["min"], a["bbox_um2"]["max"],
                       a["density"]["loose"], a["density"]["tight"],
                       "-".join(str(r) for r in a["rows_spanned"])))
    print("  Arm B   %d macros, %d nets each, %.3f um of wire a macro"
          % (b["macros"], b["nets_per_macro"], b["routed_per_macro_um"]))
    print("  decode  %d cells, %.2f um2: one %s a oscillator plus %d shared"
          % (dec["cells"], dec["area_um2"], "and3_2", dec["shared_cells"]))
    print()
    print("Routing headroom")
    print("  %-6s %10s %10s %6s %8s %10s %7s"
          % ("layer", "routed um", "capacity", "dir", "tracks", "pitch um",
             "used %"))
    for lay in sorted(meas["layers"]):
        L = meas["layers"][lay]
        print("  %-6s %10.1f %10.1f %6s %8d %10.3f %7.2f"
              % (lay, L["routed_um"], L["capacity_um"], L["preferred"],
                 L["tracks"], L["track_pitch_um"], L["utilisation_pct"]))
    print("  total routed %.1f um over %d signal nets"
          % (meas["routed_total_um"], meas["signal_nets"]))
    print()
    print("Free area from TILE_BUDGET.json: %.3f um2" % free)
    print()
    print("Arm C, standard-cell rings in identical fixed regions")
    print("  %5s %7s %9s %11s %11s %11s %8s %6s"
          % ("rings", "density", "region", "cells um2", "region um2",
             "total um2", "of free", "fits"))
    for r in priced["armc"]:
        print("  %5d %7.3f %9.2f %11.1f %11.1f %11.1f %7.2f%% %6s"
              % (r["rings"], r["density"], r["region_per_ring_um2"],
                 r["cells_um2"], r["region_um2"], r["total_um2"],
                 r["pct_of_free"], "yes" if r["fits"] else "NO"))
    print()
    print("The load ladder, no placement constraint")
    print("  %5s %6s %11s %10s %11s %8s %9s %6s"
          % ("rungs", "loads", "cells um2", "load um2", "total um2", "of free",
             "load part", "fits"))
    for r in priced["ladder"]:
        print("  %5d %6d %11.1f %10.1f %11.1f %7.2f%% %8.1f%% %6s"
              % (r["rungs"], r["load_cells"], r["cells_um2"], r["load_um2"],
                 r["total_um2"], r["pct_of_free"], r["load_share_pct"],
                 "yes" if r["fits"] else "NO"))
    print()
    p = meas["power"]
    print("Power: leakage %.4g W over the placed area, %.4f pW/um2. "
          % (p["leakage_total_W"], p["leakage_per_um2_pW"]))
    print("  A 16-ring Arm C at mean density adds %.4g W of leakage."
          % (p["leakage_per_um2_pW"] * 1e-12
             * [r for r in priced["armc"]
                if r["rings"] == 16 and r["density_label"] == "mean"
                ][0]["total_um2"]))
    print("  Dynamic power does not move: one oscillator runs at a time.")
    print("  These figures are the clocked logic only. A ring is a")
    print("  combinational loop and static analysis does not see it.")
    print()
    print("Interface: %d select bits today, %d with a third arm of 16."
          % (priced["armc"][0]["select_bits"]
             - priced["armc"][0]["extra_select_bits"],
             [r for r in priced["armc"] if r["rings"] == 16][0]["select_bits"]))
    print("  SPEF pin capacitance: %s"
          % ("present" if pin_cap else
             "absent, so no gate capacitance is available here"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", default=BUILD)
    ap.add_argument("--json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    (design, widths, routing, tracks, insts, drivers, sinks, caps, pin_cap,
     metrics, positions, hashes) = load(a.build)
    res, meas = measure(design, widths, routing, tracks, insts, drivers,
                        sinks, caps, metrics, positions)
    budget, same_def, ok_math = read_budget(hashes["def"])
    res.add("C12", "TILE_BUDGET.json describes this DEF and its sums hold",
            same_def and ok_math,
            "def hash %s, free+held=row %s"
            % ("matches" if same_def else "DIFFERS",
               "holds" if ok_math else "FAILS"))

    rh = design.row_height
    areas = dict((m, widths.get(tb.CELL_PREFIX + m, 0) * rh
                  / float(design.units) ** 2)
                 for m in ("inv_1", "and3_2", "and4_2"))
    priced = price(meas, budget["free"]["area_um2"], areas["inv_1"],
                   areas["and3_2"], areas["and4_2"] or areas["and3_2"] * 4 / 3)
    model_checks(res, priced, budget["free"]["area_um2"])

    report(meas, priced, budget, pin_cap)
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

    if a.json:
        out = {"measured": meas, "priced": priced,
               "cell_area_um2": dict((k, round(v, 4))
                                     for k, v in areas.items()),
               "free_area_um2": budget["free"]["area_um2"],
               "spef_has_pin_cap": pin_cap,
               "source": {"build": os.path.relpath(a.build, ROOT).replace(
                   os.sep, "/"), "sha256": hashes},
               "checks": res.rows}
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
