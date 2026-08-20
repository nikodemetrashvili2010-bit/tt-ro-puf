#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Recover the ring oscillators from a shuttle netlist without reading a name.

Yesterday's SPEF census matched a count to a count: 256 owners of eight nets
each in one file, 256 rings in the other, and 64 owners of one net each against
64 rings on the second target. A count agreeing with a count is not a net being
on a ring, and the writeup said so and left the claim resting on a hand
check of the netlist. This is the code that replaces it.

The recovery is name-blind. Nets and instances are opaque keys here; nothing
splits them, matches them or looks inside them, and no result depends on what
any of them is called. What it uses instead is the standard cell library: each
cell's functional view gives its pin directions and, by exhaustive
evaluation of its own truth table, whether each input arrives at each output
inverted. That
turns the netlist into a signed graph, and a ring oscillator is a feedback loop
in that graph with an odd number of inversions around it.

Names enter once, afterwards, in their own step and clearly labelled: the
author's escaped RTL paths are grouped by parent and checked against the loops
that were already found. That check is the one that had been done by hand.

Every library file is verified against `library_sources.json` before it is
parsed, so an edited cell model cannot change an answer quietly.

    python3 ring_topology.py PROJECT ...     # recover and cross-check
    python3 ring_topology.py --json OUT ...  # the same, machine readable
    python3 ring_topology.py --fetch-library # download the cell views
    python3 ring_topology.py --selftest      # planted faults, no inputs
    python3 ring_topology.py --verify-archive  # recorded numbers, no inputs

