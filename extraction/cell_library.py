#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The sky130 cell library, read from the published views rather than typed.

Split out of `extraction/ring_topology.py` on 2026-09-07, which is where all
of the parsing and evaluating below was written and where it had made that
file 1641 lines, a third over the day yardstick. Three scripts wanted the
same thing and two of them had left a note saying so:

  chip/armc_cost.py       a frozenset of ten sky130 output pin names, typed
                          by hand, with a comment saying the proper
                          derivation "belongs in extraction/cell_library.py
                          when that module is split out"
  chip/lint_rtl.py        declares every stub port `inout`, with a comment
                          saying "Direction belongs to
                          extraction/cell_library.py when that module is
                          split out"
  extraction/ring_topology.py   had it, and was too long

A.1 was corrected for exactly this habit: it decided pin direction and
sequentiality from two tables written by hand, and the tables happened to be
right. An unchecked table that happens to be right is still an assumption.

## Two manifests, on purpose

`library_sources.json` was assembled on 2026-08-20 for the two Phase A
shuttle targets and its numbers are quoted in A.3 and A.4. It is not
reopened. Its 43 views cover 35 of the 51 masters in
`dualarm/build_current`'s netlist, so on its own it cannot answer a question
about this project's own chip.

`library_sources_design.json` is the other sixteen, from the same repository
at the same commit. Together they are the library, and
`extraction/CELL_LIBRARY.json` is what the union derives. That file is
committed and mirrored; the views themselves are not, because
`extraction/inputs/` is gitignored. So the emit runs here and the checks run
in CI, the same arrangement `spef_census.py --verify-archive` has.

## What the split found

`evaluate_cell` called an output sequential when it was driven through a UDP,
because on the 43 views the only UDPs were `udp_dff$P` and `udp_dff$PR` and
the two ideas coincided. They do not. `mux2` and `mux4` are driven through
`udp_mux_2to1` and `udp_mux_4to2`, which hold no state at all, and the first
run over the wider library called both of them sequential.

Nothing downstream was wrong, because what the loop finder needs is "this
evaluator cannot tell you the arcs", and that is true of a mux UDP as much as
of a flip flop. But the name was wrong and so was the sentence the report
printed. So there are two sets now: `opaque`, an output whose arcs cannot be
derived, which is what cuts an arc; and `sequential`, the subset driven
through a state element. On the 43 views they are the same set, which is why
Phase A's numbers do not move.

Which UDPs hold state is read off the library rather than remembered: four
distinct UDPs appear across all 59 views, two flip flops and two muxes, and
L03 fails on a UDP that matches neither rule instead of guessing.

Checks:

  L01  every declared view is the declared bytes
  L02  every view URL is pinned to a forty character commit
  L03  every UDP the library uses is classified, state or combinational
  L04  no cell the A.1 name markers miss holds state
  L05  every input has an arc class to every output that is not opaque
  L06  the derived output pins sit inside A.1's table and none is an input
  L07  the two manifests declare no cell twice
  L08  the archive covers every master this project's own netlist uses

L08 is the one the split was for. `armc_cost.py` reads the archive now, and
L08 is what makes that safe: the day a synthesis run picks a cell nobody
fetched, the gate says so instead of the cost model quietly misreading a
driver as a sink.

    python3 extraction/cell_library.py --selftest
    python3 extraction/cell_library.py --verify-archive
    python3 extraction/cell_library.py --emit          # needs inputs/

