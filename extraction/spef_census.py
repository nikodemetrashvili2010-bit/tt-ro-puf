#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Count what the shuttle's published SPEF says about who owns which net.

A.2 left one question open. The flow writes the placer's instance name into GDS
property 61, and for tt_um_litneet64_ro_puf 1792 of those are full RTL paths
while for tt_um_PUF none of 351 are. The note said the second target's SPEF might
still carry paths its GDS does not, and that A.3 should measure that rather than
assume it either way. This measures it.

It is a naming census and nothing else. It reads no capacitance value into any
result, so the numbers below cannot move if the parasitics do, and nothing here
predicts a response or ranks a ring.

Two namespaces live in a SPEF and they are not the same namespace. Net names
appear after *D_NET and instance names appear after *I, and the census reports
them apart, because the GDS comparison is only entitled to the instance half.

The design is flat by the time the SPEF is written, so none of this is SPEF
hierarchy in the *DIVIDER sense -- there is not one divider character in either
file. What survives is the pre-flattening RTL path, kept verbatim inside a single
escaped identifier, dots and brackets and all. Reading it back as a path is the
leak, and the census measures how far it goes by splitting on the escaped dot.

    python3 spef_census.py PROJECT [PROJECT ...]     # census and cross-checks
    python3 spef_census.py --json OUT PROJECT ...    # the same, machine readable
    python3 spef_census.py --selftest                # planted faults, no inputs

