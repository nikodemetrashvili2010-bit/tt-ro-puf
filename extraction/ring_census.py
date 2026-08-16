#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Count the ring oscillators actually present in a hardened netlist.

A ring oscillator is a combinational cycle. Documentation is not evidence that
one was fabricated: synthesis is free to collapse a chain of inverting stages,
and an attribute written for a different tool will not stop it. So this reads
the gate-level netlist that the shuttle hardened and finds the cycles itself.

Used in Phase A to justify target selection before any response is predicted.
It says nothing about which ring is faster than which — that is A.5 onward.

    python3 ring_census.py NETLIST [NETLIST ...]     # census, human readable
    python3 ring_census.py --json OUT NETLIST ...    # census, machine readable
    python3 ring_census.py --selftest                # planted faults
"""

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import tempfile

# sky130_fd_sc_hd output pins. Everything else on a cell is an input, except
# the supply pins, which connect every cell to every other cell and would fuse
# the whole design into one cycle if they were treated as signal.
OUT_PINS = frozenset({"X", "Y", "Q", "Q_N", "COUT", "COUT_N", "SUM", "HI", "LO"})
PWR_PINS = frozenset({"VPWR", "VGND", "VPB", "VNB", "KAPWR", "VPWRIN", "LOWHVPWR"})
# cells whose output does not depend combinationally on their data input
SEQ_MARKERS = ("__df", "__sdf", "__edf", "__dl", "__sedf", "__sdl")

CELL_RE = re.compile(r"(sky130_fd_sc_hd__\w+)\s+(\\?\S+)\s*\(([^;]*?)\)\s*;", re.S)
CONN_RE = re.compile(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)")


def parse(text):
    """Yield (cell_type, instance, inputs, outputs) with supplies dropped."""
    for cell, inst, body in CELL_RE.findall(text):
        ins, outs = [], []
        for pin, net in CONN_RE.findall(body):
            net = net.strip()
            if not net or pin in PWR_PINS:
                continue
            (outs if pin in OUT_PINS else ins).append(net)
        yield cell, inst, ins, outs


def is_sequential(cell):
    return any(m in cell for m in SEQ_MARKERS)


def build_graph(cells):
    graph = collections.defaultdict(set)
    comb = seq = 0
    for cell, _inst, ins, outs in cells:
        if is_sequential(cell):
            seq += 1
            continue
        comb += 1
        for a in ins:
            for b in outs:
                graph[a].add(b)
    return graph, comb, seq


def strong_components(graph):
    """Iterative Tarjan. Recursion depth would not survive a real netlist."""
    index, low, on_stack, stack, order, out = {}, {}, set(), [], [0], []
    nodes = set(graph) | {v for s in graph.values() for v in s}
    for root in sorted(nodes):
        if root in index:
            continue
        index[root] = low[root] = order[0]
        order[0] += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(sorted(graph.get(root, ()))))]
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = order[0]
                    order[0] += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(graph.get(nxt, ())))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp))
    return out


def census(text):
    cells = list(parse(text))
    graph, comb, seq = build_graph(cells)
    rings = strong_components(graph)

    shapes = collections.Counter()
    for ring in rings:
        nets = set(ring)
        members = []
        for cell, _inst, ins, outs in cells:
            if is_sequential(cell):
                continue
            if any(o in nets for o in outs) and any(i in nets for i in ins):
                members.append(cell)
        shapes[tuple(sorted(members))] += 1

    return {
        "combinational_cells": comb,
        "sequential_cells": seq,
        "rings": len(rings),
        "shapes": [
            {"count": n, "cells": len(m), "composition": list(m)}
            for m, n in sorted(shapes.items(), key=lambda kv: -kv[1])
        ],
    }


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(paths, json_out=None):
    results = []
    for path in paths:
        with open(path, errors="replace") as fh:
            data = census(fh.read())
        data["netlist"] = os.path.basename(path)
        data["netlist_sha256"] = sha256_file(path)
        results.append(data)

        print("%s" % path)
        print("   %d combinational cells, %d sequential"
              % (data["combinational_cells"], data["sequential_cells"]))
        print("   %d combinational cycles" % data["rings"])
        for shape in data["shapes"]:
            counts = collections.Counter(shape["composition"])
            desc = ", ".join("%dx %s" % (n, c.replace("sky130_fd_sc_hd__", ""))
                             for c, n in counts.most_common())
            print("      %4d rings of %d cells: %s"
                  % (shape["count"], shape["cells"], desc))
        print()

    if json_out:
        with open(json_out, "w") as fh:
            json.dump({"schema": "phaseA-ring-census/1", "netlists": results},
                      fh, indent=2)
            fh.write("\n")
        print("wrote %s" % json_out)
    return 0


# --------------------------------------------------------------------------
# selftest


def inv(inst, a, y):
    return ("sky130_fd_sc_hd__inv_2 %s (.A(%s), .Y(%s), .VPWR(VPWR), "
            ".VGND(VGND), .VPB(VPWR), .VNB(VGND));\n" % (inst, a, y))


def and2(inst, a, b, x):
    return ("sky130_fd_sc_hd__and2_1 %s (.A(%s), .B(%s), .X(%s), .VPWR(VPWR), "
            ".VGND(VGND), .VPB(VPWR), .VNB(VGND));\n" % (inst, a, b, x))


def dff(inst, d, q):
    return ("sky130_fd_sc_hd__dfxtp_1 %s (.CLK(clk), .D(%s), .Q(%s), "
            ".VPWR(VPWR), .VGND(VGND), .VPB(VPWR), .VNB(VGND));\n"
            % (inst, d, q))


def ring(tag, stages=7, closed=True):
    """A stages-inverter ring gated by an AND, exactly like the target's."""
    out = ""
    for i in range(stages):
        out += inv("%s_i%d" % (tag, i), "%s_n%d" % (tag, i), "%s_n%d" % (tag, i + 1))
    tail = "%s_n%d" % (tag, stages)
    out += and2("%s_en" % tag, tail if closed else "tie_off", "en", "%s_n0" % tag)
    return out