"""

import argparse
import collections
import hashlib
import itertools
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCES = os.path.join(HERE, "library_sources.json")
DESIGN_SOURCES = os.path.join(HERE, "library_sources_design.json")
LIBDIR = os.path.join(HERE, "inputs", "sky130_fd_sc_hd")
ARCHIVE = os.path.join(HERE, "CELL_LIBRARY.json")
SCHEMA = "phaseA-cell-library/1"

# The netlist L08 asks the archive to cover. Committed and mirrored, unlike
# the views, so this check runs in CI.
DESIGN_NETLIST = os.path.join(
    ROOT, "dualarm", "build_current",
    "tt_um_nikodemetrashvili20_ro_puf.nl.v")
MASTER_RX = re.compile(r"^\s*(sky130_fd_sc_hd__\w+)\s", re.M)

# A UDP holding state. Read off the library: the only UDPs in all 59 views
# are udp_dff$P, udp_dff$PR, udp_dff_p, udp_dff_pr, udp_mux_2to1 and
# udp_mux_4to2. L03 fails on one that matches neither rule.
STATE_UDP = ("dff", "dlatch", "dlrtp", "sr")
COMBINATIONAL_UDP = ("mux", "pwrgood", "isolatch")

# Verilog gate primitives the cell functional views are built from. A view that
# used anything else would still parse and every arc below would be wrong, so
# the parser refuses instead of guessing.
PRIMITIVES = {
    "not": lambda v: 1 - v[0],
    "buf": lambda v: v[0],
    "and": lambda v: int(all(v)),
    "nand": lambda v: int(not all(v)),
    "or": lambda v: int(any(v)),
    "nor": lambda v: int(not any(v)),
    "xor": lambda v: _parity(v),
    "xnor": lambda v: 1 - _parity(v),
}
CONSTANTS = {"pullup": 1, "pulldown": 0}
UDP_PREFIX = "sky130_fd_sc_hd__udp_"

# An arc class. POS and NEG are the two a loop can be counted through; BIN is a
# non-monotone input such as an xor's, where "inverting" has no answer, and
# NONE is an input the output does not depend on.
POS, NEG, BIN, NONE = "pos", "neg", "bin", "none"

# A cell with more inputs than this would make the truth table the wrong tool.
# The widest cell either shuttle design uses has five.
MAX_CELL_INPUTS = 8


# A.1's ring census decided pin direction and sequentiality from two tables it
# wrote by hand. Nothing here uses them; they are re-checked against what the
# published cell views actually say, because an unchecked table that happens to
# be right is still an assumption.
A1_OUT_PINS = frozenset({"X", "Y", "Q", "Q_N", "COUT", "COUT_N", "SUM",
                         "HI", "LO"})
A1_SEQ_MARKERS = ("__df", "__sdf", "__edf", "__dl", "__sedf", "__sdl")


def _parity(values):
    out = 0
    for v in values:
        out ^= v
    return out


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# the standard cell library


class CellError(Exception):
    pass


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


class Cell(object):
    """One standard cell, as its published functional view describes it."""

    def __init__(self, name, ports, inputs, outputs, supplies, instances):
        self.name = name
        self.ports = ports
        self.inputs = inputs
        self.outputs = outputs
        self.supplies = supplies
        self.instances = instances
        self.arcs = {}
        # Two different ideas that coincide on the 43 Phase A views.
        # opaque: this evaluator cannot derive the arcs, so they are
        # cut. sequential: the subset driven through a state element.
        self.opaque = set()
        self.sequential = set()
        self.pins = set(inputs) | set(outputs)

    def arc(self, pin_in, pin_out):
        return self.arcs.get((pin_in, pin_out), NONE)


def parse_cell(text, source=""):
    """Read one functional view into a Cell.

    The views are uniform: a module, its port directions, some local wires and
    a flat list of Verilog gate primitives. Anything that does not fit that
    shape raises rather than being skipped, because a cell that silently lost
    an instance would give an output no input reaches, and the truth table
    would report an arc class of NONE for every pin.
    """
    body = strip_comments(text)
    match = re.search(r"`celldefine(.*?)`endcelldefine", body, re.S)
    if not match:
        raise CellError("no celldefine block in %s" % (source or "input"))
    body = match.group(1)
    head = re.search(r"\bmodule\s+([A-Za-z_][\w$]*)\s*\((.*?)\)\s*;", body,
                     re.S)
    if not head:
        raise CellError("no module header in %s" % (source or "input"))
    name = head.group(1)
    ports = [p.strip() for p in head.group(2).split(",") if p.strip()]
    rest = body[head.end():]
    inputs, outputs, supplies = [], [], []
    for keyword, bucket in (("input", inputs), ("output", outputs),
                            ("supply1", supplies), ("supply0", supplies)):
        pattern = r"\b%s\s+([A-Za-z_][\w$]*)\s*;" % keyword
        bucket.extend(m.group(1) for m in re.finditer(pattern, rest))
    declared = set(inputs) | set(outputs)
    if declared != set(ports):
        raise CellError("%s declares %s but its port list is %s"
                        % (name, sorted(declared), sorted(ports)))
    instances = []
    pattern = re.compile(r"^\s*([A-Za-z_][\w$]*)\s+(?:`UNIT_DELAY\s+)?"
                         r"([A-Za-z_][\w$]*)\s*\(([^)]*)\)\s*;", re.M)
    for mo in pattern.finditer(rest):
        kind, iname, args = mo.group(1), mo.group(2), mo.group(3)
        if kind in ("input", "output", "wire", "supply1", "supply0", "module"):
            continue
        terms = [t.strip() for t in args.split(",") if t.strip()]
        if not terms:
            raise CellError("%s: primitive %s has no terminals"
                            % (name, iname))
        if kind not in PRIMITIVES and kind not in CONSTANTS \
                and not kind.startswith(UDP_PREFIX):
            raise CellError("%s: unknown primitive %r" % (name, kind))
        if kind in ("not", "buf") and len(terms) != 2:
            raise CellError("%s: %s %s has %d terminals, expected 2"
                            % (name, kind, iname, len(terms)))
        instances.append((kind, iname, terms))
    return Cell(name, ports, inputs, outputs, supplies, instances)


def evaluate_cell(cell):
    """Fill in the cell's arc classes by walking its own truth table.

    Small enough to be exact: the widest cell in either design has five inputs,
    so this evaluates at most thirty-two rows and reads the answer off rather
    than pattern-matching a cell name. An input is inverting when raising it
    never raises the output and lowers it somewhere, non-inverting the other
    way round, and neither when it does both, which is what an xor's inputs do.
    """
    if len(cell.inputs) > MAX_CELL_INPUTS:
        raise CellError("%s has %d inputs, over the limit"
                        % (cell.name, len(cell.inputs)))
    driver = {}
    for kind, iname, terms in cell.instances:
        target = terms[0]
        if target in driver:
            raise CellError("%s: %s is driven twice inside the cell"
                            % (cell.name, target))
        driver[target] = (kind, [] if kind in CONSTANTS else terms[1:])

    def through_udp(signal, seen=None, state_only=False):
        seen = set() if seen is None else seen
        if signal in seen or signal not in driver:
            return False
        seen.add(signal)
        kind, args = driver[signal]
        if kind.startswith(UDP_PREFIX):
            return is_state_udp(kind) if state_only else True
        return any(through_udp(a, seen, state_only) for a in args)

    cell.opaque = {o for o in cell.outputs if through_udp(o)}
    cell.sequential = {o for o in cell.outputs
                       if through_udp(o, state_only=True)}
    combinational = [o for o in cell.outputs if o not in cell.opaque]

    def value(signal, env, depth=0):
        if signal in env:
            return env[signal]
        if depth > 64 or signal not in driver:
            raise CellError("%s: %s is not driven" % (cell.name, signal))
        kind, args = driver[signal]
        if kind in CONSTANTS:
            return CONSTANTS[kind]
        return PRIMITIVES[kind]([value(a, env, depth + 1) for a in args])

    if not cell.inputs or not combinational:
        return cell
    table = {}
    for bits in itertools.product((0, 1), repeat=len(cell.inputs)):
        env = dict(zip(cell.inputs, bits))
        for supply in cell.supplies:
            env[supply] = 1
        table[bits] = {o: value(o, env) for o in combinational}
    for index, pin in enumerate(cell.inputs):
        for out in combinational:
            up = down = False
            for bits, row in table.items():
                if bits[index]:
                    continue
                raised = list(bits)
                raised[index] = 1
                delta = table[tuple(raised)][out] - row[out]
                up = up or delta > 0
                down = down or delta < 0
            if up and down:
                cell.arcs[(pin, out)] = BIN
            elif up:
                cell.arcs[(pin, out)] = POS
            elif down:
                cell.arcs[(pin, out)] = NEG
            else:
                cell.arcs[(pin, out)] = NONE
    return cell


class Library(object):
    def __init__(self, cells, supplies, files):
        self.cells = cells
        self.supplies = supplies
        self.files = files

    def base(self, master):
        """Drop the drive strength. sky130_fd_sc_hd__inv_2 -> ...__inv.

        Drive strength changes the transistors and not the pins or the
        function, so the functional views are published per base cell. Nothing
        here reads the strength, which is the point: two rings built from the
        same cells at different strengths come out of this identical, and the
        difference between them is A.5's problem, not this script's.
        """
        if "__" not in master:
            return None
        head, tail = master.split("__", 1)
        return head + "__" + re.sub(r"_\d+$", "", tail)

    def get(self, master):
        return self.cells.get(self.base(master))


def read_library(directory=LIBDIR, sources=SOURCES, report=None):
    """Load every declared view after checking it is the declared bytes."""
    with open(sources) as handle:
        declared = json.load(handle)
    files = declared["files"]
    cells, digests, bad_hash, bad_url = {}, {}, [], []
    for entry in files:
        path = os.path.join(directory, entry["local"])
        if not os.path.exists(path):
            raise CellError("library file missing: %s" % entry["local"])
        got = sha256_file(path)
        digests[entry["local"]] = got
        if got != entry["sha256"]:
            bad_hash.append(entry["local"])
        if not re.search(r"/[0-9a-f]{40}/", entry["url"]):
            bad_url.append(entry["local"])
        with open(path) as handle:
            cell = evaluate_cell(parse_cell(handle.read(), entry["local"]))
        cells[cell.name] = cell
    supplies = set()
    for cell in cells.values():
        supplies |= set(cell.supplies)
    if report is not None:
        report.check("every declared cell view is the declared bytes",
                     not bad_hash,
                     "%d files, %d mismatched" % (len(files), len(bad_hash)))
        report.check("every cell view URL is pinned to a commit",
                     not bad_url,
                     "%d files, %d unpinned" % (len(files), len(bad_url)))
        report.check("the supply pin names come from the library",
                     len(supplies) == 4,
                     ", ".join(sorted(supplies)))
        seq = sorted(c.name for c in cells.values() if c.sequential)
        report.check("an opaque output carries no derived arc",
                     all(not any(o in c.opaque for (_, o) in c.arcs)
                         for c in cells.values()),
                     "%d sequential cells: %s"
                     % (len(seq), ", ".join(s.split("__")[-1] for s in seq)))
        classes = collections.Counter(v for c in cells.values()
                                      for v in c.arcs.values())
        report.check("every input of every cell has an arc class",
                     all(len(c.arcs) == len(c.inputs) * len(
                         [o for o in c.outputs if o not in c.opaque])
                         for c in cells.values()),
                     ", ".join("%s %d" % kv for kv in sorted(classes.items())))
        # A.1 wrote both of these down as tables and they were never checked
        # against the library they describe. They hold, for these cells.
        out_pins = sorted({p for c in cells.values() for p in c.outputs})
        in_pins = {p for c in cells.values() for p in c.inputs}
        report.check("the A.1 output-pin table covers the derived directions",
                     set(out_pins) <= A1_OUT_PINS
                     and not (in_pins & A1_OUT_PINS),
                     "derived %s" % ", ".join(out_pins))
        by_marker = {c.name for c in cells.values()
                     if any(m in c.name for m in A1_SEQ_MARKERS)}
        derived = {c.name for c in cells.values() if c.sequential}
        # The direction that can cost a ring. A cell the markers wrongly call
        # sequential only removes arcs, so it can lose a loop and never invent
        # one; a cell they miss would fuse a design's whole clocked side into
        # one feedback region. The other direction is recorded below instead of
        # being checked, because on this library it is not empty.
        report.check("no cell the A.1 markers miss holds state",
                     derived <= by_marker,
                     "%d hold state, %d markers match" % (len(derived),
                                                          len(by_marker)))
        report.marker_only = sorted(by_marker - derived)
    return Library(cells, supplies, digests)


# --------------------------------------------------------------------------
# what the library is, across both manifests


DERIVED_UTC = "2026-09-07"


def is_state_udp(kind):
    """True for a UDP that holds state, False for one that does not.

    Raises on a UDP matching neither rule rather than guessing, because
    guessing wrong in the False direction fuses a design's whole clocked
    side into one feedback region.
    """
    tail = kind[len(UDP_PREFIX):].lower()
    if any(m in tail for m in STATE_UDP):
        return True
    if any(m in tail for m in COMBINATIONAL_UDP):
        return False
    raise CellError("unclassified UDP %r: add it to STATE_UDP or to "
                    "COMBINATIONAL_UDP, do not let it default" % kind)


def manifests(here=None):
    here = here or HERE
    return [os.path.join(here, "library_sources.json"),
            os.path.join(here, "library_sources_design.json")]


def read_libraries(directory=LIBDIR, sources=None, report=None):
    """One Library from every manifest, and the cells may not overlap."""
    sources = sources or manifests()
    cells, supplies, digests, declared, dupes = {}, set(), {}, {}, []
    for path in sources:
        lib = read_library(directory, path, report)
        for name, cell in lib.cells.items():
            if name in cells:
                dupes.append(name)
            cells[name] = cell
        supplies |= lib.supplies
        digests.update(lib.files)
        with open(path) as handle:
            declared[os.path.basename(path)] = json.load(handle)
    out = Library(cells, supplies, digests)
    out.declared = declared
    out.dupes = sorted(set(dupes))
    return out


def udps_used(lib):
    """Every UDP the library instantiates, classified."""
    seen = {}
    for cell in lib.cells.values():
        for kind, _, _ in cell.instances:
            if kind.startswith(UDP_PREFIX):
                seen[kind] = "state" if is_state_udp(kind) else "combinational"
    return seen


def design_masters(path=None):
    """The distinct sky130 masters this project's own netlist instantiates."""
    path = path or DESIGN_NETLIST
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        return sorted(set(MASTER_RX.findall(handle.read())))


