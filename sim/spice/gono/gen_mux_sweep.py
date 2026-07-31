#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Fast-corner check of the 32-to-1 selection path, hardware item 2.

One oscillator at a time reaches the counter through a synthesized selector, and
a fixed delay through that selector is harmless because a delay does not change
a frequency. What would not be harmless is a path that narrows or swallows a
pulse, because then the count depends on routing instead of on the oscillator,
which is the confound this chip exists to measure.

The selector is not a tidy tree. Read out of the routed netlist, the 32 sources
reach `sel_ro` through three to five cells of mixed type, a221o_2, a22o_2,
a21o_2, a211o_2, mux4_2 and a final o21a_2, and no two arms are wired the same
way. That asymmetry is the reason for checking every source rather than one.

Each deck here carries the real cells of one source's path, taken from the
routed netlist, with each intermediate net loaded by its own total capacitance
from the routed SPEF. Side inputs are held at the levels that open that path.
The stimulus is the same for all 32: the extracted Arm B ring from
`ro_macro_matched.spice`, which at the fast corner runs near the 888 MHz the
corner sweep found, so the edge shape driving the selector is a real ring edge
rather than an invented one. Holding the stimulus fixed means any difference
between the 32 results belongs to the path.

The deck ends in the same first ripple stage the flop sweep used, a real
dfrtp_2 wired as a toggle, so the question asked is the one the design relies
on: does every edge that leaves the oscillator arrive at the counter.

Run (WSL, after the usual PDK_ROOT and PDK exports):
    python3 gen_mux_sweep.py --output-dir /tmp/muxsweep --corner ff
    cd /tmp/muxsweep
    for f in mux_*.spice; do python3 <gono>/../run_ngspice.py "$f" --log "${f%.spice}.log"; done
    python3 <gono>/analyze_mux_sweep.py /tmp/muxsweep