PROJECT is a shuttle project directory holding <name>.v, where <name> is the
directory's own name. GDS_CENSUS.json, SPEF_CENSUS.json, RING_CENSUS.json and
INPUT_MANIFEST.json are read from this script's own directory when they are
there, and the checks that need them are skipped by name when they are not.
"""

import argparse
import collections
import hashlib
import itertools
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = os.path.join(HERE, "library_sources.json")
LIBDIR = os.path.join(HERE, "inputs", "sky130_fd_sc_hd")
SCHEMA = "phaseA-ring-topology/1"

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

SCRAMBLE_SEED = 20260820

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

    def through_udp(signal, seen=None):
        seen = set() if seen is None else seen
        if signal in seen or signal not in driver:
            return False
        seen.add(signal)
        kind, args = driver[signal]
        if kind.startswith(UDP_PREFIX):
            return True
        return any(through_udp(a, seen) for a in args)

    cell.sequential = {o for o in cell.outputs if through_udp(o)}
    combinational = [o for o in cell.outputs if o not in cell.sequential]

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
        report.check("sequential outputs carry no combinational arc",
                     all(not any(o in c.sequential for (_, o) in c.arcs)
                         for c in cells.values()),
                     "%d sequential cells: %s"
                     % (len(seq), ", ".join(s.split("__")[-1] for s in seq)))
        classes = collections.Counter(v for c in cells.values()
                                      for v in c.arcs.values())
        report.check("every input of every cell has an arc class",
                     all(len(c.arcs) == len(c.inputs) * len(
                         [o for o in c.outputs if o not in c.sequential])
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
# the netlist

ESCAPED = r"\\\S+\s"
IDENT = r"[A-Za-z_][\w$]*(?:\s*\[\s*\d+\s*\])?"


class NetlistError(Exception):
    pass


class Netlist(object):
    def __init__(self, top, ports, instances, assigns):
        self.top = top
        self.ports = ports
        self.instances = instances
        self.assigns = assigns


def read_netlist(path):
    """Parse a structural gate-level Verilog netlist.

    Escaped identifiers are read as one token including the backslash and up to
    the whitespace that ends them, and then left alone. The 19 August census
    learned this the hard way on the SPEF side: a name here can carry dots and
    brackets and mean nothing by them, so nothing in this file splits a net
    name for any purpose other than the labelled audit at the end.
    """
    text = strip_comments(open(path).read())
    start = text.find("module")
    if start < 0:
        raise NetlistError("no module in %s" % path)
    body = text[start:]
    head = re.match(r"\s*module\s+([A-Za-z_][\w$]*)\s*\((.*?)\)\s*;", body,
                    re.S)
    if not head:
        raise NetlistError("no module header in %s" % path)
    ports = [p.strip() for p in head.group(2).split(",") if p.strip()]
    instances, seen_names = [], set()
    pattern = re.compile(r"\b([A-Za-z_][\w$]*__[a-z0-9_]+)\s+"
                         r"(%s|[A-Za-z_][\w$]*)\s*\((.*?)\)\s*;"
                         % ESCAPED, re.S)
    conn = re.compile(r"\.\s*([A-Za-z_][\w$]*)\s*\(\s*(%s|[^),]*?)\s*\)"
                      % ESCAPED)
    for mo in pattern.finditer(body):
        master, iname = mo.group(1), mo.group(2).strip()
        if iname in seen_names:
            raise NetlistError("instance name %s appears twice" % iname)
        seen_names.add(iname)
        pins = {}
        for c in conn.finditer(mo.group(3)):
            pins[c.group(1)] = c.group(2).strip()
        instances.append((master, iname, pins))
    assigns = []
    for mo in re.finditer(r"\bassign\s+(%s|[^=]+?)\s*=\s*(%s|[^;]+?)\s*;"
                          % (ESCAPED, ESCAPED), body):
        assigns.append((mo.group(1).strip(), mo.group(2).strip()))
    return Netlist(head.group(1), ports, instances, assigns)


# --------------------------------------------------------------------------
# the signed graph, and the loops in it


class Graph(object):
    def __init__(self):
        self.succ = collections.defaultdict(list)
        self.drivers = collections.defaultdict(list)
        self.nodes = set()

    def arc(self, source, target, parity, owner):
        self.succ[source].append((target, parity, owner))
        self.nodes.add(source)
        self.nodes.add(target)


def build_graph(netlist, library, report=None):
    """Turn instances into signed arcs between nets.

    An arc exists from an input net to an output net when the cell's own truth
    table says the output depends on that input, and it carries a parity of one
    when the dependence is inverting. Continuous assignments join the graph as
    non-inverting arcs, because that is what they are.
    """
    graph = Graph()
    graph.binate = []
    unknown_pins, unmodelled, binate = [], [], graph.binate
    for master, iname, pins in netlist.instances:
        cell = library.get(master)
        if cell is None:
            signal = [p for p in pins if p not in library.supplies]
            if signal:
                unmodelled.append((master, iname, sorted(signal)))
            continue
        for pin, net in pins.items():
            if pin in cell.outputs:
                graph.drivers[net].append((iname, pin))
            elif pin not in cell.inputs and pin not in library.supplies:
                unknown_pins.append((master, pin))
        for (pin_in, pin_out), kind in cell.arcs.items():
            if pin_in not in pins or pin_out not in pins:
                continue
            if kind == BIN:
                binate.append((iname, pins[pin_in], pins[pin_out]))
                graph.arc(pins[pin_in], pins[pin_out], None, iname)
            elif kind in (POS, NEG):
                graph.arc(pins[pin_in], pins[pin_out], 1 if kind == NEG else 0,
                          iname)
    for lhs, rhs in netlist.assigns:
        graph.arc(rhs, lhs, 0, "assign")
        graph.drivers[lhs].append(("assign", "="))
    if report is not None:
        report.check("every instance pin is a port of its master or a supply",
                     not unknown_pins,
                     "%d unrecognised" % len(unknown_pins)
                     + ("" if not unknown_pins else ": %s" % unknown_pins[:3]))
        report.check("every unmodelled master is physical only",
                     not unmodelled,
                     "%d with signal pins" % len(unmodelled)
                     + ("" if not unmodelled else ": %s" % unmodelled[:2]))
        multi = sorted(n for n, d in graph.drivers.items()
                       if len(d) > 1 and n not in library.supplies)
        report.check("every signal net has exactly one driver",
                     not multi,
                     "%d nets driven, %d driven twice"
                     % (len(graph.drivers), len(multi)))
    return graph


def feedback_components(graph):
    """Tarjan's strongly connected components, iterative, on the net graph.

    Iterative because the litneet64 netlist is deep enough to end a recursive
    walk on the interpreter's stack, and a recursion limit raised until it
    stops crashing is not a result anybody should trust.
    """
    index, low, on_stack, stack, out = {}, {}, {}, [], []
    counter = [0]
    order = sorted(graph.nodes)
    for root in order:
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            node, offset = work[-1]
            if offset == 0:
                index[node] = low[node] = counter[0]
                counter[0] += 1
                stack.append(node)
                on_stack[node] = True
            descended = False
            edges = graph.succ[node]
            for i in range(offset, len(edges)):
                nxt = edges[i][0]
                if nxt not in index:
                    work[-1] = (node, i + 1)
                    work.append((nxt, 0))
                    descended = True
                    break
                if on_stack.get(nxt):
                    low[node] = min(low[node], index[nxt])
            if descended:
                continue
            if low[node] == index[node]:
                component = []
                while True:
                    popped = stack.pop()
                    on_stack[popped] = False
                    component.append(popped)
                    if popped == node:
                        break
                self_loop = any(e[0] == node for e in graph.succ[node])
                if len(component) > 1 or self_loop:
                    out.append(sorted(component))
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return out


def classify_loop(component, graph):
    """Is this feedback region one simple loop, and how many inversions has it?

    A ring oscillator is the easy case: every net in the region has exactly one
    successor and one predecessor inside it, so the region is the loop.
    Anything else -- a region where two loops share a net, or where a net
    feeds back through several paths -- is reported as a region rather than
    counted as a ring, which is what A.3's row means by failures being
    classified.
    """
    inside = set(component)
    parity, cells, out_degree, in_degree = 0, [], {}, collections.Counter()
    undefined = False
    for net in component:
        edges = [e for e in graph.succ[net] if e[0] in inside]
        out_degree[net] = len(edges)
        for target, sign, owner in edges:
            in_degree[target] += 1
            if sign is None:
                undefined = True
            else:
                parity ^= sign
            cells.append(owner)
    simple = (set(out_degree.values()) == {1}
              and len(in_degree) == len(component)
              and set(in_degree.values()) == {1})
    return {
        "nets": len(component),
        "simple": bool(simple),
        "parity": None if undefined else parity,
        "cells": cells,
        "members": inside,
    }


def external_inputs(loop, netlist, library):
    """Nets that reach a loop's cells from outside the loop.

    For a gated ring this is the enable and nothing else. It is reported rather
    than asserted to be one, because a ring with two of them is a different
    circuit and the number is how you would find out.
    """
    inside = loop["members"]
    sources = set()
    for master, iname, pins in netlist.instances:
        cell = library.get(master)
        if cell is None:
            continue
        if not any(pins.get(p) in inside for p in cell.outputs):
            continue
        for pin in cell.inputs:
            net = pins.get(pin)
            if net is not None and net not in inside:
                sources.add(net)
    return sources


def loop_exits(loop, graph):
    """Nets a loop drives that are not in the loop. Where the ring is read."""
    return {target for net in loop["members"]
            for target, _, _ in graph.succ[net]
            if target not in loop["members"]}


def is_path_name(name):
    return name.startswith("\\") and "." in name


def path_families(names):
    """Group the author's escaped paths by parent path.

    Same rule as the SPEF census, and the same blindness on purpose: it
    splits on the escaped dot and groups, and never looks for a word like
    ring or osc in a name. Everything above this line ran without it.
    """
    groups = collections.defaultdict(set)
    for name in names:
        groups[name.rsplit(".", 1)[0]].add(name)
    return groups


def scramble_netlist(netlist):
    """Rename every net and instance, keeping only the shape of a path name.

    The control this exists for: if any result moves, something in the recovery
    was reading a name. Paths keep their depth and their family structure so
    the labelled audit at the end still has something to group, but no word
    and no index survives, and the digest of the recovered topology has to
    come out the same as on the file itself.
    """
    cache = {}

    def rename(name):
        if name in cache:
            return cache[name]
        seed = "%d:%s" % (SCRAMBLE_SEED, name)
        tag = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10]
        if is_path_name(name):
            parts = name[1:].rstrip().split(".")
            parent = ".".join(parts[:-1])
            head = hashlib.sha256(
                ("%d:%s" % (SCRAMBLE_SEED, parent)).encode("utf-8")
            ).hexdigest()[:10]
            out = "\\p%s.q%s " % (head, tag)
        else:
            out = "n%s" % tag
        cache[name] = out
        return out

    instances = [(master, rename(iname),
                  {pin: (net if net in ("VPWR", "VGND", "VPB", "VNB")
                         else rename(net)) for pin, net in pins.items()})
                 for master, iname, pins in netlist.instances]
    assigns = [(rename(l), rename(r)) for l, r in netlist.assigns]
    return Netlist(netlist.top, [rename(p) for p in netlist.ports],
                   instances, assigns)


def recover(netlist, library, report=None):
    """Everything above, run once: graph, loops, and what they are made of."""
    graph = build_graph(netlist, library, report)
    loops = [classify_loop(c, graph) for c in feedback_components(graph)]
    loops.sort(key=lambda l: (l["nets"], sorted(l["members"])[0]))
    return graph, loops


def topology_digest(loops, netlist, library, families=None):
    """A canonical summary that survives renaming but nothing else.

    Loop count, and for each loop its length, its parity, whether it is simple,
    the multiset of masters around it and how many nets reach it from outside.
    No net name and no instance name goes in.
    """
    masters = {}
    for master, iname, pins in netlist.instances:
        masters[iname] = master
    rows = []
    for loop in loops:
        composition = sorted(collections.Counter(
            masters.get(c, "assign") for c in loop["cells"]).items())
        rows.append((loop["nets"],
                     -1 if loop["parity"] is None else loop["parity"],
                     loop["simple"], tuple(composition)))
    rows.sort()
    payload = json.dumps(rows, sort_keys=True)
    if families is not None:
        payload += json.dumps(sorted(collections.Counter(
            len(v) for v in families.values()).items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# the run over one project


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
        return [{"check": n, "pass": ok, "detail": d}
                for n, ok, d in self.checks]


def load_json(name, here=None):
    path = os.path.join(here or HERE, name)
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        return json.load(handle)


def project_entry(census, design):
    if not census:
        return None
    for row in census.get("projects", []):
        if row.get("design") == design:
            return row
    return None


def recover_project(directory, library, gds=None, spef=None, rings=None,
                    manifest=None):
    design = os.path.basename(os.path.normpath(directory))
    netlist_path = os.path.join(directory, design + ".v")
    report = Report(design)
    netlist = read_netlist(netlist_path)
    report.check("the netlist names this design", netlist.top == design,
                 netlist.top)

    digest = sha256_file(netlist_path)
    pinned = None
    if manifest:
        for row in manifest.get("inputs", []):
            if row.get("local", "").endswith("/%s.v" % design):
                pinned = row.get("sha256")
    if pinned is not None:
        report.check("the netlist is the file the input manifest pinned",
                     pinned == digest, digest[:16])

    graph, loops = recover(netlist, library, report)
    inst_master = masters_of(netlist)
    masters = collections.Counter(m for m, _, _ in netlist.instances)
    modelled = sum(n for m, n in masters.items() if library.get(m) is not None)
    # A logic cell is one with a signal pin at all. The tie cell has outputs
    # and no inputs, and both the GDS and the SPEF census count it, so a
    # definition resting on inputs would come out sixteen short on either
    # design and look like a parser fault rather than a definition.
    logic = sum(n for m, n in masters.items()
                if library.get(m) is not None and library.get(m).pins)

    gds_row = project_entry(gds, design)
    if gds_row:
        report.check("the instance total matches the GDS census",
                     gds_row.get("netlist_instances") == sum(masters.values()),
                     "%d instances" % sum(masters.values()))
        report.check("the modelled-cell count matches the GDS census",
                     gds_row.get("fd_cells_placed") == modelled,
                     "%d with a functional view" % modelled)
        report.check("the logic-cell count matches the GDS census",
                     gds_row.get("cells", {}).get("logic") == logic,
                     "%d cells with a signal pin" % logic)
    spef_row = project_entry(spef, design)
    if spef_row:
        report.check("the logic-cell count matches the SPEF census",
                     spef_row.get("instances") == logic, "%d" % logic)

    simple = [l for l in loops if l["simple"]]
    regions = [l for l in loops if not l["simple"]]
    report.check("every feedback region is one simple loop", not regions,
                 "%d loops, %d regions that are not" % (len(loops),
                                                        len(regions)))
    report.check("every loop has an odd number of inversions",
                 all(l["parity"] == 1 for l in simple
                     if l["parity"] is not None),
                 "parities %s" % dict(collections.Counter(
                     str(l["parity"]) for l in simple)))
    report.check("no loop runs through a non-monotone input",
                 all(l["parity"] is not None for l in loops),
                 "%d binate arcs in the design" % len(graph.binate))
    stateful = [c for l in simple for c in l["cells"]
                if getattr(library.get(inst_master.get(c, "")), "sequential",
                           None)]
    report.check("no loop runs through a cell that holds state",
                 not stateful,
                 "%d cells on loops hold state" % len(stateful))

    lengths = collections.Counter(l["nets"] for l in simple)
    ring_row = None
    for row in (rings or {}).get("netlists", []):
        if row.get("netlist") == design + ".v":
            ring_row = row
    if ring_row:
        report.check("the loop count matches the A.1 ring census",
                     ring_row.get("rings") == len(simple),
                     "%d loops here, %d there" % (len(simple),
                                                  ring_row.get("rings")))
        here_shapes = collections.Counter()
        for loop in simple:
            here_shapes[(loop["nets"],
                         tuple(sorted(inst_master.get(c, "assign")
                                      for c in loop["cells"])))] += 1
        if ring_row.get("shapes"):
            shapes = {(row["cells"], tuple(sorted(row["composition"]))):
                      row["count"] for row in ring_row["shapes"]}
            report.check("every loop shape matches the A.1 ring census",
                         shapes == dict(here_shapes),
                         "%d shapes" % len(here_shapes))

    composition = collections.Counter()
    for loop in simple:
        composition[tuple(sorted(collections.Counter(
            inst_master.get(c, "assign")
            for c in loop["cells"]).items()))] += 1
    enables = collections.Counter(
        len(external_inputs(l, netlist, library)) for l in simple)
    report.check("every loop is reached by exactly one net from outside",
                 set(enables) == {1} if simple else False,
                 "%s" % dict(enables))
    exits = collections.Counter(len(loop_exits(l, graph)) for l in simple)
    report.check("every loop drives at least one net outside itself",
                 all(k >= 1 for k in exits) if simple else False,
                 "%s" % dict(exits))

    # ---- names enter here and not before ----
    named = {net for _, _, pins in netlist.instances for net in pins.values()
             if is_path_name(net)}
    families = path_families(named)
    net_to_loop = {}
    for i, loop in enumerate(simple):
        for net in loop["members"]:
            net_to_loop[net] = i
    placement, claimed = collections.Counter(), collections.Counter()
    for parent, members in families.items():
        seen = {net_to_loop.get(m) for m in members}
        if len(seen) == 1 and None not in seen:
            placement["one loop"] += 1
            claimed[seen.pop()] += 1
        elif seen == {None}:
            placement["no loop"] += 1
        else:
            placement["split"] += 1
    # One check and not three. Any disturbance of the name map breaks the
    # correspondence in more than one direction at once, so three checks here
    # would be three ways of reporting one fact, and a planted fault could not
    # be isolated to any of them.
    report.check("the author's path families and the recovered loops "
                 "correspond one to one",
                 placement["split"] == 0 and len(claimed) == len(simple)
                 and all(v == 1 for v in claimed.values()) and bool(simple),
                 "%d families over %d loops: %s"
                 % (len(families), len(simple), dict(placement)))
    coverage = collections.Counter(
        sum(1 for n in l["members"] if n in named) for l in simple)
    report.check("the same number of nets is named on every loop",
                 len(coverage) == 1, "%s" % dict(coverage))
    if spef_row:
        report.check("the author-path net count matches the SPEF census",
                     spef_row.get("path_nets") == len(named),
                     "%d in the netlist, %d in the SPEF"
                     % (len(named), spef_row.get("path_nets")))
        family_sizes = collections.Counter(len(v) for v in families.values())
        widest = max(family_sizes.items(), key=lambda kv: (kv[1], kv[0]))
        report.check("the widest family matches the SPEF census",
                     (spef_row.get("net_owners"),
                      spef_row.get("net_children_each")) == (widest[1],
                                                             widest[0]),
                     "%d owners of %d" % (widest[1], widest[0]))

    # ---- the control ----
    plain = topology_digest(simple, netlist, library, families)
    scrambled_netlist = scramble_netlist(netlist)
    _, scrambled_loops = recover(scrambled_netlist, library)
    scrambled_named = {net for _, _, pins in scrambled_netlist.instances
                       for net in pins.values() if is_path_name(net)}
    scrambled_families = path_families(scrambled_named)
    other = topology_digest([l for l in scrambled_loops if l["simple"]],
                            scrambled_netlist, library, scrambled_families)
    report.check("renaming every net and instance changes nothing",
                 plain == other, plain[:16])

    data = {
        "design": design,
        "netlist_sha256": digest,
        "instances": sum(masters.values()),
        "modelled_instances": modelled,
        "logic_instances": logic,
        "loops": len(simple),
        "feedback_regions": len(regions),
        "loop_lengths": {str(k): v for k, v in sorted(lengths.items())},
        "loop_parities": {str(k): v for k, v in sorted(collections.Counter(
            "undefined" if l["parity"] is None else l["parity"]
            for l in simple).items(), key=lambda kv: str(kv[0]))},
        "loop_compositions": [
            {"count": n,
             "cells": [{"master": m, "n": c} for m, c in comp]}
            for comp, n in sorted(composition.items(), key=lambda kv: -kv[1])],
        "external_inputs_per_loop": {str(k): v
                                     for k, v in sorted(enables.items())},
        "exits_per_loop": {str(k): v for k, v in sorted(exits.items())},
        "author_named_nets": len(named),
        "author_families": len(families),
        "family_placement": dict(placement),
        "named_nets_per_loop": {str(k): v
                                for k, v in sorted(coverage.items())},
        "topology_digest": plain,
        "checks": report.to_json(),
        "checks_run": len(report.checks),
        "checks_failed": len(report.failures),
    }
    return report, data


def masters_of(netlist):
    return {iname: master for master, iname, _ in netlist.instances}


def print_report(report, data):
    print("%s" % report.title)
    print("   %d instances, %d with a functional view, %d with a signal pin"
          % (data["instances"], data["modelled_instances"],
             data["logic_instances"]))
    print("   %d simple feedback loops, %d regions that are not"
          % (data["loops"], data["feedback_regions"]))
    for row in data["loop_compositions"]:
        cells = ", ".join("%d x %s" % (c["n"], c["master"].split("__")[-1])
                          for c in row["cells"])
        print("      %4d loops: %s" % (row["count"], cells))
    print("   parities %s, external inputs %s, exits %s"
          % (data["loop_parities"], data["external_inputs_per_loop"],
             data["exits_per_loop"]))
    print("   %d author-path nets in %d families; %s"
          % (data["author_named_nets"], data["author_families"],
             ", ".join("%s %d" % kv
                       for kv in sorted(data["family_placement"].items()))))
    print("   named nets per loop %s" % data["named_nets_per_loop"])
    print("   topology digest %s" % data["topology_digest"][:16])
    for name, ok, detail in report.checks:
        print("   %s %s%s" % ("PASS" if ok else "FAIL", name,
                              (" -- " + detail) if detail else ""))


def run(directories, json_out=None, here=None):
    here = here or HERE
    library_report = Report("sky130_fd_sc_hd")
    library = read_library(os.path.join(here, "inputs", "sky130_fd_sc_hd"),
                           os.path.join(here, "library_sources.json"),
                           library_report)
    gds = load_json("GDS_CENSUS.json", here)
    spef = load_json("SPEF_CENSUS.json", here)
    rings = load_json("RING_CENSUS.json", here)
    manifest = load_json("INPUT_MANIFEST.json", here)
    print("%s cells, %d views" % (library_report.title, len(library.cells)))
    marker_only = getattr(library_report, "marker_only", [])
    if marker_only:
        print("   note: %d cells A.1's markers call sequential hold no state:"
              " %s" % (len(marker_only),
                       ", ".join(c.split("__")[-1] for c in marker_only)))
    for name, ok, detail in library_report.checks:
        print("   %s %s%s" % ("PASS" if ok else "FAIL", name,
                              (" -- " + detail) if detail else ""))
    results, failed = [], len(library_report.failures)
    for directory in directories:
        report, data = recover_project(directory, library, gds, spef, rings,
                                       manifest)
        print_report(report, data)
        results.append(data)
        failed += len(report.failures)
    payload = {
        "schema": SCHEMA,
        "library": {
            "cells": len(library.cells),
            "files": library.files,
            "a1_markers_without_state": marker_only,
            "checks": library_report.to_json(),
            "checks_run": len(library_report.checks),
            "checks_failed": len(library_report.failures),
        },
        "projects": results,
    }
    if json_out:
        with open(json_out, "w") as handle:
            json.dump(payload, handle, indent=1, sort_keys=True)
            handle.write("\n")
        print("wrote %s" % json_out)
    print("%d checks, %d failed"
          % (len(library_report.checks)
             + sum(d["checks_run"] for d in results), failed))
    return 1 if failed else 0


# --------------------------------------------------------------------------
# what CI can run: the recorded numbers, without the inputs


def verify_archive(here=None, quiet=False):
    """Re-derive every claim that lives between the archived files.

    The netlists and the cell views are not committed, so nothing here reads a
    raw input. What it can still guarantee is narrower and worth having: a
    number in the writeup cannot change unless a pinned file changed or this
    goes red. Each check re-derives one recorded value from a different file
    that recorded it independently.
    """
    here = here or HERE
    report = Report("archive")
    topo = load_json("RING_TOPOLOGY.json", here)
    gds = load_json("GDS_CENSUS.json", here)
    spef = load_json("SPEF_CENSUS.json", here)
    rings = load_json("RING_CENSUS.json", here)
    manifest = load_json("INPUT_MANIFEST.json", here)
    sources = load_json("library_sources.json", here)
    report.check("the topology archive is present and current",
                 bool(topo) and topo.get("schema") == SCHEMA,
                 (topo or {}).get("schema", "missing"))
    if not topo:
        print_checks(report)
        return 1
    report.check("the topology archive recorded no failure",
                 topo["library"]["checks_failed"] == 0
                 and all(p["checks_failed"] == 0 for p in topo["projects"]),
                 "%d library, %d project"
                 % (topo["library"]["checks_failed"],
                    sum(p["checks_failed"] for p in topo["projects"])))
    report.check("every recorded check count matches its own check list",
                 topo["library"]["checks_run"]
                 == len(topo["library"]["checks"])
                 and all(p["checks_run"] == len(p["checks"])
                         for p in topo["projects"]),
                 "%d + %d" % (topo["library"]["checks_run"],
                              sum(p["checks_run"] for p in topo["projects"])))
    declared = {f["local"]: f["sha256"] for f in (sources or {}).get("files",
                                                                     [])}
    report.check("every cell view read was a declared one",
                 set(topo["library"]["files"]) == set(declared)
                 and all(topo["library"]["files"][k] == v
                         for k, v in declared.items()),
                 "%d views" % len(declared))
    report.check("the cell view count matches the declaration",
                 topo["library"]["cells"] == len(declared),
                 "%d" % topo["library"]["cells"])
    unpinned = [f["local"] for f in (sources or {}).get("files", [])
                if not re.search(r"/[0-9a-f]{40}/", f["url"])]
    report.check("every declared cell view URL is on a commit", not unpinned,
                 "%d unpinned" % len(unpinned))
    for project in topo["projects"]:
        design = project["design"]
        gds_row = project_entry(gds, design) or {}
        spef_row = project_entry(spef, design) or {}
        ring_row = None
        for row in (rings or {}).get("netlists", []):
            if row.get("netlist") == design + ".v":
                ring_row = row
        report.check("%s: the netlist hash matches the ring census" % design,
                     bool(ring_row)
                     and ring_row.get("netlist_sha256")
                     == project["netlist_sha256"],
                     project["netlist_sha256"][:16])
        pinned = [row.get("sha256") for row in (manifest or {}).get("inputs",
                                                                    [])
                  if row.get("local", "").endswith("/%s.v" % design)]
        report.check("%s: the netlist hash matches the manifest" % design,
                     pinned and pinned[0] == project["netlist_sha256"],
                     "%d manifest rows" % len(pinned))
        report.check("%s: the instance total matches the GDS census" % design,
                     gds_row.get("netlist_instances") == project["instances"],
                     "%d" % project["instances"])
        report.check("%s: the logic-cell count matches both censuses" % design,
                     gds_row.get("cells", {}).get("logic")
                     == project["logic_instances"]
                     and spef_row.get("instances")
                     == project["logic_instances"],
                     "%d" % project["logic_instances"])
        report.check("%s: the loop count matches the ring census" % design,
                     bool(ring_row) and ring_row.get("rings")
                     == project["loops"], "%d" % project["loops"])
        report.check("%s: the loop lengths add up to the loop count" % design,
                     sum(project["loop_lengths"].values()) == project["loops"],
                     "%s" % project["loop_lengths"])
        report.check("%s: every loop has odd parity" % design,
                     list(project["loop_parities"]) == ["1"]
                     and project["loop_parities"]["1"] == project["loops"],
                     "%s" % project["loop_parities"])
        report.check("%s: the compositions add up to the loop count" % design,
                     sum(r["count"] for r in project["loop_compositions"])
                     == project["loops"], "%d shapes"
                     % len(project["loop_compositions"]))
        report.check("%s: every composition matches the ring census" % design,
                     bool(ring_row) and sorted(
                         (r["count"], sum(c["n"] for c in r["cells"]))
                         for r in project["loop_compositions"]) == sorted(
                             (s["count"], s["cells"])
                             for s in ring_row.get("shapes", [])),
                     "%d shapes" % len(project["loop_compositions"]))
        report.check("%s: the author-path net count matches the SPEF census"
                     % design,
                     spef_row.get("path_nets") == project["author_named_nets"],
                     "%d" % project["author_named_nets"])
        report.check("%s: the families all landed on one loop each" % design,
                     project["family_placement"].get("split", 0) == 0
                     and project["family_placement"].get("one loop")
                     == project["loops"],
                     "%s" % project["family_placement"])
        report.check("%s: the named-net coverage is one number" % design,
                     len(project["named_nets_per_loop"]) == 1
                     and sum(project["named_nets_per_loop"].values())
                     == project["loops"],
                     "%s" % project["named_nets_per_loop"])
        report.check("%s: every loop is reached by one net from outside"
                     % design,
                     list(project["external_inputs_per_loop"]) == ["1"]
                     and project["external_inputs_per_loop"]["1"]
                     == project["loops"],
                     "%s" % project["external_inputs_per_loop"])
    if not quiet:
        print_checks(report)
    return 1 if report.failures else 0


def print_checks(report):
    for name, ok, detail in report.checks:
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" -- " + detail) if detail else ""))
    print("%d checks, %d failed" % (len(report.checks), len(report.failures)))


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


def fixture_netlist(design="tt_um_fixture", rings=5, stages=3, named=2,
                    even_ring=False, merged=False, broken=False,
                    through_xor=False, through_state=False,
                    second_enable=False, unknown_pin=False,
                    double_drive=False, unmodelled_signal=False,
                    straddle=False, extra_name=False):
    """A small design of gated inverter rings, plus whichever fault is asked.

    Shaped like the targets and not like a unit test: every ring is an odd
    chain closed through an AND that gates it, some of its nets carry an
    escaped RTL path and some do not, and there is a flop off to the side so
    that a sequential cell is present without being on a loop.
    """
    lines, body = [], []
    for r in range(rings):
        chain = stages + (1 if even_ring and r == 0 else 0)
        nets = ["r%d_n%d" % (r, i) for i in range(chain + 1)]
        borrowed = straddle and r == rings - 1
        for i in range(named):
            if i < len(nets) - 1:
                nets[i] = "\\ring%d.f0.n%d " % (r - 1 if borrowed else r,
                                                 i + (10 if borrowed else 0))
        if extra_name and r == 0:
            nets[named] = "\\ring0.f0.n%d " % named
        for i in range(chain):
            cell = "fixinv"
            if through_state and r == 2 and i == 0:
                body.append(" %sdflfix_1 s%d_%d (.A(%s), .Y(%s), .Q(q%d),"
                            " .VPWR(VPWR), .VGND(VGND));"
                            % (FIX, r, i, nets[i].strip(),
                               nets[i + 1].strip(), r))
                continue
            body.append(" %s%s_2 g%d_%d (.A(%s), .Y(%s), .VPWR(VPWR),"
                        " .VGND(VGND));"
                        % (FIX, cell, r, i, nets[i].strip(),
                           nets[i + 1].strip()))
        tail = nets[chain].strip()
        if broken and r == rings - 1:
            tail = "dangling"
        close = nets[0].strip()
        # Cross-coupling two rings' gates is the only way a single-driver
        # netlist can hold a feedback region that is not one simple loop: the
        # gate has two inputs and both of them end up inside it.
        enable = "en"
        if merged and r in (0, 1):
            enable = "r%d_n%d" % (1 - r, stages)
        if through_xor and r == 1:
            body.append(" %sfixxor2_1 e%d (.A(%s), .B(en), .X(%s),"
                        " .VPWR(VPWR), .VGND(VGND));"
                        % (FIX, r, tail, close))
        elif second_enable and r == 0:
            body.append(" %sfixand3_1 e%d (.A(%s), .B(en), .C(en2), .X(%s),"
                        " .VPWR(VPWR), .VGND(VGND));"
                        % (FIX, r, tail, close))
        else:
            body.append(" %sfixand2_1 e%d (.A(%s), .B(%s), .X(%s),"
                        " .VPWR(VPWR), .VGND(VGND));"
                        % (FIX, r, tail, enable, close))
        body.append(" %sfixbuf_2 t%d (.A(%s), .X(tap%d), .VPWR(VPWR),"
                    " .VGND(VGND));" % (FIX, r, close, r))
    body.append(" %sdfxfix_1 ff0 (.CLK(clk), .D(r0_n%d), .Q(state),"
                " .VPWR(VPWR), .VGND(VGND));" % (FIX, stages))
    body.append(" %sfixbuf_2 ob0 (.A(state), .X(probe), .VPWR(VPWR),"
                " .VGND(VGND));" % FIX)
    body.append(" %sfixfill_1 fill0 (.VPWR(VPWR), .VGND(VGND));" % FIX)
    if unknown_pin:
        body.append(" %sfixbuf_2 bad0 (.A(en), .ZZ(probe2), .X(probe3),"
                    " .VPWR(VPWR), .VGND(VGND));" % FIX)
    if double_drive:
        body.append(" %sfixbuf_2 dd0 (.A(en), .X(probe), .VPWR(VPWR),"
                    " .VGND(VGND));" % FIX)
    if unmodelled_signal:
        body.append(" sky130_ef_sc_hd__decap_12 dc0 (.A(en), .VPWR(VPWR),"
                    " .VGND(VGND));")
    else:
        body.append(" sky130_ef_sc_hd__decap_12 dc0 (.VPWR(VPWR),"
                    " .VGND(VGND));")
    lines.append("module %s (clk, en, en2, one, probe, VPWR, VGND);" % design)
    lines.append(" input clk; input en; input en2; input one;")
    lines.append(" output probe; input VPWR; input VGND;")
    lines.extend(body)
    lines.append(" assign probe_alias = probe;")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def write_fixture(root, design="tt_um_fixture", census=None, **kwargs):
    """The netlist, the cell views and the four archives beside them.

    The archives describe whatever the fixture built, unless `census` overrides
    a value on purpose -- which is itself one of the faults, because a netlist
    disagreeing with the record of it is exactly what those checks exist for.
    """
    write_fixture_library(root, **{k: v for k, v in kwargs.items()
                                   if k in LIBRARY_FAULTS})
    netlist_kwargs = {k: v for k, v in kwargs.items()
                      if k not in LIBRARY_FAULTS}
    directory = os.path.join(root, design)
    os.makedirs(directory)
    text = fixture_netlist(design=design, **netlist_kwargs)
    path = os.path.join(directory, design + ".v")
    with open(path, "w") as handle:
        handle.write(text)
    digest = sha256_file(path)
    rings = netlist_kwargs.get("rings", 5)
    stages = netlist_kwargs.get("stages", 3)
    named = netlist_kwargs.get("named", 2)
    instances = len(re.findall(r"^ \w+__\w+ ", text, re.M))
    logic = instances - 2                      # the fill and the ef decap
    facts = {
        "instances": instances, "modelled": instances - 1, "logic": logic,
        "rings": rings, "net_owners": rings, "net_children_each": named,
        "path_nets": rings * named + (1 if kwargs.get("extra_name") else 0),
        "sha256": digest, "shapes": [],
    }
    facts.update(census or {})
    with open(os.path.join(root, "GDS_CENSUS.json"), "w") as handle:
        json.dump({"projects": [{"design": design,
                                 "netlist_instances": facts["instances"],
                                 "fd_cells_placed": facts["modelled"],
                                 "cells": {"logic": facts["logic"]}}]}, handle)
    with open(os.path.join(root, "SPEF_CENSUS.json"), "w") as handle:
        json.dump({"projects": [{"design": design,
                                 "instances": facts["logic"],
                                 "path_nets": facts["path_nets"],
                                 "net_owners": facts["net_owners"],
                                 "net_children_each":
                                     facts["net_children_each"]}]}, handle)
    with open(os.path.join(root, "RING_CENSUS.json"), "w") as handle:
        json.dump({"netlists": [{"netlist": design + ".v",
                                 "netlist_sha256": facts["sha256"],
                                 "rings": facts["rings"],
                                 "shapes": facts["shapes"]}]},
                  handle)
    with open(os.path.join(root, "INPUT_MANIFEST.json"), "w") as handle:
        json.dump({"inputs": [{"local": "x/%s.v" % design,
                               "sha256": facts["sha256"]}]}, handle)
    return directory


LIBRARY_FAULTS = ("unknown_primitive", "port_mismatch", "stray_output",
                  "hidden_state", "edit_one", "unpinned")


# --------------------------------------------------------------------------
# the selftest


def run_fixture(**kwargs):
    """Build a fixture, recover it, and hand back the checks it produced."""
    census = kwargs.pop("census", None)
    root = tempfile.mkdtemp(prefix="ring-topology-")
    directory = write_fixture(root, census=census, **kwargs)
    report = Report("library")
    library = read_library(os.path.join(root, "inputs", "sky130_fd_sc_hd"),
                           os.path.join(root, "library_sources.json"), report)
    project, data = recover_project(
        directory, library,
        load_json("GDS_CENSUS.json", root),
        load_json("SPEF_CENSUS.json", root),
        load_json("RING_CENSUS.json", root),
        load_json("INPUT_MANIFEST.json", root))
    return report.checks + project.checks, data


def selftest():
    passed, failed = [0], []

    def check(name, condition, detail=""):
        if condition:
            passed[0] += 1
        else:
            failed.append("%s%s" % (name, (" -- " + detail) if detail else ""))

    def fault(name, expect, **kwargs):
        """One planted fault must trip the named check and only that one."""
        try:
            checks, _ = run_fixture(**kwargs)
        except (CellError, NetlistError) as exc:
            failed.append("%s raised instead of failing a check: %s"
                          % (name, exc))
            return
        tripped = sorted(n for n, ok, _ in checks if not ok)
        check("%s trips %r" % (name, expect), expect in tripped,
              "tripped %s" % (tripped or "nothing"))
        check("%s trips nothing else" % name, tripped == [expect],
              "also %s" % [t for t in tripped if t != expect])

    def refusal(name, needle, **kwargs):
        """Some faults are not results at all -- the parser has to refuse."""
        try:
            run_fixture(**kwargs)
        except (CellError, NetlistError) as exc:
            check("%s is refused" % name, needle in str(exc), str(exc))
            return
        check("%s is refused" % name, False, "it was accepted")

    # ---- controls: these must trip nothing ----
    clean, data = run_fixture()
    tripped = sorted(n for n, ok, _ in clean if not ok)
    check("the clean fixture passes every check", not tripped,
          "%s" % tripped)
    check("the clean fixture finds five loops", data["loops"] == 5,
          "%d" % data["loops"])
    check("every loop is odd", data["loop_parities"] == {"1": 5},
          "%s" % data["loop_parities"])
    check("two nets are named on each loop",
          data["named_nets_per_loop"] == {"2": 5},
          "%s" % data["named_nets_per_loop"])

    wide, wide_data = run_fixture(stages=7)
    check("a longer ring is still one loop and still odd",
          wide_data["loops"] == 5 and wide_data["loop_parities"] == {"1": 5},
          "%s" % wide_data["loop_parities"])
    check("a longer ring changes the topology digest",
          wide_data["topology_digest"] != data["topology_digest"])

    strong, strong_data = run_fixture(rings=5, stages=3)
    check("the same fixture twice gives the same digest",
          strong_data["topology_digest"] == data["topology_digest"])

    # The control the whole approach rests on. The recovery is handed a file in
    # which no net or instance is called what it was called, and it has to
    # return the same topology. If any of it were reading a name, this moves.
    check("renaming everything is already checked inside the run",
          all(ok for n, ok, _ in clean
              if n == "renaming every net and instance changes nothing"))

    # ---- faults the parser must refuse rather than score ----
    refusal("a cell view using an unknown primitive", "unknown primitive",
            unknown_primitive=True)
    refusal("a cell view whose ports and declarations disagree",
            "port list", port_mismatch=True)

    # ---- planted faults, one check each ----
    fault("an edited cell view", "every declared cell view is the declared "
          "bytes", edit_one=True)
    fault("a cell view URL off a commit",
          "every cell view URL is pinned to a commit", unpinned=True)
    fault("a cell with an output pin A.1 never listed",
          "the A.1 output-pin table covers the derived directions",
          stray_output=True)
    fault("a cell that holds state under a name A.1 would miss",
          "no cell the A.1 markers miss holds state", hidden_state=True)
    fault("an instance pin its master does not have",
          "every instance pin is a port of its master or a supply",
          unknown_pin=True)
    fault("a net driven twice", "every signal net has exactly one driver",
          double_drive=True)
    fault("a physical-only master wired to a signal",
          "every unmodelled master is physical only", unmodelled_signal=True)
    fault("a ring with an even number of inversions",
          "every loop has an odd number of inversions", even_ring=True,
          census={"rings": 5})
    fault("two rings sharing their gates",
          "every feedback region is one simple loop", merged=True,
          census={"rings": 3})
    fault("a ring closed through an xor",
          "no loop runs through a non-monotone input", through_xor=True)
    fault("a ring closed through a cell that holds state",
          "no loop runs through a cell that holds state", through_state=True)
    fault("a ring left open", "the loop count matches the A.1 ring census",
          broken=True)
    fault("a ring gated by two enables",
          "every loop is reached by exactly one net from outside",
          second_enable=True)
    fault("a family of paths spanning two rings",
          "the author's path families and the recovered loops correspond "
          "one to one", straddle=True, census={"net_owners": 3})
    fault("one more named net on one ring",
          "the same number of nets is named on every loop", extra_name=True,
          census={"net_owners": 4})
    fault("an edited instance total in the GDS census",
          "the instance total matches the GDS census",
          census={"instances": 999})
    fault("an edited path-net count in the SPEF census",
          "the author-path net count matches the SPEF census",
          census={"path_nets": 999})
    fault("an edited netlist hash in the input manifest",
          "the netlist is the file the input manifest pinned",
          census={"sha256": "0" * 64})

    # ---- the archive verifier, which is all CI gets to run ----
    def archive(**edits):
        root = tempfile.mkdtemp(prefix="ring-archive-")
        design, loops, named = "tt_um_fixture", 5, 2
        views = [{"local": "c%d.functional.v" % i, "sha256": "%064d" % i,
                  "url": "https://x/%s/c%d" % ("a" * 40, i)} for i in range(3)]
        topo = {
            "schema": SCHEMA,
            "library": {"cells": len(views),
                        "files": {v["local"]: v["sha256"] for v in views},
                        "checks": [], "checks_run": 0, "checks_failed": 0},
            "projects": [{
                "design": design, "netlist_sha256": "d" * 64,
                "instances": 40, "modelled_instances": 39,
                "logic_instances": 30, "loops": loops, "feedback_regions": 0,
                "loop_lengths": {"4": loops}, "loop_parities": {"1": loops},
                "loop_compositions": [{"count": loops,
                                       "cells": [{"master": "m", "n": 4}]}],
                "external_inputs_per_loop": {"1": loops},
                "exits_per_loop": {"1": loops},
                "author_named_nets": loops * named, "author_families": loops,
                "family_placement": {"one loop": loops},
                "named_nets_per_loop": {str(named): loops},
                "topology_digest": "e" * 64, "checks": [], "checks_run": 0,
                "checks_failed": 0}]}
        docs = {
            "RING_TOPOLOGY.json": topo,
            "library_sources.json": {"files": views},
            "GDS_CENSUS.json": {"projects": [
                {"design": design, "netlist_instances": 40,
                 "cells": {"logic": 30}}]},
            "SPEF_CENSUS.json": {"projects": [
                {"design": design, "instances": 30,
                 "path_nets": loops * named}]},
            "RING_CENSUS.json": {"netlists": [
                {"netlist": design + ".v", "netlist_sha256": "d" * 64,
                 "rings": loops,
                 "shapes": [{"count": loops, "cells": 4}]}]},
            "INPUT_MANIFEST.json": {"inputs": [
                {"local": "x/%s.v" % design, "sha256": "d" * 64}]},
        }
        for name, edit in edits.items():
            edit(docs)
        for name, doc in docs.items():
            with open(os.path.join(root, name), "w") as handle:
                json.dump(doc, handle)
        return verify_archive(root, quiet=True)

    check("the archive fixture verifies clean", archive() == 0)
    check("an edited loop count is caught", archive(
        f=lambda d: d["RING_TOPOLOGY.json"]["projects"][0]
        .__setitem__("loops", 6)) == 1)
    check("a swapped cell view hash is caught", archive(
        f=lambda d: d["library_sources.json"]["files"][0]
        .__setitem__("sha256", "f" * 64)) == 1)
    check("a recorded failure is caught", archive(
        f=lambda d: d["RING_TOPOLOGY.json"]["projects"][0]
        .__setitem__("checks_failed", 1)) == 1)
    check("an edited path-net count is caught", archive(
        f=lambda d: d["SPEF_CENSUS.json"]["projects"][0]
        .__setitem__("path_nets", 99)) == 1)
    check("a cell view URL off a commit is caught", archive(
        f=lambda d: d["library_sources.json"]["files"][0]
        .__setitem__("url", "https://x/main/c0")) == 1)

    # The rename control cannot be tripped by any input file, because a file is
    # exactly what it is invariant to. So it is tripped from the other side, by
    # making one step read a net name, which is the failure it exists to catch.
    original = build_graph

    def name_reading_graph(netlist, library, report=None):
        graph = original(netlist, library, report)
        for net in list(graph.succ):
            if "ring0" in net:
                graph.succ[net] = []
        return graph

    globals()["build_graph"] = name_reading_graph
    try:
        checks, _ = run_fixture()
        tripped = sorted(n for n, ok, _ in checks if not ok)
        check("a step that reads a net name trips the rename control",
              "renaming every net and instance changes nothing" in tripped,
              "tripped %s" % tripped)
    finally:
        globals()["build_graph"] = original

    for line in failed:
        print("FAIL %s" % line)
    print("%d checks, %d failed" % (passed[0] + len(failed), len(failed)))
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projects", nargs="*")
    parser.add_argument("--json", dest="json_out")
    parser.add_argument("--fetch-library", action="store_true",
                        dest="fetch_library")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--verify-archive", action="store_true",
                        dest="verify_archive")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.verify_archive:
        return verify_archive()
    if args.fetch_library:
        return fetch_library()
    if not args.projects:
        parser.error("give at least one project directory, or --selftest")
    return run(args.projects, args.json_out)


if __name__ == "__main__":
    sys.exit(main())