def archive_from(lib):
    """The committed artefact, as data."""
    doc = {
        "schema": SCHEMA,
        "derived_utc": DERIVED_UTC,
        "manifests": {},
        "udps": udps_used(lib),
        "supplies": sorted(lib.supplies),
        "output_pins": sorted({p for c in lib.cells.values()
                               for p in c.outputs}),
        "input_pins": sorted({p for c in lib.cells.values()
                              for p in c.inputs}),
        "cells": {},
    }
    for name, decl in sorted(getattr(lib, "declared", {}).items()):
        doc["manifests"][name] = {
            "cells": len(decl["files"]),
            "commit": decl.get("repo", {}).get("commit", ""),
            "declared_utc": decl.get("declared_utc", ""),
        }
    for name, cell in sorted(lib.cells.items()):
        doc["cells"][name] = {
            "inputs": sorted(cell.inputs),
            "outputs": sorted(cell.outputs),
            "supplies": sorted(cell.supplies),
            "opaque": sorted(cell.opaque),
            "sequential": sorted(cell.sequential),
            "arcs": {"%s>%s" % k: v for k, v in sorted(cell.arcs.items())},
        }
    return doc


def write_archive(doc, path=None):
    path = path or ARCHIVE
    with open(path, "w", newline="\n") as handle:
        json.dump(doc, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def read_archive(path=None):
    with open(path or ARCHIVE) as handle:
        return json.load(handle)


# --------------------------------------------------------------------------
# checks


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


class Report(object):
    """What read_library's optional reporter needs, and nothing else."""

    def __init__(self):
        self.rows = []
        self.marker_only = []

    def check(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), detail))
        return ok