"""

import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pdk_paths import atomic_write_text, sky130_spice_paths  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BUILD = os.path.join(ROOT, "dualarm", "build_current")
NETLIST = os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.nl.v")
SPEF = os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
TEMPLATE = os.path.join(HERE, "ro_macro_matched.spice")

TARGET = r"\u_puf.u_core.sel_ro"

# Same corner definitions as gen_dualarm_decks.py and gen_flop_sweep.py.
CORNERS = {
    "tt": dict(section="tt", temp=27,  supply=1.80),
    "ss": dict(section="ss", temp=100, supply=1.60),
    "ff": dict(section="ff", temp=-40, supply=1.95),
}

T_END_NS = 42.0      # ring starts at 2 ns, so about 30 edges to count
T_CTRL_NS = 16.0     # a blocked path only has to prove it stays quiet
T_STEP_PS = 1        # 1 ps, fine enough to time a 500 ps level

OUT_PINS = {"X", "Y", "Q", "Q_N", "COUT", "SUM", "HI", "LO", "out"}
PWR_PINS = {"VPWR", "VGND", "VPB", "VNB"}

# Pin order of every cell a selector path can contain, taken from the sky130
# high-density SPICE library, plus what the other inputs must be for the named
# data pin to pass. AND-OR and OR-AND cells are non-inverting on every data pin,
# so sel_ro follows the ring rather than its complement.
# What each selector cell computes, and therefore what the other inputs must be
# for the named data pin to reach the output. Only the boolean function is
# written down here. The pin ORDER is never assumed: it is read from the PDK's
# own subckt line at generation time, because getting an order wrong by hand is
# exactly the kind of silent error this whole check exists to catch.
#
#   a221o  X = (A1 & A2) | (B1 & B2) | C1
#   a22o   X = (A1 & A2) | (B1 & B2)
#   a21o   X = (A1 & A2) | B1
#   a211o  X = (A1 & A2) | B1 | C1
#   o21a   X = (A1 | A2) & B1
#   mux4   X = A0..A3 chosen by S1:S0
#   mux2   X = A0 or A1 chosen by S
#
# Every one of these is non-inverting on every data pin, so sel_ro follows the
# ring rather than its complement, and the first counter flop sees ring edges.
#
# A useful property of setting side inputs this way: if any of these assignments
# were wrong, the cell would hold its output constant and the deck would deliver
# zero edges, which the analyzer fails on. A mistake here cannot pass quietly.
CELLS = {
    "sky130_fd_sc_hd__a221o_2": {
        "A1": {"A2": 1, "B1": 0, "B2": 0, "C1": 0},
        "A2": {"A1": 1, "B1": 0, "B2": 0, "C1": 0},
        "B1": {"B2": 1, "A1": 0, "A2": 0, "C1": 0},
        "B2": {"B1": 1, "A1": 0, "A2": 0, "C1": 0},
        "C1": {"A1": 0, "A2": 0, "B1": 0, "B2": 0}},
    "sky130_fd_sc_hd__a22o_2": {
        "A1": {"A2": 1, "B1": 0, "B2": 0},
        "A2": {"A1": 1, "B1": 0, "B2": 0},
        "B1": {"B2": 1, "A1": 0, "A2": 0},
        "B2": {"B1": 1, "A1": 0, "A2": 0}},
    "sky130_fd_sc_hd__a21o_2": {
        "A1": {"A2": 1, "B1": 0},
        "A2": {"A1": 1, "B1": 0},
        "B1": {"A1": 0, "A2": 0}},
    "sky130_fd_sc_hd__a211o_2": {
        "A1": {"A2": 1, "B1": 0, "C1": 0},
        "A2": {"A1": 1, "B1": 0, "C1": 0},
        "B1": {"A1": 0, "A2": 0, "C1": 0},
        "C1": {"A1": 0, "A2": 0, "B1": 0}},
    "sky130_fd_sc_hd__o21a_2": {
        "A1": {"A2": 0, "B1": 1},
        "A2": {"A1": 0, "B1": 1},
        "B1": {"A1": 1, "A2": 0}},
    "sky130_fd_sc_hd__mux4_2": {
        "A0": {"S0": 0, "S1": 0, "A1": 0, "A2": 0, "A3": 0},
        "A1": {"S0": 1, "S1": 0, "A0": 0, "A2": 0, "A3": 0},
        "A2": {"S0": 0, "S1": 1, "A0": 0, "A1": 0, "A3": 0},
        "A3": {"S0": 1, "S1": 1, "A0": 0, "A1": 0, "A2": 0}},
    "sky130_fd_sc_hd__mux2_1": {
        "A0": {"S": 0, "A1": 0},
        "A1": {"S": 1, "A0": 0}},
}

# The side value that blocks a path instead of opening it, used by --control.
# Forcing the final cell's data pin to be ignored must yield a silent output.
BLOCK = {
    "sky130_fd_sc_hd__a221o_2": {"A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0},
    "sky130_fd_sc_hd__a22o_2":  {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "sky130_fd_sc_hd__a21o_2":  {"A1": 0, "A2": 0, "B1": 0},
    "sky130_fd_sc_hd__a211o_2": {"A1": 0, "A2": 0, "B1": 0, "C1": 0},
    "sky130_fd_sc_hd__o21a_2":  {"A1": 0, "A2": 0, "B1": 0},
    "sky130_fd_sc_hd__mux4_2":  {"A0": 0, "A1": 0, "A2": 0, "A3": 0, "S0": 0, "S1": 0},
    "sky130_fd_sc_hd__mux2_1":  {"A0": 0, "A1": 0, "S": 0},
}


def read_pin_order(lib_path):
    """Pin order of every cell in the decks, straight out of the PDK.

    Nothing about cell pin order is written down in this file. If the library
    ever reorders a port, or if a cell is missing, this raises instead of
    quietly building a deck that wires the wrong pins together.
    """
    order = {}
    want = set(CELLS) | {"sky130_fd_sc_hd__inv_1", "sky130_fd_sc_hd__dfrtp_2"}
    with open(lib_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.lower().startswith(".subckt"):
                continue
            parts = line.split()
            if len(parts) > 2 and parts[1] in want:
                order[parts[1]] = parts[2:]
    missing = sorted(want - set(order))
    if missing:
        raise SystemExit("cells absent from %s: %s" % (lib_path, ", ".join(missing)))
    for cell, table in CELLS.items():
        named = set(order[cell])
        for data_pin, sides in table.items():
            unknown = ({data_pin} | set(sides)) - named
            if unknown:
                raise SystemExit("cell %s has no pin %s in the PDK; its ports are %s"
                                 % (cell, ", ".join(sorted(unknown)), " ".join(order[cell])))
    return order


def read_netlist(path):
    text = open(path, encoding="utf-8").read()
    pat = re.compile(r'\b(sky130_fd_sc_hd__[a-z0-9_]+|ro_macro_hard)\s+(\S+)\s*\((.*?)\);', re.S)
    insts = {}
    for m in pat.finditer(text):
        pins = dict(re.findall(r'\.(\w+)\s*\(\s*([^)]*?)\s*\)', m.group(3)))
        insts[m.group(2)] = (m.group(1), pins)
    loads = defaultdict(list)
    for name, (cell, pins) in insts.items():
        for pin, net in pins.items():
            if net and pin not in OUT_PINS and pin not in PWR_PINS:
                loads[net].append((name, cell, pin))
    return insts, loads


def read_spef_caps(path):
    """Total capacitance per net, in farads, keyed by netlist-style name.

    The D_NET header already carries the net's total, which is the same lumped
    convention gen_decks.py uses, so nothing is re-derived here.
    """
    names, caps = {}, {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("*") and not line.startswith("*D_NET"):
                m = re.match(r'\*(\d+)\s+(\S+)\s*$', line)
                if m:
                    names[m.group(1)] = m.group(2)
                    continue
            if line.startswith("*D_NET"):
                parts = line.split()
                key = parts[1]
                if key.startswith("*"):
                    key = names.get(key[1:], key)
                caps[key] = float(parts[2]) * 1e-12
    return caps


def spef_key(netlist_name):
    """Netlist escaped identifier to the name the SPEF uses.

    OpenROAD drops the leading backslash of a Verilog escaped identifier and
    then backslash-escapes each dot and bracket inside it, so
    `\\u_puf.u_core.sel_ro` is written `u_puf\\.u_core\\.sel_ro`.
    """
    n = netlist_name[1:] if netlist_name.startswith("\\") else netlist_name
    return re.sub(r'([.\[\]])', r'\\\1', n)


def find_paths(insts, loads):
    """Forward walk from each oscillator output to sel_ro, data path only."""
    import collections

    def walk(start):
        q = collections.deque([(start, [])])
        best = {}
        while q:
            net, acc = q.popleft()
            if net == TARGET:
                return acc
            if len(acc) > 8:
                continue
            for iname, icell, ipin in loads.get(net, []):
                if icell not in CELLS:
                    continue
                outs = [n for p, n in insts[iname][1].items() if p in OUT_PINS and n]
                if not outs:
                    continue
                onet = outs[0]
                if best.get(onet, 99) <= len(acc):
                    continue
                best[onet] = len(acc)
                q.append((onet, acc + [(iname, icell, ipin, net, onet)]))
        return None

    out = []
    for i in range(16):
        src = insts["\\u_puf.u_core.g_ro_bank[%d].u_ro.u_buf" % i][1]["X"]
        out.append(("A%02d" % i, src, walk(src)))
    for i in range(16):
        src = insts["u_rob%d" % i][1]["out"]
        out.append(("B%02d" % i, src, walk(src)))
    return out


def node(net):
    """A net name ngspice will accept."""
    n = net[1:] if net.startswith("\\") else net
    return re.sub(r'[^A-Za-z0-9_]', "_", n)


def stimulus(corner):
    """The parasitic half of the matched-macro deck, up to and including b_out."""
    keep = []
    for line in open(TEMPLATE, encoding="utf-8").read().splitlines():
        s = line.strip()
        if s.startswith(".lib "):
            keep.append(re.sub(r'(\.lib\s+\S+)\s+\w+$', r'\1 ' + corner["section"], line))
            if corner["temp"] != 27:
                keep.append(".temp %g" % corner["temp"])
        elif s.startswith(".param SUPPLY"):
            keep.append(".param SUPPLY=%g" % corner["supply"])
        elif s.startswith("Ven "):
            keep.append("Ven EN 0 PULSE(0 %g 2n 50p 50p 1 2)" % corner["supply"])
        elif s.startswith("Xa_") or s.startswith("Ca_"):
            continue                      # control ring not needed here
        elif s.startswith((".save", ".tran", ".control", "meas ", "let ", "print ",
                           ".endc", ".end")):
            break
        else:
            keep.append(line)
    return keep


def build(tag, src_net, path, caps, corner, order, control=False):
    """One deck: this oscillator's real selector cells into a real first flop."""
    v = corner["supply"]
    lines = stimulus(corner)
    lines.append("")
    kind = "blocked control" if control else "open path"
    chain = " ".join(c.replace("sky130_fd_sc_hd__", "") + "." + pin
                     for _, c, pin, _, _ in path)
    lines.append("* --- selector path for oscillator %s, %d cells, %s ---"
                 % (tag, len(path), kind))
    lines.append("* chain: %s" % chain)
    lines.append("* the extracted ring tap b_out stands in for this oscillator")
    lines.append("Vone ONE 0 %g" % v)

    rename = {src_net: "b_out"}
    missing = []
    for k, (iname, icell, ipin, innet, outnet) in enumerate(path):
        last = (k == len(path) - 1)
        if control and last:
            sides = dict(BLOCK[icell])
            sides.pop(ipin, None)
            conn = {ipin: rename.get(innet, node(innet))}
        else:
            sides = CELLS[icell][ipin]
            conn = {ipin: rename.get(innet, node(innet))}
        for pin, val in sides.items():
            conn[pin] = "ONE" if val else "0"
        args = []
        for pin in order[icell]:
            if pin in ("VGND", "VNB"):
                args.append("0")
            elif pin in ("VPB", "VPWR"):
                args.append("VPWR")
            elif pin in ("X", "Y"):
                args.append(node(outnet))
            else:
                args.append(conn.get(pin, "0"))
        lines.append("Xsel%d %s %s" % (k, " ".join(args), icell))
        c = caps.get(spef_key(outnet))
        if c is None:
            missing.append(outnet)
        else:
            lines.append("Csel%d %s 0 %.6e" % (k, node(outnet), c))

    sel = node(TARGET)
    ff_args = []
    for pin in order["sky130_fd_sc_hd__dfrtp_2"]:
        ff_args.append({"CLK": sel, "D": "qbar", "RESET_B": "RSTN", "Q": "q",
                        "VGND": "0", "VNB": "0", "VPB": "VPWR",
                        "VPWR": "VPWR"}.get(pin, "0"))
    inv_args = []
    for pin in order["sky130_fd_sc_hd__inv_1"]:
        inv_args.append({"A": "q", "Y": "qbar", "VGND": "0", "VNB": "0",
                         "VPB": "VPWR", "VPWR": "VPWR"}.get(pin, "0"))
    lines += [
        "",
        "* --- first ripple stage, a real dfrtp_2 wired as a toggle flop ---",
        "Vrstn RSTN 0 PULSE(0 %g 1n 50p 50p 500n 1000n)" % v,
        "Xff_inv %s sky130_fd_sc_hd__inv_1" % " ".join(inv_args),
        "Xff %s sky130_fd_sc_hd__dfrtp_2" % " ".join(ff_args),
        "",
        ".save v(b_out) v(%s) v(q)" % sel,
        ".tran %dp %.1fn" % (T_STEP_PS, T_CTRL_NS if control else T_END_NS),
        ".control",
        "run",
        "set wr_vecnames",
        "wrdata mux_%s.raw.txt v(b_out) v(%s) v(q)" % (tag, sel),
        "quit",
        ".endc",
        ".END",
    ]
    return "\n".join(lines) + "\n", missing


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", default="/tmp/muxsweep")
    ap.add_argument("--corner", default="ff", choices=sorted(CORNERS),
                    help="PVT corner (default ff, the demanding one)")
    ap.add_argument("--lib", default=None,
                    help="sky130_fd_sc_hd.spice; default is the path the "
                         "matched-macro template already includes")
    ap.add_argument("--control", action="store_true",
                    help="also write blocked-path controls, which must show no "
                         "output edges at all")
    args = ap.parse_args()
    corner = CORNERS[args.corner]

    lib = args.lib
    if lib is None:
        lib = str(sky130_spice_paths()[1])   # same resolution run_ngspice.py uses
    order = read_pin_order(lib)

    insts, loads = read_netlist(NETLIST)
    caps = read_spef_caps(SPEF)
    paths = find_paths(insts, loads)
    os.makedirs(args.output_dir, exist_ok=True)

    unreached = [t for t, _, p in paths if not p]
    if unreached:
        raise SystemExit("no selector path found for: %s" % ", ".join(unreached))

    all_missing = []
    for tag, src, path in paths:
        text, missing = build(tag, src, path, caps, corner, order)
        atomic_write_text(os.path.join(args.output_dir, "mux_%s.spice" % tag), text)
        all_missing += missing
    if args.control:
        for tag, src, path in paths:
            text, _ = build("ctl" + tag, src, path, caps, corner, order, control=True)
            atomic_write_text(os.path.join(args.output_dir, "mux_ctl%s.spice" % tag), text)

    depths = [len(p) for _, _, p in paths]
    print("corner %s: %g C, %g V" % (args.corner, corner["temp"], corner["supply"]))
    print("wrote %d decks to %s%s" % (len(paths), args.output_dir,
                                      " plus 32 blocked controls" if args.control else ""))
    print("selector depth: %d to %d cells, %d distinct depths"
          % (min(depths), max(depths), len(set(depths))))
    for tag, _, path in paths:
        print("  %s  %s" % (tag, " ".join(c.replace("sky130_fd_sc_hd__", "") + "." + p
                                          for _, c, p, _, _ in path)))
    if all_missing:
        print("WARNING: %d nets had no SPEF entry and carry no load: %s"
              % (len(all_missing), ", ".join(sorted(set(all_missing))[:5])))
    else:
        print("every intermediate net carries its own SPEF capacitance")
    print("pin order for %d cells read from %s" % (len(order), lib))


if __name__ == "__main__":
    main()
