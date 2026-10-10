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
    # Entered at B1 an o21a_2 passes with either A1 or A2 high, and the
    # two do not time the same. Both builds hold A2 high and A1 low there:
    # _356_ on the two-arm build, all sixteen Arm B paths, and _447_ on the
    # release build, C00 to C03. This line had A1 until 2026-10-10, so the
    # two-arm archive in mux/ and the B00 and B15 boundary decks were made
    # with the other input high. --check-sides holds this table to the
    # netlist's own decode.
    "sky130_fd_sc_hd__o21a_2": {
        "A1": {"A2": 0, "B1": 1},
        "A2": {"A1": 0, "B1": 1},
        "B1": {"A1": 0, "A2": 1}},
    "sky130_fd_sc_hd__a21bo_2": {
        # X = (A1 & A2) | ~B1_N
        "A1": {"A2": 1, "B1_N": 1},
        "A2": {"A1": 1, "B1_N": 1}},
    "sky130_fd_sc_hd__and3_2": {
        "A": {"B": 1, "C": 1},
        "B": {"A": 1, "C": 1},
        "C": {"A": 1, "B": 1}},
    "sky130_fd_sc_hd__and3b_2": {
        # X = ~A_N & B & C
        "B": {"A_N": 0, "C": 1},
        "C": {"A_N": 0, "B": 1}},
    "sky130_fd_sc_hd__o21ba_2": {
        # X = (A1 | A2) & ~B1_N
        "A1": {"A2": 0, "B1_N": 0},
        "A2": {"A1": 0, "B1_N": 0}},
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
#
# Not every data pin can be blocked from the side. A pin that enters an
# AND-OR cell as a bare OR term, a211o's B1 and C1, a221o's C1, a21o's
# B1, reaches the output whatever the other pins do; on the chip those
# pins are driven by the decode upstream, so the real block sits one cell
# earlier. The two-arm selector never ended a path on one of these. The
# three-arm one ends 32 of 48 on a211o's B1 or C1, and the first control
# run through it produced edges on all 32 because the block was being
# applied to a pin it could not hold. The control now blocks at the last
# cell on the path that can block, and leaves the cells after it open, so
# a silent output also shows those open cells generate nothing on their
# own.
UNBLOCKABLE = {
    ("sky130_fd_sc_hd__a211o_2", "B1"),
    ("sky130_fd_sc_hd__a211o_2", "C1"),
    ("sky130_fd_sc_hd__a221o_2", "C1"),
    ("sky130_fd_sc_hd__a21o_2", "B1"),
}
BLOCK = {
    "sky130_fd_sc_hd__a221o_2": {"A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0},
    "sky130_fd_sc_hd__a22o_2":  {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "sky130_fd_sc_hd__a21o_2":  {"A1": 0, "A2": 0, "B1": 0},
    "sky130_fd_sc_hd__a211o_2": {"A1": 0, "A2": 0, "B1": 0, "C1": 0},
    "sky130_fd_sc_hd__o21a_2":  {"A1": 0, "A2": 0, "B1": 0},
    "sky130_fd_sc_hd__a21bo_2": {"A1": 0, "A2": 0, "B1_N": 1},
    "sky130_fd_sc_hd__and3_2":  {"A": 0, "B": 0, "C": 0},
    "sky130_fd_sc_hd__and3b_2": {"A_N": 1, "B": 0, "C": 0},
    "sky130_fd_sc_hd__o21ba_2": {"A1": 0, "A2": 0, "B1_N": 1},
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
    # Arm C exists only in the three-arm build. Its buffers sit under
    # g_armc[i].u_roc, so the two-arm netlist has none and the list stays
    # at 32, which keeps the archived decks regenerating byte for byte.
    for i in range(16):
        key = "\\u_puf.u_core.g_armc[%d].u_roc.u_buf" % i
        if key in insts:
            src = insts[key][1]["X"]
            out.append(("C%02d" % i, src, walk(src)))
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
    block_at = None
    if control:
        for k, (_, icell, ipin, _, _) in enumerate(path):
            if (icell, ipin) not in UNBLOCKABLE:
                block_at = k
        if block_at is None:
            raise SystemExit("%s: no cell on the path can block it: %s"
                             % (tag, " ".join(c + "." + p for _, c, p, _, _ in path)))
    chain = " ".join(c.replace("sky130_fd_sc_hd__", "") + "." + pin
                     for _, c, pin, _, _ in path)
    lines.append("* --- selector path for oscillator %s, %d cells, %s ---"
                 % (tag, len(path), kind))
    if control and block_at != len(path) - 1:
        lines.append("* blocked at cell %d of %d, %s; the cells after it are open"
                     % (block_at + 1, len(path),
                        path[block_at][1].replace("sky130_fd_sc_hd__", "")
                        + "." + path[block_at][2]))
    lines.append("* chain: %s" % chain)
    lines.append("* the extracted ring tap b_out stands in for this oscillator")
    lines.append("Vone ONE 0 %g" % v)

    rename = {src_net: "b_out"}
    missing = []
    for k, (iname, icell, ipin, innet, outnet) in enumerate(path):
        if control and k == block_at:
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


# --- the table against the netlist, --check-sides ---------------------------
#
# Every tie in CELLS is a claim about the chip: with this oscillator selected,
# this side input sits at this level. Until 2026-10-10 nothing tested it, and
# the o21a_2 line was wrong on both builds from the first sweep on. This works
# the levels out of the netlist's own decode and fails on any tie that
# disagrees.
#
# A level is 0, 1 or None for unknown. The selection register is the only
# state that gets set; every other flop is unknown and so is the running ring.
# A stopped ring's output is low. Its NAND holds n[0] high once the enable
# drops and fifteen inverters bring the tap n[15] down, the same in
# ro_macro.v, ro_armc.v and the hard macro's own netlist.

def _and(*v):
    return 0 if 0 in v else (None if None in v else 1)


def _or(*v):
    return 1 if 1 in v else (None if None in v else 0)


def _not(a):
    return None if a is None else 1 - a


def _mux(s, a0, a1):
    if s is None:
        return a0 if a0 == a1 else None
    return a1 if s else a0


LOGIC = {
    "inv":           lambda p: _not(p["A"]),
    "clkinv":        lambda p: _not(p["A"]),
    "buf":           lambda p: p["A"],
    "bufbuf":        lambda p: p["A"],
    "clkbuf":        lambda p: p["A"],
    "clkdlybuf4s15": lambda p: p["A"],
    "clkdlybuf4s18": lambda p: p["A"],
    "clkdlybuf4s25": lambda p: p["A"],
    "clkdlybuf4s50": lambda p: p["A"],
    "dlygate4sd1":   lambda p: p["A"],      # hold buffers, which start "dl"
    "dlygate4sd2":   lambda p: p["A"],      # like a latch and are not one
    "dlygate4sd3":   lambda p: p["A"],
    "dlymetal6s2s":  lambda p: p["A"],
    "dlymetal6s4s":  lambda p: p["A"],
    "dlymetal6s6s":  lambda p: p["A"],
    "and2":          lambda p: _and(p["A"], p["B"]),
    "and2b":         lambda p: _and(_not(p["A_N"]), p["B"]),
    "and3":          lambda p: _and(p["A"], p["B"], p["C"]),
    "and3b":         lambda p: _and(_not(p["A_N"]), p["B"], p["C"]),
    "nand2":         lambda p: _not(_and(p["A"], p["B"])),
    "nor2":          lambda p: _not(_or(p["A"], p["B"])),
    "a21o":          lambda p: _or(_and(p["A1"], p["A2"]), p["B1"]),
    "a21bo":         lambda p: _or(_and(p["A1"], p["A2"]), _not(p["B1_N"])),
    "a211o":         lambda p: _or(_and(p["A1"], p["A2"]), p["B1"], p["C1"]),
    "a22o":          lambda p: _or(_and(p["A1"], p["A2"]),
                                   _and(p["B1"], p["B2"])),
    "a221o":         lambda p: _or(_and(p["A1"], p["A2"]),
                                   _and(p["B1"], p["B2"]), p["C1"]),
    "o21a":          lambda p: _and(_or(p["A1"], p["A2"]), p["B1"]),
    "o21ba":         lambda p: _and(_or(p["A1"], p["A2"]), _not(p["B1_N"])),
    "mux2":          lambda p: _mux(p["S"], p["A0"], p["A1"]),
    "mux4":          lambda p: _mux(p["S1"], _mux(p["S0"], p["A0"], p["A1"]),
                                    _mux(p["S0"], p["A2"], p["A3"])),
}


def net_levels(insts, ring_slot, sel_bits, slot):
    """Level of any net with oscillator `slot` selected and its window open."""
    drivers = {}
    for name, (cell, pins) in insts.items():
        for pin, net in pins.items():
            if net and pin in OUT_PINS:
                drivers[net] = (name, pin)
    memo = {}

    def level(net):
        if net in memo:
            return memo[net]
        memo[net] = None                     # a loop reads as unknown
        if net in ring_slot:
            v = None if ring_slot[net] == slot else 0
        elif net in sel_bits:
            v = (slot >> sel_bits[net]) & 1
        elif net not in drivers:
            v = None                         # a pin of the project
        else:
            name, opin = drivers[net]
            cell, pins = insts[name]
            base = re.sub(r'_\d+$', '', cell.replace("sky130_fd_sc_hd__", ""))
            if base == "conb":
                v = 1 if opin == "HI" else 0
            elif base in LOGIC:
                v = LOGIC[base]({p: level(n) for p, n in pins.items()
                                 if p not in OUT_PINS and p not in PWR_PINS})
            elif re.match(r'(df|dl|sdf|edf)', base):
                v = None                     # state nobody set
            else:
                raise SystemExit("--check-sides: no logic written for %s (%s)"
                                 % (cell, name))
        memo[net] = v
        return v
    return level


def slot_of(tag):
    return {"A": 0, "B": 16, "C": 32}[tag[0]] + int(tag[1:])


def check_sides(build_dir, cells=None):
    """Every CELLS tie on every path, held to the netlist's own decode."""
    cells = CELLS if cells is None else cells
    netlist = os.path.join(build_dir, os.path.basename(NETLIST))
    insts, loads = read_netlist(netlist)
    paths = find_paths(insts, loads)
    sel_bits = {}
    for cell, pins in insts.values():
        q = pins.get("Q", "")
        m = re.match(r'\\u_puf\.u_core\.active_sel\[(\d+)\]$', q)
        if m:
            sel_bits[q] = int(m.group(1))
    if not sel_bits:
        raise SystemExit("--check-sides: no active_sel flops in %s"
                         % build_dir)
    ring_slot = {src: slot_of(tag) for tag, src, _ in paths}
    compared, bad = 0, []
    for tag, src, path in paths:
        if not path:
            raise SystemExit("--check-sides: no selector path for %s" % tag)
        level = net_levels(insts, ring_slot, sel_bits, slot_of(tag))
        for iname, icell, ipin, _, _ in path:
            for pin, want in sorted(cells[icell][ipin].items()):
                got = level(insts[iname][1][pin])
                compared += 1
                if got != want:
                    bad.append((tag, iname, icell, pin, want, got))
    return compared, len(paths), bad


def selftest():
    """Plant wrong ties and a missing cell; each has to be caught, alone."""
    import copy
    builds = {"two-arm": os.path.join(ROOT, "dualarm", "build_current"),
              "release": os.path.join(ROOT, "dualarm", "build_armc")}
    ok = True

    def expect(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  %-52s %s" % (name, "ok" if good else "FAILED: %r" % (got,)))

    for label, b in builds.items():
        n, npaths, bad = check_sides(b)
        expect("%s, table as it stands: %d ties" % (label, n),
               (n > 0, bad), (True, []))
    old = copy.deepcopy(CELLS)
    old["sky130_fd_sc_hd__o21a_2"]["B1"] = {"A1": 1, "A2": 0}
    _, _, bad = check_sides(builds["release"], old)
    expect("release, the o21a_2 line as it was",
           sorted({(t, i) for t, i, _, _, _, _ in bad}),
           [("C0%d" % k, "_447_") for k in range(4)])
    _, _, bad = check_sides(builds["two-arm"], old)
    expect("two-arm, the o21a_2 line as it was",
           sorted({(t, i) for t, i, _, _, _, _ in bad}),
           [("B%02d" % k, "_356_") for k in range(16)])
    wrong = copy.deepcopy(CELLS)
    wrong["sky130_fd_sc_hd__a22o_2"]["A1"]["A2"] = 0
    _, _, bad = check_sides(builds["release"], wrong)
    expect("release, a22o_2 at A1 with its partner low",
           sorted({(c, p, w) for _, _, c, p, w, _ in bad}),
           [("sky130_fd_sc_hd__a22o_2", "A2", 0)])
    kept = LOGIC.pop("and2b")
    try:
        check_sides(builds["release"])
        expect("release, no logic for and2b", "passed", "stopped")
    except SystemExit:
        expect("release, no logic for and2b", "stopped", "stopped")
    finally:
        LOGIC["and2b"] = kept
    print("selftest: %s" % ("all caught" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", default="/tmp/muxsweep")
    ap.add_argument("--corner", default="ff", choices=sorted(CORNERS),
                    help="PVT corner (default ff, the demanding one)")
    ap.add_argument("--lib", default=None,
                    help="sky130_fd_sc_hd.spice; default is the path the "
                         "matched-macro template already includes")
    ap.add_argument("--build", default=BUILD,
                    help="build directory holding the routed netlist and nominal "
                         "SPEF (default dualarm/build_current, the two-arm archive; "
                         "point it at the three-arm build to sweep its 48 paths)")
    ap.add_argument("--control", action="store_true",
                    help="also write blocked-path controls, which must show no "
                         "output edges at all")
    ap.add_argument("--check-sides", action="store_true",
                    help="hold every side tie to the netlist's decode and "
                         "write nothing; needs no PDK")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.check_sides:
        n, npaths, bad = check_sides(os.path.abspath(args.build))
        for tag, iname, icell, pin, want, got in bad:
            print("  %s %s %s.%s: table %s, netlist %s"
                  % (tag, iname, icell.replace("sky130_fd_sc_hd__", ""),
                     pin, want, got))
        print("side ties: %d on %d paths held to the netlist, %d disagree"
              % (n, npaths, len(bad)))
        return 1 if bad or not n else 0
    corner = CORNERS[args.corner]

    lib = args.lib
    if lib is None:
        lib = str(sky130_spice_paths()[1])   # same resolution run_ngspice.py uses
    order = read_pin_order(lib)

    build_dir = os.path.abspath(args.build)
    insts, loads = read_netlist(os.path.join(build_dir, os.path.basename(NETLIST)))
    caps = read_spef_caps(os.path.join(build_dir, os.path.basename(SPEF)))
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
                                      " plus %d blocked controls" % len(paths) if args.control else ""))
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
    sys.exit(main())