def run_checks(doc, decls, netlist=None, digests=None, dupes=()):
    """Every claim the archive makes, re-derived from the archive.

    digests is the sha256 of each view as read off disk, and is None in
    --verify-archive mode where the views are not present. L01 then compares
    the manifests against each other instead, which is the narrower
    guarantee: the archive cannot claim a cell no manifest declares.
    """
    res = Results()
    cells = doc["cells"]

    # From the file name, not from the manifest's "cell" field. The real
    # manifests carry both and the fixture carries only one, and the name
    # that matters is the one read_library keyed the cell by, which comes
    # from the module header inside the view.
    declared_cells = {e["local"][:-len(".functional.v")]
                      for d in decls.values() for e in d["files"]}
    if digests is None:
        res.add("L01", "every archived cell is one a manifest declares",
                set(cells) == declared_cells,
                "%d archived, %d declared, %d only in one"
                % (len(cells), len(declared_cells),
                   len(set(cells) ^ declared_cells)))
    else:
        bad = [e["local"] for d in decls.values() for e in d["files"]
               if digests.get(e["local"]) != e["sha256"]]
        res.add("L01", "every declared view is the declared bytes",
                not bad, "%d files, %d mismatched" % (len(digests), len(bad)))

    unpinned = [e["local"] for d in decls.values() for e in d["files"]
                if not re.search(r"/[0-9a-f]{40}/", e["url"])]
    res.add("L02", "every view URL is pinned to a forty character commit",
            not unpinned, "%d unpinned" % len(unpinned))

    udps = doc["udps"]
    wrong = []
    for kind, kls in sorted(udps.items()):
        try:
            want = "state" if is_state_udp(kind) else "combinational"
        except CellError:
            wrong.append(kind + " (unclassified)")
            continue
        if want != kls:
            wrong.append("%s recorded %s" % (kind, kls))
    res.add("L03", "every UDP the library uses is classified", not wrong,
            "%d UDPs: %s" % (len(udps), ", ".join(
                "%s %s" % (k.split("__udp_")[-1], v)
                for k, v in sorted(udps.items()))))

    seq = {n for n, c in cells.items() if c["sequential"]}
    by_marker = {n for n in cells if any(m in n for m in A1_SEQ_MARKERS)}
    res.add("L04", "no cell the A.1 name markers miss holds state",
            seq <= by_marker,
            "%d hold state (%s), %d match a marker"
            % (len(seq), ", ".join(sorted(s.split("__")[-1] for s in seq)),
               len(by_marker)))

    missing = []
    for n, c in sorted(cells.items()):
        want = len(c["inputs"]) * len([o for o in c["outputs"]
                                       if o not in c["opaque"]])
        if len(c["arcs"]) != want:
            missing.append("%s %d of %d" % (n.split("__")[-1],
                                            len(c["arcs"]), want))
    res.add("L05", "every input has an arc class to every non-opaque output",
            not missing, ", ".join(missing) or "%d cells clean" % len(cells))

    outs, ins = set(doc["output_pins"]), set(doc["input_pins"])
    res.add("L06", "the derived output pins sit inside A.1's table and none "
            "is an input",
            outs <= A1_OUT_PINS and not (ins & A1_OUT_PINS),
            "derived %s" % ", ".join(sorted(outs)))

    res.add("L07", "the two manifests declare no cell twice", not dupes,
            ", ".join(dupes) or "none")

    masters = design_masters(netlist)
    if masters is None:
        res.add("L08", "the archive covers every master the design uses",
                False, "netlist not found: %s" % (netlist or DESIGN_NETLIST))
    else:
        base = Library({}, set(), {}).base
        uncovered = sorted({m for m in masters if base(m) not in cells})
        res.add("L08", "the archive covers every master the design uses",
                not uncovered,
                "%d masters, %d uncovered%s"
                % (len(masters), len(uncovered),
                   ": " + ", ".join(uncovered) if uncovered else ""))
    return res