PROJECT is a shuttle project directory holding <name>.spef and <name>.v, where
<name> is the directory's own name. GDS_CENSUS.json and RING_CENSUS.json are read
from this script's own directory when they are there, and the checks that need
them are skipped by name when they are not.
"""

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import tempfile

# The parser below assumes these three, so it checks them rather than trusting
# them. A file that declared a different divider would still parse, and every
# path count in the census would be wrong by an amount nothing else would catch.
EXPECT_DIVIDER = "/"
EXPECT_DELIMITER = ":"
EXPECT_BUS = "[]"

# *C_UNIT 1 PF is what both shuttle files declare. No capacitance value reaches a
# result here, but the per-net total is checked against the sum of its own *CAP
# entries, and that check is only meaningful if both sides are the same unit.
EXPECT_CAP_UNIT = "PF"

# Every *CAP entry is printed to six significant digits, and a net here holds up
# to a few hundred of them, so a net total and the sum of its own entries cannot
# agree exactly. The worst relative residual over both shuttle files is 6.1e-06.
# The gate is set an order of magnitude above that rather than at it.
CAP_SUM_TOLERANCE = 1e-4

# The escaped dot is the separator to split on. In the file the RTL path
# genblk1[0].puf_buffer.ro_array_1[0].inter_wire[3] is written as one identifier
# with every dot and bracket backslash-escaped, so a plain split(".") finds
# nothing and a split on "\\." finds the path the author wrote.
SEP = "\\."

NETLIST_CELL_RE = re.compile(r"\b(sky130_\w+)\s+(\\?\S+?)\s*\(", re.M)
NETLIST_DECL_RE = re.compile(
    r"^\s*(input|output|inout|wire|supply0|supply1)\s+"
    r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s+)?(\\?\S+?)\s*;", re.M)


# --------------------------------------------------------------------------
# reading


def unescape(name):
    """Drop SPEF/Verilog escaping so the two files can be compared by name."""
    return name.replace("\\", "")


def segments(name):
    """The RTL path inside one escaped identifier, outermost first."""
    return [unescape(part) for part in name.split(SEP)]


def is_path(name):
    return SEP in name


class Spef(object):
    def __init__(self):
        self.header = {}
        self.name_map = {}
        self.duplicate_ids = []
        self.ports = []
        self.nets = []            # (name_token, declared_total, cap_sum, caps)
        self.net_ids = []
        self.instance_ids = []
        self.instance_pins = []   # (instance_token, pin)
        self.unresolved = []
        self.bad_lines = []


def read_spef(path):
    """Everything this census needs out of one SPEF, in one pass.

    Deliberately not a general SPEF reader. It knows *NAME_MAP, *PORTS, *D_NET
    with its *CONN and *CAP sections, and it records anything it did not
    recognise instead of skipping it, so a file shaped differently from these two
    fails loudly rather than censusing half of itself.
    """
    spef = Spef()
    section = None
    net = None

    with open(path, errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue

            if line.startswith("*SPEF ") or line.startswith("*DESIGN "):
                key, _, value = line[1:].partition(" ")
                spef.header[key] = value.strip().strip('"')
                continue
            head = line.split()
            keyword = head[0]

            if keyword in ("*DATE", "*VENDOR", "*PROGRAM", "*VERSION",
                           "*DESIGN_FLOW"):
                spef.header[keyword[1:]] = line.partition(" ")[2].strip()
                continue
            if keyword in ("*DIVIDER", "*DELIMITER", "*BUS_DELIMITER"):
                spef.header[keyword[1:]] = line.partition(" ")[2].strip()
                continue
            if keyword in ("*T_UNIT", "*C_UNIT", "*R_UNIT", "*L_UNIT"):
                spef.header[keyword[1:]] = line.partition(" ")[2].strip()
                continue

            if keyword == "*NAME_MAP":
                section = "names"
                continue
            if keyword == "*PORTS":
                section = "ports"
                continue

            if keyword == "*D_NET":
                section = "net"
                net = {"token": head[1],
                       "total": float(head[2]) if len(head) > 2 else None,
                       "caps": [], "conn": 0}
                spef.nets.append(net)
                spef.net_ids.append(head[1])
                continue
            if keyword == "*END":
                section = None
                net = None
                continue

            if section == "names":
                match = re.match(r"^\*(\d+)\s+(\S+)$", line)
                if not match:
                    spef.bad_lines.append(line)
                    continue
                index, name = match.group(1), match.group(2)
                if index in spef.name_map:
                    spef.duplicate_ids.append(index)
                spef.name_map[index] = name
                continue

            if section == "ports":
                spef.ports.append(head[0])
                continue

            if section == "net":
                if keyword in ("*CONN", "*CAP", "*RES"):
                    section = "net_" + keyword[1:].lower()
                    continue

            if section and section.startswith("net_"):
                if keyword in ("*CONN", "*CAP", "*RES"):
                    section = "net_" + keyword[1:].lower()
                    continue
                if keyword == "*END":
                    section = None
                    net = None
                    continue
                if keyword == "*I":
                    token, _, pin = head[1].partition(EXPECT_DELIMITER)
                    spef.instance_ids.append(token)
                    spef.instance_pins.append((token, pin))
                    net["conn"] += 1
                    continue
                if keyword == "*P":
                    net["conn"] += 1
                    continue
                if section == "net_cap" and len(head) >= 2:
                    try:
                        net["caps"].append(float(head[-1]))
                    except ValueError:
                        spef.bad_lines.append(line)
                    continue
                if section == "net_res":
                    continue
                spef.bad_lines.append(line)
                continue

            spef.bad_lines.append(line)

    for token in set(spef.net_ids) | set(spef.instance_ids):
        if token.startswith("*") and token[1:] not in spef.name_map:
            spef.unresolved.append(token)
    return spef


def resolve(spef, token):
    """A *N reference or a literal name, either way as a plain string.

    None when a *N reference has no entry in the name map. The caller drops
    those rather than comparing them against the netlist, because a dangling
    reference is already reported by its own check and should not also arrive
    as an unknown net.
    """
    if token.startswith("*"):
        return spef.name_map.get(token[1:])
    return token


def read_netlist(path):
    """Instances, declared nets and top-level ports from the gate-level netlist."""
    with open(path, errors="replace") as handle:
        text = handle.read()

    instances = collections.OrderedDict()
    for master, name in NETLIST_CELL_RE.findall(text):
        instances[unescape(name)] = master

    nets, ports = set(), set()
    for kind, high, low, name in NETLIST_DECL_RE.findall(text):
        name = unescape(name)
        if high:
            members = ["%s[%d]" % (name, i)
                       for i in range(int(low), int(high) + 1)]
        else:
            members = [name]
        nets.update(members)
        if kind in ("input", "output", "inout"):
            ports.update(members)
        if kind in ("supply0", "supply1"):
            ports.update(members)
    return instances, nets, ports


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# census


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


def family(names):
    """Group escaped RTL paths by parent path.

    Returns parent -> sorted leaf names. This is the whole recovery step and it
    is deliberately blind to the design: it splits on the separator and groups,
    and it never looks for a word like "ring" or "osc" in a name. What it can say
    is how many distinct owners the paths describe and how many children each
    has. Whether an owner is a ring is settled by comparing that count against
    the ring census, which was produced from the netlist by different code.
    """
    groups = collections.defaultdict(list)
    for name in names:
        parts = segments(name)
        groups[".".join(parts[:-1])].append(parts[-1])
    return {parent: sorted(leaves) for parent, leaves in groups.items()}


def widest_family(groups):
    """The parent count at the most common children-per-parent size.

    In both shuttle targets the ring arrays are the largest equal-sized family of
    parents, and the counters and the arbiter form smaller families beside them.
    Picking the largest family by parent count rather than by name is what keeps
    this from being a per-design pattern.
    """
    sizes = collections.Counter(len(leaves) for leaves in groups.values())
    if not sizes:
        return 0, 0
    best = max(sizes.items(), key=lambda kv: (kv[1], kv[0]))
    return best[1], best[0]        # how many parents, children each


def census_project(directory, gds_census=None, ring_census=None):
    design = os.path.basename(os.path.normpath(directory))
    spef_path = os.path.join(directory, design + ".spef")
    net_path = os.path.join(directory, design + ".v")

    report = Report(design)
    data = {"design": design,
            "spef_sha256": sha256_file(spef_path),
            "netlist_sha256": sha256_file(net_path)}

    spef = read_spef(spef_path)
    instances, netlist_nets, netlist_ports = read_netlist(net_path)

    # ---- the file is the file this census thinks it is -------------------
    report.check("the SPEF names this design",
                 spef.header.get("DESIGN") == design,
                 "%s" % spef.header.get("DESIGN"))
    report.check("the hierarchy divider is the one the parser assumes",
                 spef.header.get("DIVIDER") == EXPECT_DIVIDER,
                 "%r" % spef.header.get("DIVIDER"))
    report.check("the pin delimiter is the one the parser assumes",
                 spef.header.get("DELIMITER") == EXPECT_DELIMITER,
                 "%r" % spef.header.get("DELIMITER"))
    report.check("the bus delimiter is the one the parser assumes",
                 spef.header.get("BUS_DELIMITER") == EXPECT_BUS,
                 "%r" % spef.header.get("BUS_DELIMITER"))
    cap_unit = (spef.header.get("C_UNIT") or "").split()[-1:]
    report.check("capacitance is in the declared unit",
                 cap_unit == [EXPECT_CAP_UNIT],
                 "%s" % spef.header.get("C_UNIT"))
    report.check("every line was recognised",
                 not spef.bad_lines,
                 "%d unrecognised" % len(spef.bad_lines))

    # ---- the name map is a map -------------------------------------------
    report.check("name map indices are unique",
                 not spef.duplicate_ids,
                 "%d repeated" % len(spef.duplicate_ids))
    report.check("every name reference resolves",
                 not spef.unresolved,
                 "%d dangling" % len(spef.unresolved))

    net_ids = set(spef.net_ids)
    inst_ids = set(spef.instance_ids)
    report.check("no index is used as both a net and an instance",
                 not (net_ids & inst_ids),
                 "%d shared" % len(net_ids & inst_ids))

    # ---- the parser read the numbers it did read correctly ---------------
    off, worst = [], 0.0
    for entry in spef.nets:
        if entry["total"] is None or not entry["caps"]:
            continue
        residual = (abs(sum(entry["caps"]) - entry["total"])
                    / max(entry["total"], 1e-15))
        worst = max(worst, residual)
        if residual > CAP_SUM_TOLERANCE:
            off.append(entry["token"])
    report.check("each net total equals the sum of its own cap entries",
                 not off, "%d disagree, worst residual %.2e" % (len(off), worst))
    report.check("every net declares at least one connection",
                 all(n["conn"] for n in spef.nets),
                 "%d bare" % sum(1 for n in spef.nets if not n["conn"]))

    # ---- against the netlist ---------------------------------------------
    net_names = [n for n in (resolve(spef, t) for t in spef.net_ids)
                 if n is not None]
    inst_names = sorted({n for n in (resolve(spef, t)
                                     for t in spef.instance_ids)
                         if n is not None})
    unknown_nets = [n for n in net_names if unescape(n) not in netlist_nets]
    unknown_insts = [n for n in inst_names if unescape(n) not in instances]
    report.check("every SPEF net is a net the netlist declares",
                 not unknown_nets, "%d unknown" % len(unknown_nets))
    report.check("every SPEF instance is one the netlist instantiates",
                 not unknown_insts, "%d unknown" % len(unknown_insts))

    absent = sorted(netlist_nets - {unescape(n) for n in net_names})
    unclassified = [n for n in absent if n not in netlist_ports]
    report.check("netlist nets the SPEF omits are ports and supplies only",
                 not unclassified,
                 "%d omitted, %d unclassified" % (len(absent), len(unclassified)))

    # ---- the leak ---------------------------------------------------------
    divider_in_names = [n for n in spef.name_map.values()
                        if EXPECT_DIVIDER in n]
    report.check("no name carries the declared divider",
                 not divider_in_names,
                 "%d of %d names" % (len(divider_in_names), len(spef.name_map)))

    path_nets = [n for n in net_names if is_path(n)]
    path_insts = [n for n in inst_names if is_path(n)]
    # Unescaping is what lets a SPEF name be compared with a netlist identifier
    # at all, and it is lossy: a\.b and a.b both come out as a.b. If two names
    # collide the census would count two nets as one and never say so.
    collapsed = collections.Counter(unescape(n) for n in spef.name_map.values())
    collisions = [n for n, c in collapsed.items() if c > 1]
    report.check("distinct names stay distinct once unescaped",
                 not collisions, "%d collisions" % len(collisions))

    net_groups = family(path_nets)
    inst_groups = family(path_insts)
    net_owners, net_children = widest_family(net_groups)
    inst_owners, inst_children = widest_family(inst_groups)

    data.update({
        "nets": len(net_names),
        "instances": len(inst_names),
        "name_map": len(spef.name_map),
        "path_nets": len(path_nets),
        "path_instances": len(path_insts),
        "path_net_fraction": round(len(path_nets) / float(len(net_names)), 4)
                             if net_names else 0.0,
        "path_instance_fraction": round(len(path_insts) / float(len(inst_names)), 4)
                                  if inst_names else 0.0,
        "net_depths": dict(collections.Counter(
            len(segments(n)) for n in path_nets)),
        "instance_depths": dict(collections.Counter(
            len(segments(n)) for n in path_insts)),
        "net_owners": net_owners,
        "net_children_each": net_children,
        "instance_owners": inst_owners,
        "path_net_example": sorted(unescape(n) for n in path_nets)[:1],
        "path_instance_example": sorted(unescape(n) for n in path_insts)[:1],
        "nets_omitted": len(absent),
    })

    # the two namespaces are written by different stages, so when both carry
    # paths they are an independent check on each other
    if path_insts:
        owners_from_nets = set(net_groups)
        owners_from_insts = {".".join(segments(n)[:-2]) for n in path_insts}
        agree = owners_from_insts <= owners_from_nets
        report.check("instance paths and net paths name the same owners",
                     agree,
                     "%d instance owners, %d of them also net owners"
                     % (len(owners_from_insts),
                        len(owners_from_insts & owners_from_nets)))
    else:
        report.check("instance paths and net paths name the same owners",
                     True, "skipped: no instance carries a path")

    # ---- against the other two censuses -----------------------------------
    gds = None
    for entry in (gds_census or {}).get("projects", []):
        if entry.get("design") == design:
            gds = entry
    if gds is None:
        report.check("instance paths agree with the GDS census", True,
                     "skipped: no GDS census entry")
        report.check("the SPEF instance count is the GDS logic cell count", True,
                     "skipped: no GDS census entry")
    else:
        report.check("instance paths agree with the GDS census",
                     len(path_insts) == gds.get("hierarchical_names"),
                     "SPEF %d, GDS %d"
                     % (len(path_insts), gds.get("hierarchical_names")))
        report.check("the SPEF instance count is the GDS logic cell count",
                     len(inst_names) == gds.get("cells", {}).get("logic"),
                     "SPEF %d, GDS %d"
                     % (len(inst_names), gds.get("cells", {}).get("logic")))

    rings = None
    for entry in (ring_census or {}).get("netlists", []):
        if entry.get("netlist") == design + ".v":
            rings = entry
    if rings is None:
        report.check("the widest family of owners is one per ring", True,
                     "skipped: no ring census entry")
        report.check("the ring census read this netlist", True,
                     "skipped: no ring census entry")
    else:
        report.check("the widest family of owners is one per ring",
                     net_owners == rings.get("rings"),
                     "%d owners with %d nets each, %d rings"
                     % (net_owners, net_children, rings.get("rings")))
        report.check("the ring census read this netlist",
                     rings.get("netlist_sha256") == data["netlist_sha256"],
                     rings.get("netlist_sha256", "")[:16])
        data["rings"] = rings.get("rings")

    # ---- classification ----------------------------------------------------
    # A.3's acceptance condition asks for failures to be classified. Nothing
    # fails on these two, so what gets classified is the leak: how much of the
    # author's own structure each published file hands over without extraction.
    if path_insts and path_nets:
        tier = "instance and net names both carry the RTL path"
    elif path_nets:
        tier = "net names carry the RTL path, instance names do not"
    elif path_insts:
        tier = "instance names carry the RTL path, net names do not"
    else:
        tier = "no RTL path survives in either namespace"
    data["classification"] = tier

    return report, data


# --------------------------------------------------------------------------
# output


def print_report(report, data):
    print("\n%s" % report.title)
    print("  %d nets, %d instances, %d name map entries"
          % (data["nets"], data["instances"], data["name_map"]))
    print("  RTL paths: %d of %d nets (%.1f%%), %d of %d instances (%.1f%%)"
          % (data["path_nets"], data["nets"], 100 * data["path_net_fraction"],
             data["path_instances"], data["instances"],
             100 * data["path_instance_fraction"]))
    print("  widest family: %d owners with %d nets each%s"
          % (data["net_owners"], data["net_children_each"],
             ", %d rings in the ring census" % data["rings"]
             if "rings" in data else ""))
    print("  %s" % data["classification"])
    for name, ok, detail in report.checks:
        print("    %-58s %-4s %s" % (name, "pass" if ok else "FAIL", detail))


def run(directories, json_out=None):
    here = os.path.dirname(os.path.abspath(__file__))

    def load(filename):
        path = os.path.join(here, filename)
        if not os.path.exists(path):
            return None
        with open(path) as handle:
            return json.load(handle)

    gds_census = load("GDS_CENSUS.json")
    ring_census = load("RING_CENSUS.json")

    results, failed = [], 0
    for directory in directories:
        report, data = census_project(directory, gds_census, ring_census)
        data["checks"] = report.to_json()
        data["checks_run"] = len(report.checks)
        data["checks_failed"] = len(report.failures)
        failed += len(report.failures)
        results.append(data)
        print_report(report, data)

    ran = sum(r["checks_run"] for r in results)
    print("\n%d checks across %d projects, %d failed"
          % (ran, len(results), failed))

    if json_out:
        with open(json_out, "w") as handle:
            json.dump({"schema": "phaseA-spef-census/1", "projects": results},
                      handle, indent=2)
            handle.write("\n")
        print("wrote %s" % json_out)
    return 1 if failed else 0


# --------------------------------------------------------------------------
# archive verification
#
# extraction/inputs/ is gitignored and never mirrored, so CI cannot re-run the
# census on the real files. What it can do is re-check the census against the
# other three archived JSONs, arithmetically, with no input file present. That
# catches the failure this repo actually has to worry about: a recorded number
# edited without the file it came from changing.


def verify_archive(here=None, quiet=False):
    here = here or os.path.dirname(os.path.abspath(__file__))

    def load(filename):
        path = os.path.join(here, filename)
        if not os.path.exists(path):
            return None, "missing"
        with open(path) as handle:
            return json.load(handle), None

    report = Report("SPEF_CENSUS.json against the rest of the archive")
    census, err = load("SPEF_CENSUS.json")
    if err:
        report.check("SPEF_CENSUS.json is present", False, err)
        if not quiet:
            print_checks(report)
        return 1
    gds, _ = load("GDS_CENSUS.json")
    rings, _ = load("RING_CENSUS.json")
    manifest, _ = load("INPUT_MANIFEST.json")

    report.check("the census declares the schema this reader knows",
                 census.get("schema") == "phaseA-spef-census/1",
                 str(census.get("schema")))

    by_design = {p["design"]: p for p in census.get("projects", [])}
    report.check("the census covers both shuttle targets",
                 set(by_design) == {"tt_um_PUF", "tt_um_litneet64_ro_puf"},
                 ", ".join(sorted(by_design)))

    gds_by = {p["design"]: p for p in (gds or {}).get("projects", [])}
    ring_by = {p["netlist"]: p for p in (rings or {}).get("netlists", [])}
    hashes = {}
    for entry in (manifest or {}).get("inputs", []):
        hashes[entry["local"]] = entry["sha256"]

    for design, project in sorted(by_design.items()):
        tag = design[:18]

        report.check("%s: no check failed when the census ran" % tag,
                     project.get("checks_failed") == 0,
                     "%s of %s" % (project.get("checks_failed"),
                                   project.get("checks_run")))
        report.check("%s: the recorded pass count matches the list" % tag,
                     project.get("checks_run") == len(project.get("checks", [])),
                     "%s" % project.get("checks_run"))

        nets, insts = project["nets"], project["instances"]
        report.check("%s: the net path fraction is its own ratio" % tag,
                     abs(project["path_net_fraction"]
                         - project["path_nets"] / float(nets)) < 5e-5,
                     "%d/%d" % (project["path_nets"], nets))
        report.check("%s: the instance path fraction is its own ratio" % tag,
                     abs(project["path_instance_fraction"]
                         - project["path_instances"] / float(insts)) < 5e-5,
                     "%d/%d" % (project["path_instances"], insts))
        report.check("%s: the depth histogram accounts for every path net" % tag,
                     sum(project["net_depths"].values()) == project["path_nets"],
                     "%d" % project["path_nets"])
        report.check("%s: the depth histogram accounts for every path cell" % tag,
                     sum(project["instance_depths"].values())
                     == project["path_instances"],
                     "%d" % project["path_instances"])

        gds_entry = gds_by.get(design)
        report.check("%s: the GDS census agrees on the path count" % tag,
                     gds_entry is not None
                     and gds_entry.get("hierarchical_names")
                     == project["path_instances"],
                     "SPEF %d, GDS %s" % (project["path_instances"],
                                          (gds_entry or {}).get(
                                              "hierarchical_names")))
        report.check("%s: the GDS census agrees on the cell count" % tag,
                     gds_entry is not None
                     and gds_entry.get("cells", {}).get("logic") == insts,
                     "SPEF %d, GDS %s" % (insts, (gds_entry or {}).get(
                         "cells", {}).get("logic")))
        report.check("%s: both censuses read the same netlist" % tag,
                     gds_entry is not None
                     and gds_entry.get("netlist_sha256")
                     == project["netlist_sha256"],
                     project["netlist_sha256"][:16])

        ring_entry = ring_by.get(design + ".v")
        report.check("%s: the owner count is the ring count" % tag,
                     ring_entry is not None
                     and ring_entry.get("rings") == project["net_owners"],
                     "%d owners, %s rings" % (project["net_owners"],
                                              (ring_entry or {}).get("rings")))

        base = "tt07_shuttle/projects/%s/%s" % (design, design)
        report.check("%s: the SPEF is the one the manifest pins" % tag,
                     hashes.get(base + ".spef") == project["spef_sha256"],
                     project["spef_sha256"][:16])
        report.check("%s: the netlist is the one the manifest pins" % tag,
                     hashes.get(base + ".v") == project["netlist_sha256"],
                     project["netlist_sha256"][:16])

    if not quiet:
        print_checks(report)
    return 1 if report.failures else 0


def print_checks(report):
    print("\n%s" % report.title)
    for name, ok, detail in report.checks:
        print("  %-58s %-4s %s" % (name, "pass" if ok else "FAIL", detail))
    print("\n%d checks, %d failed" % (len(report.checks), len(report.failures)))


# --------------------------------------------------------------------------
# selftest
#
# The fixture is a four-ring design with the same shape as the real targets: an
# RTL path per ring net, a flat synthesis name for everything else, and a second
# namespace of instance names that may or may not carry the path. Each planted
# fault is one edit and it declares which check it must trip.


RINGS = 4
STAGES = 3


def fixture_paths(with_instance_paths=True):
    nets, insts = [], []
    for ring in range(RINGS):
        for stage in range(STAGES):
            nets.append(r"genblk1\[%d\]\.core\.ro\[%d\]\.w\[%d\]"
                        % (ring // 2, ring, stage))
            if with_instance_paths:
                insts.append(r"genblk1\[%d\]\.core\.ro\[%d\]\.g%d\.inv"
                             % (ring // 2, ring, stage))
    return nets, insts


def fixture(with_instance_paths=True, divider="/", cap_unit="1 PF",
            design="tt_um_selftest", duplicate_id=False, dangle=False,
            shared_id=False, bad_total=False, bare_net=False,
            unknown_instance=False, unknown_net=False, drop_ring=False,
            orphan_net=False, collide=False, shuffle=False, cap_scale=1.0,
            spef_design=None, divider_in_name=False):
    """One SPEF and one netlist, consistent unless a fault is asked for."""
    path_nets, path_insts = fixture_paths(with_instance_paths)
    if drop_ring:
        path_nets = [n for n in path_nets if r"ro\[3\]" not in n]

    flat_nets = ["_%03d_" % i for i in range(6)]
    flat_insts = ["_%03d_" % (100 + i) for i in range(5)]
    if unknown_net:
        flat_nets = list(flat_nets) + ["_ghost_"]
    if unknown_instance:
        flat_insts = list(flat_insts) + ["_ghostcell_"]

    nets = list(path_nets) + flat_nets
    insts = list(path_insts) + flat_insts
    if divider_in_name:
        nets = ["top/" + n if n == flat_nets[0] else n for n in nets]
    if shuffle:
        nets = nets[::-1]

    names = {}
    index = 3
    for name in nets + insts:
        names[name] = index
        index += 1
    dual = "_dual_" if shared_id else None
    if dual:
        names[dual] = index
        index += 1
        nets = nets + [dual]
    if collide:
        # the unescaped twin of the first ring net, as a flat name
        names[unescape(path_nets[0])] = index
        nets = nets + [unescape(path_nets[0])]
        index += 1

    lines = ['*SPEF "ieee 1481-1999"',
             '*DESIGN "%s"' % (spef_design or design),
             '*DATE "00:00:00 Monday January 01, 2026"',
             '*VENDOR "selftest"',
             '*PROGRAM "selftest"',
             '*VERSION "0"',
             '*DESIGN_FLOW "NAME_SCOPE LOCAL" "PIN_CAP NONE"',
             "*DIVIDER %s" % divider,
             "*DELIMITER :",
             "*BUS_DELIMITER []",
             "*T_UNIT 1 NS",
             "*C_UNIT %s" % cap_unit,
             "*R_UNIT 1 OHM",
             "*L_UNIT 1 HENRY",
             "",
             "*NAME_MAP"]
    for name, idx in sorted(names.items(), key=lambda kv: kv[1]):
        lines.append("*%d %s" % (idx, name))
    if duplicate_id:
        lines.append("*%d %s" % (names[nets[0]], nets[0]))
    lines.append("")
    lines.append("*PORTS")
    lines.append("")

    for position, net in enumerate(nets):
        caps = [0.001 * cap_scale, 0.002 * cap_scale]
        total = sum(caps)
        if bad_total and position == 0:
            total += 0.5
        lines.append("*D_NET *%d %g" % (names[net], total))
        if not (bare_net and position == 0):
            lines.append("*CONN")
            pin_of = insts[position % len(insts)]
            token = "*%d" % names[pin_of]
            if dangle and position == 0:
                token = "*99999"
            if dual and net == dual:
                token = "*%d" % names[dual]
            lines.append("*I %s:A I *D sky130_fd_sc_hd__inv_2" % token)
        lines.append("*CAP")
        for k, value in enumerate(caps):
            lines.append("%d *%d %g" % (k + 1, names[net], value))
        lines.append("*END")
        lines.append("")

    spef = "\n".join(lines) + "\n"

    # the netlist the census cross-checks against
    decls = ["module %s (VGND, VPWR, clk);" % design,
             " input VGND;", " input VPWR;", " input clk;"]
    for net in nets:
        if net == "_ghost_":
            continue
        if is_path(net) or "/" in net:
            decls.append(" wire \\%s ;" % unescape(net))
        else:
            decls.append(" wire %s;" % net)
    if orphan_net:
        decls.append(" wire _orphan_;")
    body = []
    for name in insts:
        if name == "_ghostcell_":
            continue
        written = ("\\%s " % unescape(name)) if is_path(name) else name
        body.append(" sky130_fd_sc_hd__inv_2 %s (.A(clk),\n    .Y(clk));"
                    % written)
    if dual:
        body.append(" sky130_fd_sc_hd__inv_2 %s (.A(clk),\n    .Y(clk));" % dual)
    netlist = "\n".join(decls + body + ["endmodule", ""])
    return spef, netlist


def write_fixture(root, design="tt_um_selftest", **kwargs):
    directory = os.path.join(root, design)
    os.makedirs(directory)
    spef, netlist = fixture(design=design, **kwargs)
    with open(os.path.join(directory, design + ".spef"), "w") as handle:
        handle.write(spef)
    with open(os.path.join(directory, design + ".v"), "w") as handle:
        handle.write(netlist)
    return directory


def selftest():
    ok = True
    tripped = set()

    def note(name, condition):
        nonlocal ok
        print("  %-64s %s" % (name, "pass" if condition else "FAIL"))
        ok = ok and condition

    def census(**kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_fixture(tmp, **kwargs)
            return census_project(root)

    # separator handling, which every count in the census rests on
    note("an escaped dot splits and a plain dot does not",
         segments(r"a\.b\[0\]\.c") == ["a", "b[0]", "c"]
         and segments("a.b") == ["a.b"])
    note("a flat synthesis name is not read as a path",
         not is_path("_042_") and is_path(r"a\.b"))

    report, data = census()
    failures = [c[0] for c in report.failures]
    note("a consistent fixture passes every check", not failures)
    for name in failures:
        print("        unexpected failure: %s" % name)
    note("the fixture is read as %d ring nets" % (RINGS * STAGES),
         data["path_nets"] == RINGS * STAGES)
    note("and as %d owners with %d nets each" % (RINGS, STAGES),
         data["net_owners"] == RINGS and data["net_children_each"] == STAGES)

    def plants(label, expect, **kwargs):
        nonlocal ok
        report, _ = census(**kwargs)
        failed = [c[0] for c in report.failures]
        hit = expect in failed
        extra = [f for f in failed if f != expect]
        print("  %-64s %s" % (label, "pass" if hit and not extra else "FAIL"))
        if not hit:
            print("        wanted %r, got %r" % (expect, failed))
        if extra:
            print("        also tripped %r" % extra)
        ok = ok and hit and not extra
        tripped.add(expect)

    plants("a renamed design trips the design check",
           "the SPEF names this design", spef_design="tt_um_other")
    plants("a different divider trips the divider check",
           "the hierarchy divider is the one the parser assumes", divider=".")
    plants("femtofarads trip the unit check",
           "capacitance is in the declared unit", cap_unit="1 FF")
    plants("a repeated index trips the uniqueness check",
           "name map indices are unique", duplicate_id=True)
    plants("a dangling reference trips the resolution check",
           "every name reference resolves", dangle=True)
    plants("one index for a net and an instance trips the namespace check",
           "no index is used as both a net and an instance", shared_id=True)
    plants("a total that is not its own sum trips the arithmetic check",
           "each net total equals the sum of its own cap entries", bad_total=True)
    plants("a net with no connections trips the connection check",
           "every net declares at least one connection", bare_net=True)
    plants("a net the netlist does not declare trips the net check",
           "every SPEF net is a net the netlist declares", unknown_net=True)
    plants("an instance the netlist does not have trips the instance check",
           "every SPEF instance is one the netlist instantiates",
           unknown_instance=True)
    plants("a netlist net the SPEF never mentions trips the omission check",
           "netlist nets the SPEF omits are ports and supplies only",
           orphan_net=True)
    plants("two names that unescape alike trip the injectivity check",
           "distinct names stay distinct once unescaped", collide=True)
    # a divider inside a name would mean the design was not flat after all, and
    # every owner count here would be counting the wrong thing
    plants("a divider inside a name trips the divider-in-name check",
           "no name carries the declared divider", divider_in_name=True)

    # a missing ring has to change the owner count, or the ring comparison is
    # a check that cannot fail
    report, data = census(drop_ring=True)
    note("dropping one ring drops the owner count to %d" % (RINGS - 1),
         data["net_owners"] == RINGS - 1)

    # instance paths that disagree with the net paths
    report, data = census(with_instance_paths=False)
    note("a design with no instance paths is classified as net-only",
         data["classification"]
         == "net names carry the RTL path, instance names do not"
         and not report.failures)

    # controls: neither of these may trip anything
    report, _ = census(shuffle=True)
    note("control: reordering the nets in the file changes nothing",
         not report.failures)
    report_a, data_a = census()
    report_b, data_b = census(cap_scale=1000.0)
    note("control: scaling every capacitance changes nothing",
         not report_b.failures
         and data_a["path_nets"] == data_b["path_nets"]
         and data_a["net_owners"] == data_b["net_owners"])

    note("every planted fault named a distinct check", len(tripped) == 13)

    # --verify-archive is the only thing CI can run against the real numbers,
    # since the inputs are never committed. A flag that cannot fail is worse
    # than no flag, so it gets planted faults too.
    def archive(edit=None):
        with tempfile.TemporaryDirectory() as tmp:
            spef_sha, net_sha = "a" * 64, "b" * 64
            project = {
                "design": "tt_um_PUF", "spef_sha256": spef_sha,
                "netlist_sha256": net_sha, "nets": 358, "instances": 351,
                "name_map": 2370, "path_nets": 82, "path_instances": 0,
                "path_net_fraction": 0.2291, "path_instance_fraction": 0.0,
                "net_depths": {"3": 18, "4": 64}, "instance_depths": {},
                "net_owners": 64, "net_children_each": 1, "instance_owners": 0,
                "checks": [{"check": "x", "pass": True, "detail": ""}],
                "checks_run": 1, "checks_failed": 0,
            }
            other = dict(project, design="tt_um_litneet64_ro_puf")
            files = {
                "SPEF_CENSUS.json": {"schema": "phaseA-spef-census/1",
                                     "projects": [project, other]},
                "GDS_CENSUS.json": {"projects": [
                    {"design": d, "hierarchical_names": 0,
                     "cells": {"logic": 351}, "netlist_sha256": net_sha}
                    for d in ("tt_um_PUF", "tt_um_litneet64_ro_puf")]},
                "RING_CENSUS.json": {"netlists": [
                    {"netlist": d + ".v", "rings": 64}
                    for d in ("tt_um_PUF", "tt_um_litneet64_ro_puf")]},
                "INPUT_MANIFEST.json": {"inputs": [
                    {"local": "tt07_shuttle/projects/%s/%s%s" % (d, d, ext),
                     "sha256": sha}
                    for d in ("tt_um_PUF", "tt_um_litneet64_ro_puf")
                    for ext, sha in ((".spef", spef_sha), (".v", net_sha))]},
            }
            if edit:
                edit(files)
            for name, body in files.items():
                with open(os.path.join(tmp, name), "w") as handle:
                    json.dump(body, handle)
            return verify_archive(tmp, quiet=True)

    note("control: a consistent archive verifies", archive() == 0)

    def bump(path_to, value):
        def edit(files):
            target = files
            for key in path_to[:-1]:
                target = target[key]
            target[path_to[-1]] = value
        return edit

    note("an edited path count is caught",
         archive(bump(["SPEF_CENSUS.json", "projects", 0, "path_nets"], 83)) == 1)
    note("an edited owner count is caught",
         archive(bump(["SPEF_CENSUS.json", "projects", 0, "net_owners"], 63)) == 1)
    note("a swapped input hash is caught",
         archive(bump(["INPUT_MANIFEST.json", "inputs", 0, "sha256"],
                      "c" * 64)) == 1)
    note("a census that recorded its own failures is caught",
         archive(bump(["SPEF_CENSUS.json", "projects", 1, "checks_failed"],
                      1)) == 1)

    print("\nselftest %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projects", nargs="*")
    parser.add_argument("--json", dest="json_out")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--verify-archive", action="store_true",
                        dest="verify_archive")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.verify_archive:
        return verify_archive()
    if not args.projects:
        parser.error("give at least one project directory, or --selftest")
    return run(args.projects, args.json_out)


if __name__ == "__main__":
    sys.exit(main())