def selftest():
    ok = True

    def check(name, condition):
        nonlocal ok
        print("  %-58s %s" % (name, "pass" if condition else "FAIL"))
        ok = ok and condition

    one = census(ring("r0"))
    check("a closed 7-inverter ring is found", one["rings"] == 1)
    check("its ring is 8 cells", one["shapes"][0]["cells"] == 8)
    check("its ring is 7 inverters and an AND",
          collections.Counter(one["shapes"][0]["composition"])
          == {"sky130_fd_sc_hd__inv_2": 7, "sky130_fd_sc_hd__and2_1": 1})

    cut = census(ring("r0", closed=False))
    check("cutting the feedback removes the ring", cut["rings"] == 0)

    two = census(ring("r0") + ring("r1"))
    check("two independent rings are two, not one", two["rings"] == 2)

    # the fault that would silently merge every ring on the die into one:
    # treating the shared supply pins as signal
    check("shared supplies do not fuse the two rings",
          two["rings"] == 2 and all(s["cells"] == 8 for s in two["shapes"]))

    # a loop that goes through a flop is a state machine, not an oscillator
    seq_loop = dff("f0", "s_q_n", "s_q") + inv("f0i", "s_q", "s_q_n")
    check("a loop closed through a flop is not counted",
          census(seq_loop)["rings"] == 0)

    # and the same loop with the flop replaced by a buffer must be counted, so
    # the check above cannot pass by the parser simply failing
    comb_loop = inv("g0", "s_q_n", "s_q") + inv("g0i", "s_q", "s_q_n")
    check("the same loop without the flop is counted",
          census(comb_loop)["rings"] == 1)

    one_stage = census(ring("r0", stages=1))
    check("a one-inverter ring is found too", one_stage["rings"] == 1)
    check("and is distinguished from a seven-inverter ring",
          one_stage["shapes"][0]["cells"] == 2)

    mixed = census(ring("a", stages=7) + ring("b", stages=1))
    check("rings of different length are reported separately",
          mixed["rings"] == 2 and len(mixed["shapes"]) == 2)

    check("cells outside any ring are not reported as rings",
          census(ring("r0") + inv("stray", "p", "q"))["rings"] == 1)

    check("an empty netlist has no rings", census("")["rings"] == 0)

    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "n.v")
        with open(p, "w") as fh:
            fh.write(ring("r0"))
        check("netlist hash matches hashlib",
              sha256_file(p) == hashlib.sha256(ring("r0").encode()).hexdigest())

    print("\nselftest %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("netlists", nargs="*")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.netlists:
        ap.error("give at least one netlist, or --selftest")
    return run(args.netlists, args.json_out)


if __name__ == "__main__":
    sys.exit(main())