# --------------------------------------------------------------------------
# fetching the cell views


def fetch_library(directory=LIBDIR, sources=SOURCES):
    """Download every declared view. Needs network, so never runs in CI."""
    import urllib.request
    with open(sources) as handle:
        declared = json.load(handle)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    bad = 0
    for entry in declared["files"]:
        dest = os.path.join(directory, entry["local"])
        request = urllib.request.Request(
            entry["url"], headers={"User-Agent": "phaseA-ring-topology"})
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = response.read()
        with open(dest, "wb") as handle:
            handle.write(payload)
        got = hashlib.sha256(payload).hexdigest()
        ok = got == entry["sha256"]
        bad += 0 if ok else 1
        print("%s %s %d bytes" % ("ok  " if ok else "HASH", entry["local"],
                                  len(payload)))
    print("%d files, %d wrong" % (len(declared["files"]), bad))
    return 1 if bad else 0


# --------------------------------------------------------------------------
# the fixture

FIX = "sky130_fd_sc_hd__"
FIX_VIEWS = {
    "fixinv": ("Y,A", "output Y; input A;",
               "not not0 (n0, A); buf buf0 (Y, n0);"),
    "fixbuf": ("X,A", "output X; input A;",
               "buf buf0 (b0, A); buf buf1 (X, b0);"),
    "fixand2": ("X,A,B", "output X; input A; input B;",
                "and and0 (a0, A, B); buf buf0 (X, a0);"),
    "fixand2b": ("X,A_N,B", "output X; input A_N; input B;",
                 "not not0 (n0, A_N); and and0 (a0, n0, B); "
                 "buf buf0 (X, a0);"),
    "fixand3": ("X,A,B,C", "output X; input A; input B; input C;",
                "and and0 (a0, A, B, C); buf buf0 (X, a0);"),
    "fixxor2": ("X,A,B", "output X; input A; input B;",
                "xor xor0 (x0, A, B); buf buf0 (X, x0);"),
    "dfxfix": ("Q,CLK,D", "output Q; input CLK; input D;",
               FIX + "udp_dff$P dff0 (q0, D, CLK); buf buf0 (Q, q0);"),
    "dflfix": ("Q,Y,A", "output Q; output Y; input A;",
               FIX + "udp_dff$P dff0 (q0, A, A); buf buf0 (Q, q0); "
                     "not not0 (n0, A); buf buf1 (Y, n0);"),
    "fixfill": ("", "", "supply1 VPWR; supply0 VGND; supply1 VPB; "
                        "supply0 VNB;"),
    # A cell that holds state under a name none of A.1's markers would catch.
    # Only written when that fault is asked for.
    "fixlatch": ("Q,A", "output Q; input A;",
                 FIX + "udp_dff$P dff0 (q0, A, A); buf buf0 (Q, q0);"),
}
FIX_VIEW_TEXT = """\
/* SPDX-License-Identifier: Apache-2.0 */
`celldefine
module %s%s (%s);
    %s
    %s
endmodule
`endcelldefine
"""


