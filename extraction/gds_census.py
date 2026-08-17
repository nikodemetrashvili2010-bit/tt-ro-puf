#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Read the shuttle's published GDS and check it is the die the other files describe.

A.2 was written as an OAS-to-GDS conversion step, with cell counts, bounding box
and top cell surviving the conversion as its acceptance condition. Tiny Tapeout
publishes GDS directly, so there is no conversion and nothing to survive one. The
check the conversion check was standing in for is still worth running: the GDS,
the LEF, the gate-level netlist and the flow's own metrics are four files written
by four stages of one flow, and an attack that reads three of them is entitled to
know they describe the same die.

So this reads the GDS itself — records, transforms, placements and the instance
names the flow left in the property records — and reconciles it against the other
three, one instance at a time. Everything is stdlib; there is no layout library
in the loop that could paper over a disagreement.

Nothing here measures a ring or predicts a response.

    python3 gds_census.py PROJECT [PROJECT ...]     # census and cross-checks
    python3 gds_census.py --json OUT PROJECT ...    # the same, machine readable
    python3 gds_census.py --selftest                # planted faults, no inputs

PROJECT is a shuttle project directory holding <name>.gds, <name>.lef, <name>.v
and stats/metrics.csv, where <name> is the directory's own name.
"""

import argparse
import collections
import csv
import hashlib
import json
import math
import os
import re
import struct
import sys
import tempfile

# GDSII record types. Only the ones this reader acts on are named.
HEADER, BGNLIB, LIBNAME, UNITS, ENDLIB = 0x00, 0x01, 0x02, 0x03, 0x04
BGNSTR, STRNAME, ENDSTR = 0x05, 0x06, 0x07
BOUNDARY, PATH, SREF, AREF, TEXT = 0x08, 0x09, 0x0A, 0x0B, 0x0C
LAYER, DATATYPE, WIDTH, XY, ENDEL = 0x0D, 0x0E, 0x0F, 0x10, 0x11
SNAME, COLROW = 0x12, 0x13
STRANS, MAG, ANGLE = 0x1A, 0x1B, 0x1C
PROPATTR, PROPVALUE = 0x2B, 0x2C
BOX, BOXTYPE = 0x2D, 0x2E

ELEMENTS = (BOUNDARY, PATH, SREF, AREF, TEXT, BOX)
GEOMETRY = (BOUNDARY, PATH, BOX)

# The flow writes the placer's instance name into property 61 of every
# placement. That is the hook the whole netlist comparison below hangs on.
PROP_INSTANCE_NAME = 61

# sky130 layer purposes used here. 235 is prBoundary, which the top cell carries
# as the die outline; 236 is the standard cell outline, which the physical
# filler cells do not carry at all.
DIE_OUTLINE_LAYER = 235
CELL_OUTLINE_LAYER = 236

# How the flow's own metrics split the placed cells. The classification is on
# the master name because that is all the GDS gives.
PHYSICAL_KINDS = (
    ("fill", "__fill"),
    ("decap", "__decap"),
    ("tap", "__tap"),
    ("diode", "__diode"),
)

# The netlist parse is deliberately not shared with ring_census.py. If the two
# ever disagree about how many cells a netlist holds, that is a finding.
NETLIST_CELL_RE = re.compile(r"(sky130_\w+)\s+(\\?\S+)\s*\(", re.S)
LEF_MACRO_RE = re.compile(r"\bMACRO\s+(\S+)(.*?)\bEND\s+\1\b", re.S)
LEF_SIZE_RE = re.compile(r"\bSIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;")

MM2_TOLERANCE = 1e-9  # mm^2, against the flow's own printed die area


# --------------------------------------------------------------------------
# GDSII


def decode_real8(raw):
    """Excess-64 floating point, the format GDSII stores UNITS in."""
    exponent = (raw[0] & 0x7F) - 64
    mantissa = int.from_bytes(raw[1:8], "big") / float(1 << 56)
    value = mantissa * (16.0 ** exponent)
    return -value if raw[0] & 0x80 else value


def encode_real8(value):
    """The inverse, used only to build selftest fixtures."""
    if value == 0:
        return b"\x00" * 8
    sign = 0x80 if value < 0 else 0
    value = abs(value)
    exponent = 0
    while value >= 1.0:
        value /= 16.0
        exponent += 1
    while value < 1.0 / 16.0:
        value *= 16.0
        exponent -= 1
    mantissa = int(round(value * (1 << 56)))
    if mantissa >= (1 << 56):  # rounding pushed it out of range
        mantissa >>= 4
        exponent += 1
    return bytes([sign | (exponent + 64)]) + mantissa.to_bytes(7, "big")


def records(path):
    """Yield (record_type, data_type, payload) over a GDSII stream."""
    with open(path, "rb") as fh:
        while True:
            head = fh.read(4)
            if len(head) < 4:
                return
            length, rtype, dtype = struct.unpack(">HBB", head)
            if length < 4:
                raise ValueError("record length %d at byte %d is impossible"
                                 % (length, fh.tell() - 4))
            payload = fh.read(length - 4) if length > 4 else b""
            if len(payload) != length - 4:
                raise ValueError("stream ends inside a record")
            yield rtype, dtype, payload


def _name(payload):
    return payload.rstrip(b"\x00").decode("ascii", "replace")


class Structure(object):
    def __init__(self, name):
        self.name = name
        self.boxes = collections.defaultdict(list)  # layer -> [(x0,y0,x1,y1)]
        self.refs = []                              # Placement


class Placement(object):
    def __init__(self, master, origin, mirror, angle, mag, inst):
        self.master = master
        self.origin = origin
        self.mirror = mirror
        self.angle = angle
        self.mag = mag
        self.inst = inst


def read_gds(path):
    """Parse a GDSII file into structures, placements and instance names."""
    structures = collections.OrderedDict()
    units = None
    libname = None
    current = None
    element = layer = None
    sname = inst = None
    mirror = False
    angle, mag = 0.0, 1.0
    colrow = points = None
    attr = None
    arefs = 0

    for rtype, dtype, payload in records(path):
        if rtype == UNITS:
            units = (decode_real8(payload[0:8]), decode_real8(payload[8:16]))
        elif rtype == LIBNAME:
            libname = _name(payload)
        elif rtype == STRNAME:
            current = Structure(_name(payload))
            if current.name in structures:
                raise ValueError("structure %s defined twice" % current.name)
            structures[current.name] = current
        elif rtype in ELEMENTS:
            element, layer, sname, inst = rtype, None, None, None
            mirror, angle, mag = False, 0.0, 1.0
            colrow = points = attr = None
        elif rtype == LAYER:
            layer = struct.unpack(">h", payload[:2])[0]
        elif rtype == SNAME:
            sname = _name(payload)
        elif rtype == STRANS:
            mirror = bool(struct.unpack(">H", payload[:2])[0] & 0x8000)
        elif rtype == ANGLE:
            angle = decode_real8(payload[0:8])
        elif rtype == MAG:
            mag = decode_real8(payload[0:8])
        elif rtype == COLROW:
            colrow = struct.unpack(">hh", payload[:4])
        elif rtype == PROPATTR:
            attr = struct.unpack(">h", payload[:2])[0]
        elif rtype == PROPVALUE:
            if attr == PROP_INSTANCE_NAME:
                inst = _name(payload)
        elif rtype == XY:
            points = [struct.unpack(">ii", payload[i * 8:i * 8 + 8])
                      for i in range(len(payload) // 8)]
        elif rtype == ENDEL:
            if current is None or points is None:
                element = None
                continue
            if element in GEOMETRY and layer is not None:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                current.boxes[layer].append((min(xs), min(ys), max(xs), max(ys)))
            elif element == SREF:
                current.refs.append(
                    Placement(sname, points[0], mirror, angle, mag, inst))
            elif element == AREF:
                arefs += 1
                for origin in expand_aref(points, colrow):
                    current.refs.append(
                        Placement(sname, origin, mirror, angle, mag, inst))
            element = None

    if units is None:
        raise ValueError("no UNITS record")
    return {"structures": structures, "units": units, "libname": libname,
            "arefs": arefs}


def expand_aref(points, colrow):
    """An AREF is cols x rows placements between three reference points."""
    if colrow is None or len(points) < 3:
        raise ValueError("AREF without COLROW or without three points")
    cols, rows = colrow
    if cols < 1 or rows < 1:
        raise ValueError("AREF with %d columns and %d rows" % (cols, rows))
    x0, y0 = points[0]
    cx, cy = points[1]
    rx, ry = points[2]
    dcx, dcy = (cx - x0) / float(cols), (cy - y0) / float(cols)
    drx, dry = (rx - x0) / float(rows), (ry - y0) / float(rows)
    out = []
    for row in range(rows):
        for col in range(cols):
            out.append((int(round(x0 + col * dcx + row * drx)),
                        int(round(y0 + col * dcy + row * dry))))
    return out


def transform_box(box, place):
    """Move a master's own bounding box into the parent's coordinates."""
    x0, y0, x1, y1 = box
    radians = math.radians(place.angle)
    cos_a, sin_a = math.cos(radians), math.sin(radians)
    xs, ys = [], []
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        x *= place.mag
        y *= place.mag
        if place.mirror:
            y = -y
        xs.append(x * cos_a - y * sin_a + place.origin[0])
        ys.append(x * sin_a + y * cos_a + place.origin[1])
    return (min(xs), min(ys), max(xs), max(ys))


def union(boxes):
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def contains(outer, inner):
    return (inner[0] >= outer[0] and inner[1] >= outer[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def find_top(structures):
    """The structure nothing else places. There has to be exactly one."""
    referenced = set()
    for struct_ in structures.values():
        for place in struct_.refs:
            referenced.add(place.master)
    return [n for n in structures if n not in referenced]


# --------------------------------------------------------------------------
# the other three files


def read_lef_size(path, macro):
    """MACRO ... SIZE w BY h, in microns, for one named macro."""
    with open(path, errors="replace") as fh:
        text = fh.read()
    for name, body in LEF_MACRO_RE.findall(text):
        if name != macro:
            continue
        found = LEF_SIZE_RE.search(body)
        if not found:
            raise ValueError("macro %s has no SIZE" % macro)
        return float(found.group(1)), float(found.group(2))
    raise ValueError("no MACRO %s in %s" % (macro, os.path.basename(path)))


def read_netlist(path):
    """Instance name -> master, from the gate-level netlist."""
    with open(path, errors="replace") as fh:
        text = fh.read()
    cells = collections.OrderedDict()
    duplicates = []
    for master, inst in NETLIST_CELL_RE.findall(text):
        if inst in cells:
            duplicates.append(inst)
        cells[inst] = master
    return cells, duplicates


def read_metrics(path, design):
    with open(path, newline="", errors="replace") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if row.get("design_name") == design:
            return row
    raise ValueError("no row for %s in %s" % (design, os.path.basename(path)))


def normalise(name):
    """Strip escaping so a Verilog identifier and a GDS name can be compared.

    The netlist writes an escaped identifier as \\genblk1[0].u.inv and the GDS
    writes the same instance as genblk1\\[0\\].u.inv. Removing every backslash
    reconciles them, and the injectivity check below is what stops that from
    quietly merging two different instances into one.
    """
    return name.replace("\\", "")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# the checks


class Report(object):
    def __init__(self, title):
        self.title = title
        self.checks = []

    def check(self, name, condition, detail=""):
        self.checks.append((name, bool(condition), detail))
        return bool(condition)

    @property
    def failures(self):
        return [c for c in self.checks if not c[1]]

    def to_json(self):
        return [{"check": n, "pass": ok, "detail": d} for n, ok, d in self.checks]


def census_project(directory, ring_census=None):
    """Read all four files for one shuttle project and cross-check them."""
    design = os.path.basename(os.path.normpath(directory))
    gds_path = os.path.join(directory, design + ".gds")
    lef_path = os.path.join(directory, design + ".lef")
    net_path = os.path.join(directory, design + ".v")
    met_path = os.path.join(directory, "stats", "metrics.csv")

    report = Report(design)
    data = {"design": design}

    parsed = read_gds(gds_path)
    structures = parsed["structures"]
    data["gds_sha256"] = sha256_file(gds_path)
    data["netlist_sha256"] = sha256_file(net_path)
    data["library"] = parsed["libname"]
    data["structures"] = len(structures)
    data["aref_elements"] = parsed["arefs"]

    # --- the file describes one die, in nanometres
    user_unit, metre_unit = parsed["units"]
    data["db_unit_m"] = metre_unit
    report.check("database unit is 1 nm", abs(metre_unit - 1e-9) < 1e-18,
                 "%g m" % metre_unit)
    report.check("user unit is 1 um", abs(user_unit - 1e-3) < 1e-12,
                 "%g db units" % user_unit)
    nm_per_um = 1000.0

    tops = find_top(structures)
    report.check("exactly one top structure", len(tops) == 1, ", ".join(tops))
    report.check("the top structure is the design", tops == [design],
                 tops[0] if tops else "none")
    if len(tops) != 1:
        return report, data
    top = structures[tops[0]]

    # --- the die outline
    outlines = top.boxes.get(DIE_OUTLINE_LAYER, [])
    report.check("top carries one die outline on layer %d" % DIE_OUTLINE_LAYER,
                 len(outlines) == 1, "%d shapes" % len(outlines))
    die = union(outlines)
    if die is None:
        return report, data
    report.check("the die outline starts at the origin", die[0] == 0 and die[1] == 0,
                 "%d, %d" % (die[0], die[1]))
    width_um, height_um = (die[2] - die[0]) / nm_per_um, (die[3] - die[1]) / nm_per_um
    data["die_um"] = [width_um, height_um]

    lef_w, lef_h = read_lef_size(lef_path, design)
    data["lef_um"] = [lef_w, lef_h]
    report.check("die outline matches the LEF macro size",
                 abs(width_um - lef_w) < 1e-9 and abs(height_um - lef_h) < 1e-9,
                 "GDS %.3f x %.3f, LEF %.3f x %.3f" % (width_um, height_um, lef_w, lef_h))

    metrics = read_metrics(met_path, design)
    area_mm2 = width_um * height_um / 1e6
    flow_area = float(metrics["DIEAREA_mm^2"])
    data["die_area_mm2"] = area_mm2
    report.check("die area matches the flow's own metrics",
                 abs(area_mm2 - flow_area) <= MM2_TOLERANCE,
                 "%.8f vs %.8f mm^2" % (area_mm2, flow_area))

    # --- what is placed
    placements = top.refs
    data["instances"] = len(placements)
    elsewhere = sum(len(s.refs) for n, s in structures.items() if n != top.name)
    report.check("nothing is placed below the top cell", elsewhere == 0,
                 "%d placements in other structures" % elsewhere)

    by_master = collections.Counter(p.master for p in placements)
    data["masters"] = len(by_master)
    missing = sorted({p.master for p in placements} - set(structures))
    report.check("every placed master is defined in the file", not missing,
                 ", ".join(missing[:3]))

    kinds = collections.Counter()
    for place in placements:
        kind = "logic"
        for label, marker in PHYSICAL_KINDS:
            if marker in place.master:
                kind = label
                break
        kinds[kind] += 1
    data["cells"] = dict(kinds)

    total = int(metrics["TotalCells"])
    report.check("placed instances match TotalCells", len(placements) == total,
                 "%d vs %d" % (len(placements), total))
    for label, column in (("logic", "NonPhysCells"), ("fill", "FillCells"),
                          ("decap", "DecapCells"), ("tap", "WelltapCells"),
                          ("diode", "DiodeCells")):
        want = int(metrics[column])
        report.check("%s cells match %s" % (label, column), kinds[label] == want,
                     "%d vs %d" % (kinds[label], want))

    # --- placement geometry
    outside = [p for p in placements
               if not (die[0] <= p.origin[0] <= die[2]
                       and die[1] <= p.origin[1] <= die[3])]
    report.check("every instance origin is on the die", not outside,
                 "%d outside" % len(outside))

    covered = overhanging = 0
    no_outline = collections.Counter()
    for place in placements:
        master = structures.get(place.master)
        box = union(master.boxes.get(CELL_OUTLINE_LAYER, [])) if master else None
        if box is None:
            no_outline[place.master] += 1
            continue
        covered += 1
        if not contains(die, transform_box(box, place)):
            overhanging += 1
    data["outline_checked"] = covered
    data["no_outline_masters"] = sorted(no_outline)
    report.check("instances with a cell outline stay inside the die",
                 overhanging == 0,
                 "%d of %d checked overhang" % (overhanging, covered))
    report.check("the uncovered masters are physical fillers only",
                 all(any(m in name for _, m in PHYSICAL_KINDS) for name in no_outline),
                 ", ".join(sorted(no_outline)))

    # A standard cell row uses four orientations: upright and 180-rotated, each
    # with or without a reflection about x. A 90 degree placement would mean the
    # rows are not rows, and A.3 onward assumes they are.
    counted = collections.Counter((p.mirror, p.angle, p.mag) for p in placements)
    data["transforms"] = [{"mirror": m, "angle": a, "mag": g, "count": n}
                          for (m, a, g), n in sorted(counted.items())]
    report.check("placements are row orientations, unscaled",
                 all(a in (0.0, 180.0) and g == 1.0 for m, a, g in counted),
                 "%d distinct" % len(counted))

    # --- the placements are the netlist
    named = [p for p in placements if p.inst]
    report.check("every placement carries an instance name",
                 len(named) == len(placements),
                 "%d of %d" % (len(named), len(placements)))

    # Not a pass/fail, a count. The names the flow left behind are the author's
    # RTL paths, so the GDS publishes the hierarchy the same way the SPEF does.
    hierarchical = sorted(normalise(p.inst) for p in named
                          if "." in normalise(p.inst))
    data["hierarchical_names"] = len(hierarchical)
    data["hierarchical_example"] = hierarchical[0] if hierarchical else None

    gds_names = {}
    collisions = 0
    for place in named:
        key = normalise(place.inst)
        if key in gds_names:
            collisions += 1
        gds_names[key] = place.master
    report.check("GDS instance names stay distinct once unescaped",
                 collisions == 0, "%d collisions" % collisions)

    netlist, duplicates = read_netlist(net_path)
    report.check("netlist instance names are unique", not duplicates,
                 ", ".join(duplicates[:3]))
    net_names = {}
    net_collisions = 0
    for inst, master in netlist.items():
        key = normalise(inst)
        if key in net_names:
            net_collisions += 1
        net_names[key] = master
    report.check("netlist instance names stay distinct once unescaped",
                 net_collisions == 0, "%d collisions" % net_collisions)
    data["netlist_instances"] = len(netlist)

    only_gds = sorted(set(gds_names) - set(net_names))
    only_net = sorted(set(net_names) - set(gds_names))
    report.check("no instance is placed that the netlist does not have",
                 not only_gds, ", ".join(only_gds[:3]))
    report.check("no instance is in the netlist that is not placed",
                 not only_net, ", ".join(only_net[:3]))

    mismatched = sorted(n for n in set(gds_names) & set(net_names)
                        if gds_names[n] != net_names[n])
    report.check("every shared instance has the same master",
                 not mismatched, ", ".join(mismatched[:3]))

    net_by_master = collections.Counter(netlist.values())
    differing = sorted(m for m in set(net_by_master) | set(by_master)
                       if net_by_master[m] != by_master[m])
    report.check("per-master counts agree with the netlist",
                 not differing, ", ".join(differing[:3]))

    # --- and the ring census read the same netlist
    if ring_census is not None:
        entry = None
        for candidate in ring_census.get("netlists", []):
            if candidate.get("netlist") == design + ".v":
                entry = candidate
        report.check("the ring census covers this netlist", entry is not None)
        if entry is not None:
            report.check("the ring census read this exact netlist",
                         entry.get("netlist_sha256") == data["netlist_sha256"])
            counted = entry["combinational_cells"] + entry["sequential_cells"]
            fd_cells = sum(n for m, n in by_master.items()
                           if m.startswith("sky130_fd_sc_hd__"))
            report.check("ring census cell count matches the fd cells placed",
                         counted == fd_cells, "%d vs %d" % (counted, fd_cells))
            data["ring_census_cells"] = counted
            data["fd_cells_placed"] = fd_cells

    return report, data


# --------------------------------------------------------------------------
# output


def print_report(report, data):
    print("%s" % report.title)
    if "die_um" in data:
        print("   %.3f x %.3f um, %d structures, %d instances of %d masters"
              % (data["die_um"][0], data["die_um"][1], data["structures"],
                 data.get("instances", 0), data.get("masters", 0)))
        cells = data.get("cells", {})
        print("   %d logic, %d fill, %d decap, %d tap, %d diode"
              % (cells.get("logic", 0), cells.get("fill", 0), cells.get("decap", 0),
                 cells.get("tap", 0), cells.get("diode", 0)))
        if "hierarchical_names" in data:
            print("   %d placements named with an RTL path%s"
                  % (data["hierarchical_names"],
                     ", e.g. " + data["hierarchical_example"]
                     if data["hierarchical_example"] else ""))
    for name, ok, detail in report.checks:
        mark = "pass" if ok else "FAIL"
        print("      %-56s %s%s" % (name, mark, "  (%s)" % detail if detail and not ok else ""))
    print()


def run(directories, json_out=None):
    ring_census = None
    here = os.path.dirname(os.path.abspath(__file__))
    census_path = os.path.join(here, "RING_CENSUS.json")
    if os.path.exists(census_path):
        with open(census_path) as fh:
            ring_census = json.load(fh)

    results, failed = [], 0
    for directory in directories:
        report, data = census_project(directory, ring_census)
        data["checks"] = report.to_json()
        data["checks_run"] = len(report.checks)
        data["checks_failed"] = len(report.failures)
        failed += len(report.failures)
        results.append(data)
        print_report(report, data)

    ran = sum(r["checks_run"] for r in results)
    print("%d checks across %d projects, %d failed" % (ran, len(results), failed))

    if json_out:
        with open(json_out, "w") as fh:
            json.dump({"schema": "phaseA-gds-census/1", "projects": results},
                      fh, indent=2)
            fh.write("\n")
        print("wrote %s" % json_out)
    return 1 if failed else 0


# --------------------------------------------------------------------------
# selftest
#
# Every fixture below is built in memory, so this runs with no network and
# without the 13 MB of downloaded inputs. Each planted fault is one edit to one
# of the four files, and the check it is supposed to trip is named.


def rec(rtype, dtype, payload=b""):
    return struct.pack(">HBB", 4 + len(payload), rtype, dtype) + payload


def rec_str(rtype, text):
    raw = text.encode()
    if len(raw) % 2:
        raw += b"\x00"
    return rec(rtype, 6, raw)


def rec_i2(rtype, *values):
    return rec(rtype, 2, struct.pack(">%dh" % len(values), *values))


def rec_i4(rtype, *values):
    return rec(rtype, 3, struct.pack(">%di" % len(values), *values))


def rec_real(rtype, *values):
    return rec(rtype, 5, b"".join(encode_real8(v) for v in values))


def box_element(layer, x0, y0, x1, y1):
    return (rec(BOUNDARY, 0) + rec_i2(LAYER, layer) + rec_i2(DATATYPE, 0)
            + rec_i4(XY, x0, y0, x1, y0, x1, y1, x0, y1, x0, y0) + rec(ENDEL, 0))


def sref(master, x, y, inst=None, mirror=False):
    out = rec(SREF, 0) + rec_str(SNAME, master)
    if mirror:
        out += rec(STRANS, 1, struct.pack(">HH", 0x8000, 0))
    out += rec_i4(XY, x, y)
    if inst is not None:
        out += rec_i2(PROPATTR, PROP_INSTANCE_NAME) + rec_str(PROPVALUE, inst)
    return out + rec(ENDEL, 0)


def structure(name, body):
    return (rec_i2(BGNSTR, *([0] * 12)) + rec_str(STRNAME, name) + body
            + rec(ENDSTR, 0))


# One cell 1000 nm wide and 2720 nm tall, and a die two rows of four.
CELL_W, CELL_H = 1000, 2720
DIE_W, DIE_H = 4000, 5440
CELL_A = "sky130_fd_sc_hd__inv_2"
CELL_B = "sky130_fd_sc_hd__buf_1"
CELL_FILL = "sky130_fd_sc_hd__fill_1"


def fixture_gds(design="tt_um_selftest", placements=None, die=(DIE_W, DIE_H),
                db_unit=1e-9, extra_structures=b"", top_outline=True):
    if placements is None:
        placements = default_placements()
    lib = rec_i2(HEADER, 600) + rec_i2(BGNLIB, *([0] * 12))
    lib += rec_str(LIBNAME, design) + rec_real(UNITS, 1e-3, db_unit)
    # cell_a carries an overhanging well layer on purpose: real cells do, and a
    # containment check written against all layers would fail on a good file.
    lib += structure(CELL_A, box_element(CELL_OUTLINE_LAYER, 0, 0, CELL_W, CELL_H)
                     + box_element(64, -190, -190, CELL_W + 190, CELL_H + 190))
    lib += structure(CELL_B, box_element(CELL_OUTLINE_LAYER, 0, 0, CELL_W, CELL_H))
    lib += structure(CELL_FILL, box_element(68, 0, 0, CELL_W, CELL_H))
    lib += extra_structures
    body = box_element(DIE_OUTLINE_LAYER, 0, 0, die[0], die[1]) if top_outline else b""
    for master, x, y, inst, mirror in placements:
        body += sref(master, x, y, inst, mirror)
    lib += structure(design, body)
    return lib + rec(ENDLIB, 0)


def default_placements():
    """Four logic cells on row 0 and three plus a filler on row 1, mirrored."""
    out = []
    for i in range(4):
        out.append((CELL_A if i % 2 == 0 else CELL_B, i * CELL_W, 0,
                    "u_row0_%d" % i, False))
    for i in range(3):
        out.append((CELL_B, i * CELL_W, 2 * CELL_H, "u_row1_%d" % i, True))
    out.append((CELL_FILL, 3 * CELL_W, 2 * CELL_H, "FILLER_1_3", True))
    return out


def fixture_netlist(design="tt_um_selftest", placements=None):
    if placements is None:
        placements = default_placements()
    body = "module %s (VGND, VPWR);\n" % design
    for master, _x, _y, inst, _m in placements:
        body += "  %s %s (.A(a), .X(x), .VPWR(VPWR), .VGND(VGND));\n" % (master, inst)
    return body + "endmodule\n"


def fixture_lef(design="tt_um_selftest", die=(DIE_W, DIE_H)):
    return ("VERSION 5.7 ;\nMACRO %s\n  CLASS BLOCK ;\n  ORIGIN 0.000 0.000 ;\n"
            "  SIZE %.3f BY %.3f ;\nEND %s\n"
            % (design, die[0] / 1000.0, die[1] / 1000.0, design))


def fixture_metrics(design="tt_um_selftest", placements=None, die=(DIE_W, DIE_H)):
    if placements is None:
        placements = default_placements()
    fill = sum(1 for p in placements if "__fill" in p[0])
    logic = len(placements) - fill
    columns = ["design_name", "DIEAREA_mm^2", "TotalCells", "NonPhysCells",
               "FillCells", "DecapCells", "WelltapCells", "DiodeCells"]
    values = [design, "%.8f" % (die[0] * die[1] / 1e6 / 1e6), str(len(placements)),
              str(logic), str(fill), "0", "0", "0"]
    return ",".join(columns) + "\n" + ",".join(values) + "\n"


def write_fixture(directory, gds=None, netlist=None, lef=None, metrics=None,
                  design="tt_um_selftest"):
    root = os.path.join(directory, design)
    os.makedirs(os.path.join(root, "stats"), exist_ok=True)
    with open(os.path.join(root, design + ".gds"), "wb") as fh:
        fh.write(gds if gds is not None else fixture_gds(design))
    with open(os.path.join(root, design + ".v"), "w") as fh:
        fh.write(netlist if netlist is not None else fixture_netlist(design))
    with open(os.path.join(root, design + ".lef"), "w") as fh:
        fh.write(lef if lef is not None else fixture_lef(design))
    with open(os.path.join(root, "stats", "metrics.csv"), "w") as fh:
        fh.write(metrics if metrics is not None else fixture_metrics(design))
    return root


def selftest():
    ok = True
    checked_names = set()

    def note(name, condition):
        nonlocal ok
        print("  %-62s %s" % (name, "pass" if condition else "FAIL"))
        ok = ok and condition

    # the real encoder and the real decoder have to agree, or every number
    # this script reads out of a UNITS record is wrong in the same direction
    for value in (1e-3, 1e-9, 0.5, 1.0, 1e-6, 123.456):
        note("real8 round trip %g" % value,
             abs(decode_real8(encode_real8(value)) - value) <= abs(value) * 1e-15)

    def run_fixture(**kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_fixture(tmp, **kwargs)
            return census_project(root)

    report, data = run_fixture()
    failures = [c[0] for c in report.failures]
    note("a consistent fixture passes every check", not failures)
    if failures:
        for name in failures:
            print("        unexpected failure: %s" % name)
    note("the fixture is read as 8 instances", data.get("instances") == 8)
    note("the fixture die is 4.000 x 5.440 um",
         data.get("die_um") == [4.0, 5.44])
    note("both row orientations are seen", len(data.get("transforms", [])) == 2)

    def plants(label, expect, **kwargs):
        """Plant one fault and confirm the named check is the one that trips."""
        nonlocal ok
        report, _ = run_fixture(**kwargs)
        names = [c[0] for c in report.failures]
        hit = expect in names
        checked_names.add(expect)
        print("  %-62s %s" % (label, "pass" if hit else "FAIL"))
        if not hit:
            print("        expected %r, got %r" % (expect, names))
        ok = ok and hit

    # --- the die
    plants("a shrunken LEF size is caught",
           "die outline matches the LEF macro size",
           lef=fixture_lef(die=(DIE_W - 1000, DIE_H)))
    plants("a die area the flow does not agree with is caught",
           "die area matches the flow's own metrics",
           metrics=fixture_metrics(die=(DIE_W, DIE_H + 1000)))
    plants("a database unit that is not 1 nm is caught",
           "database unit is 1 nm", gds=fixture_gds(db_unit=1e-10))
    plants("a missing die outline is caught",
           "top carries one die outline on layer 235",
           gds=fixture_gds(top_outline=False))

    # --- the placements
    # drop a cell whose master is still placed elsewhere, so the fixture keeps
    # exactly one top structure and the planted fault is the only difference
    dropped = default_placements()
    del dropped[2]
    plants("an instance missing from the GDS is caught",
           "no instance is in the netlist that is not placed",
           gds=fixture_gds(placements=dropped))
    plants("and the same fault trips the count against the metrics",
           "placed instances match TotalCells",
           gds=fixture_gds(placements=dropped))

    renamed = default_placements()
    renamed[2] = (renamed[2][0], renamed[2][1], renamed[2][2], "u_renamed", renamed[2][4])
    plants("a renamed instance is caught",
           "no instance is placed that the netlist does not have",
           gds=fixture_gds(placements=renamed))

    swapped = default_placements()
    swapped[0] = (CELL_B,) + swapped[0][1:]
    plants("an instance placed with the wrong master is caught",
           "every shared instance has the same master",
           gds=fixture_gds(placements=swapped))
    plants("and the per-master totals move with it",
           "per-master counts agree with the netlist",
           gds=fixture_gds(placements=swapped))

    unnamed = default_placements()
    unnamed[1] = (unnamed[1][0], unnamed[1][1], unnamed[1][2], None, unnamed[1][4])
    plants("a placement with no name property is caught",
           "every placement carries an instance name",
           gds=fixture_gds(placements=unnamed))

    # two names that are different in the GDS but equal once unescaped. this is
    # the failure mode the normalisation itself could introduce.
    colliding = default_placements()
    colliding[0] = (colliding[0][0], colliding[0][1], colliding[0][2],
                    "u_row0_1", colliding[0][4])
    colliding[1] = (colliding[1][0], colliding[1][1], colliding[1][2],
                    "u_ro\\w0_1", colliding[1][4])
    plants("names that collide once unescaped are caught",
           "GDS instance names stay distinct once unescaped",
           gds=fixture_gds(placements=colliding))

    # --- geometry
    off_die = default_placements()
    off_die[0] = (off_die[0][0], DIE_W + CELL_W, off_die[0][2], off_die[0][3],
                  off_die[0][4])
    plants("a cell placed off the die is caught",
           "every instance origin is on the die",
           gds=fixture_gds(placements=off_die))

    overhang = default_placements()
    overhang[0] = (overhang[0][0], DIE_W - CELL_W // 2, 0, overhang[0][3],
                   overhang[0][4])
    plants("a cell hanging over the die edge is caught",
           "instances with a cell outline stay inside the die",
           gds=fixture_gds(placements=overhang))

    rotated_gds = fixture_gds().replace(
        rec_str(SNAME, CELL_A) + rec_i4(XY, 0, 0),
        rec_str(SNAME, CELL_A) + rec(ANGLE, 5, encode_real8(90.0)) + rec_i4(XY, 0, 0),
        1)
    plants("a rotated placement is reported, not silently accepted",
           "placements are row orientations, unscaled", gds=rotated_gds)

    # --- the top cell
    two_tops = fixture_gds(extra_structures=structure(
        "orphan", box_element(CELL_OUTLINE_LAYER, 0, 0, CELL_W, CELL_H)))
    plants("a second unreferenced structure is caught",
           "exactly one top structure", gds=two_tops)

    # --- the netlist
    duplicate = fixture_netlist() + "  %s u_row0_0 (.A(a));\n" % CELL_B
    plants("a netlist instance name used twice is caught",
           "netlist instance names are unique", netlist=duplicate)

    # a mirrored cell has to land where a mirrored cell lands, or the overhang
    # check above would be passing for the wrong reason
    place = Placement(CELL_A, (1000, 2720), True, 0.0, 1.0, None)
    got = transform_box((0, 0, CELL_W, CELL_H), place)
    note("a mirrored placement reflects about its own origin",
         got == (1000.0, 0.0, 2000.0, 2720.0))
    place = Placement(CELL_A, (0, 0), False, 90.0, 1.0, None)
    got = tuple(round(v) for v in transform_box((0, 0, CELL_W, CELL_H), place))
    note("a 90 degree placement rotates counter-clockwise",
         got == (-CELL_H, 0, 0, CELL_W))

    # AREF expansion, which no shuttle file uses and every reader gets wrong
    origins = expand_aref([(0, 0), (3000, 0), (0, 4000)], (3, 2))
    note("an AREF expands to columns times rows", len(origins) == 6)
    note("and lands on the right pitch",
         sorted(origins) == [(0, 0), (0, 2000), (1000, 0), (1000, 2000),
                             (2000, 0), (2000, 2000)])

    note("every planted fault named a distinct check",
         len(checked_names) == 16)

    print("\nselftest %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projects", nargs="*")
    parser.add_argument("--json", dest="json_out")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.projects:
        parser.error("give at least one project directory, or --selftest")
    return run(args.projects, args.json_out)


if __name__ == "__main__":
    sys.exit(main())