def write_fixture_library(root, unknown_primitive=False, port_mismatch=False,
                          stray_output=False, hidden_state=False,
                          edit_one=False, unpinned=False):
    directory = os.path.join(root, "inputs", "sky130_fd_sc_hd")
    os.makedirs(directory)
    views = dict(FIX_VIEWS)
    if not hidden_state:
        del views["fixlatch"]
    if unknown_primitive:
        views["fixinv"] = (views["fixinv"][0], views["fixinv"][1],
                           "zomg not0 (n0, A); buf buf0 (Y, n0);")
    if port_mismatch:
        views["fixbuf"] = ("X,A,B", views["fixbuf"][1],
                           views["fixbuf"][2])
    if stray_output:
        views["fixzed"] = ("Z,A", "output Z; input A;",
                           "buf buf0 (Z, A);")
    files = []
    for name, (ports, decls, guts) in sorted(views.items()):
        local = "%s%s.functional.v" % (FIX, name)
        # one statement to a line, the way the published views are written
        laid_out = "\n    ".join(part.strip() + ";"
                                  for part in guts.split(";") if part.strip())
        declared = "\n    ".join(part.strip() + ";"
                                  for part in decls.split(";") if part.strip())
        text = FIX_VIEW_TEXT % (FIX, name, ports, declared, laid_out)
        with open(os.path.join(directory, local), "w") as handle:
            handle.write(text)
        files.append({
            "local": local,
            "url": "https://raw.githubusercontent.com/fixture/lib/%s/%s"
                   % ("z" * 40 if unpinned else "a" * 40, local),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
    if edit_one:
        target = os.path.join(directory, files[0]["local"])
        with open(target, "a") as handle:
            handle.write("\n// one byte more than was declared\n")
    with open(os.path.join(root, "library_sources.json"), "w") as handle:
        json.dump({"schema": "phaseA-library-sources/1", "files": files},
                  handle, indent=1, sort_keys=True)
    return directory


# The faults write_fixture_library can plant, named so a caller's selftest
# can iterate them. ring_topology.py's loop finder uses the same fixture.
LIBRARY_FAULTS = ("unknown_primitive", "port_mismatch", "stray_output",
                  "hidden_state", "edit_one", "unpinned")


# --------------------------------------------------------------------------
# the selftest


def write_second_manifest(root, cell="fixextra", duplicate=None):
    """A second manifest beside the fixture's, so L07 has something to see."""
    directory = os.path.join(root, "inputs", "sky130_fd_sc_hd")
    name = duplicate or cell
    local = "%s%s.functional.v" % (FIX, name)
    path = os.path.join(directory, local)
    if duplicate is None:
        text = FIX_VIEW_TEXT % (FIX, name, "X,A", "output X;\n    input A;",
                                "buf buf0 (X, A);")
        with open(path, "w") as handle:
            handle.write(text)
    else:
        with open(path) as handle:
            text = handle.read()
    with open(os.path.join(root, "library_sources_design.json"), "w") as fh:
        json.dump({"schema": "phaseA-library-sources/1", "files": [{
            "local": local,
            "url": "https://raw.githubusercontent.com/fixture/lib/%s/%s"
                   % ("a" * 40, local),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }]}, fh, indent=1, sort_keys=True)
    return os.path.join(root, "library_sources_design.json")


def write_fixture_netlist(root, master="sky130_fd_sc_hd__fixinv_1"):
    """A netlist L08 can be pointed at."""
    path = os.path.join(root, "fixture.nl.v")
    with open(path, "w", newline="\n") as handle:
        handle.write("module tt_um_fixture (input a, output y);\n")
        handle.write("  %s cell0 (.A(a), .Y(y));\n" % master)
        handle.write("endmodule\n")
    return path


def build_fixture(root, duplicate=False, extra_master=None, **kwargs):
    write_fixture_library(root, **kwargs)
    write_second_manifest(root, duplicate="fixinv" if duplicate else None)
    netlist = write_fixture_netlist(
        root, extra_master or "sky130_fd_sc_hd__fixinv_1")
    return (os.path.join(root, "inputs", "sky130_fd_sc_hd"),
            [os.path.join(root, "library_sources.json"),
             os.path.join(root, "library_sources_design.json")],
            netlist)


def run_fixture(root, **kwargs):
    directory, srcs, netlist = build_fixture(root, **kwargs)
    lib = read_libraries(directory, srcs)
    doc = archive_from(lib)
    return doc, run_checks(doc, lib.declared, netlist, lib.files, lib.dupes)


FAULTS = (
    ("L01", "a view edited after its hash was declared", dict(edit_one=True)),
    ("L02", "a view URL that is not a commit", dict(unpinned=True)),
    ("L04", "a cell holding state under a name no A.1 marker catches",
     dict(hidden_state=True)),
    ("L07", "the same cell declared by both manifests", dict(duplicate=True)),
    ("L08", "a master in the netlist that no manifest declares",
     dict(extra_master="sky130_fd_sc_hd__nobody_1")),
)


def selftest():
    import shutil
    import tempfile
    ok = True
    print("cell_library selftest")
    tmp = tempfile.mkdtemp(prefix="clfix")

    def fresh():
        shutil.rmtree(tmp)
        os.makedirs(tmp)

    try:
        doc, res = run_fixture(tmp)
        if res.failed():
            print("  FAIL: clean fixture fails %s" % ", ".join(res.failed()))
            for r in res.rows:
                if not r["pass"]:
                    print("        %s %s" % (r["id"], r["detail"]))
            ok = False
        else:
            print("  clean fixture passes all %d checks, %d cells"
                  % (len(res.rows), len(doc["cells"])))

        # the split itself: a mux UDP is opaque and is not state
        fresh()
        directory, srcs, netlist = build_fixture(tmp)
        text = FIX_VIEW_TEXT % (FIX, "fixmux", "X,A,S",
                                "output X;\n    input A;\n    input S;",
                                FIX + "udp_mux_2to1 mux0 (m0, A, A, S);\n"
                                "    buf buf0 (X, m0);")
        with open(os.path.join(directory, FIX + "fixmux.functional.v"),
                  "w") as fh:
            fh.write(text)
        with open(srcs[1]) as fh:
            second = json.load(fh)
        second["files"].append({
            "local": FIX + "fixmux.functional.v",
            "url": "https://raw.githubusercontent.com/fixture/lib/%s/x.v"
                   % ("a" * 40),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
        with open(srcs[1], "w") as fh:
            json.dump(second, fh, indent=1, sort_keys=True)
        lib = read_libraries(directory, srcs)
        mux = lib.cells[FIX + "fixmux"]
        doc = archive_from(lib)
        res = run_checks(doc, lib.declared, netlist, lib.files, lib.dupes)
        if mux.opaque == {"X"} and not mux.sequential and not res.failed():
            print("  ok    a mux UDP is opaque and holds no state, which is "
                  "the bug the split found")
        else:
            print("  FAIL  mux: opaque %s sequential %s failed %s"
                  % (sorted(mux.opaque), sorted(mux.sequential),
                     ", ".join(res.failed()) or "nothing"))
            ok = False

        # an unclassified UDP must raise, not default
        try:
            is_state_udp(UDP_PREFIX + "wat_1to0")
            print("  FAIL  L03  an unknown UDP was classified silently")
            ok = False
        except CellError:
            print("  ok    L03  an unknown UDP raises instead of defaulting")

        # the two parse-time faults still raise, as they did before the split
        for fault in ("unknown_primitive", "port_mismatch"):
            fresh()
            directory, srcs, _ = build_fixture(tmp, **{fault: True})
            try:
                read_libraries(directory, srcs)
                print("  FAIL  %s did not raise" % fault)
                ok = False
            except CellError:
                print("  ok    %-18s raises rather than being skipped"
                      % fault)

        for want, label, kwargs in FAULTS:
            fresh()
            tripped = set(run_fixture(tmp, **kwargs)[1].failed())
            if tripped == {want}:
                print("  ok    %-4s %s" % (want, label))
            elif want in tripped:
                print("  FAIL  %-4s %s -- also tripped %s"
                      % (want, label, ", ".join(sorted(tripped - {want}))))
                ok = False
            else:
                print("  FAIL  %-4s %s -- tripped %s"
                      % (want, label,
                         ", ".join(sorted(tripped)) or "nothing"))
                ok = False

        # the archive has to regenerate byte for byte
        fresh()
        directory, srcs, _ = build_fixture(tmp)
        lib = read_libraries(directory, srcs)
        a = json.dumps(archive_from(lib), indent=2, sort_keys=True)
        lib2 = read_libraries(directory, srcs)
        b = json.dumps(archive_from(lib2), indent=2, sort_keys=True)
        if a == b:
            print("  ok    the archive regenerates byte for byte")
        else:
            print("  FAIL  the archive is not deterministic")
            ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n  %s" % ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# --------------------------------------------------------------------------
# main


def print_checks(res):
    for r in res.rows:
        print("  %-5s %-4s %-58s %s"
              % ("pass" if r["pass"] else "FAIL", r["id"],
                 r["name"], r["detail"]))
    bad = res.failed()
    print("\n  %d checks, %s" % (len(res.rows),
                                 "all pass" if not bad
                                 else "FAILED: " + ", ".join(bad)))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", nargs="?", const=ARCHIVE, default=None,
                    help="derive the archive from the views under inputs/")
    ap.add_argument("--verify-archive", action="store_true",
                    help="re-derive every claim the committed archive makes")
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    if a.fetch:
        rc = 0
        for path in manifests():
            rc |= fetch_library(sources=path)
        return rc

    if a.emit:
        lib = read_libraries()
        doc = archive_from(lib)
        res = run_checks(doc, lib.declared, None, lib.files, lib.dupes)
        write_archive(doc, a.emit)
        print("wrote %s: %d cells from %d manifests"
              % (a.emit, len(doc["cells"]), len(doc["manifests"])))
        return print_checks(res)

    if a.verify_archive:
        doc = read_archive()
        decls = {}
        for path in manifests():
            with open(path) as handle:
                decls[os.path.basename(path)] = json.load(handle)
        res = run_checks(doc, decls)
        print("cell_library --verify-archive: %d cells, %d manifests"
              % (len(doc["cells"]), len(doc["manifests"])))
        return print_checks(res)

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
