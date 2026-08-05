#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Per-instance Arm B integration, hardware item 8.

Every Arm B number I have quoted so far comes from simulating the macro once.
That is defensible for the inside of the ring, because the sixteen copies are one
GDS stamped down sixteen times and the extractor cannot even tell them apart: the
top SPEF contains no net that lives inside a macro. It is not defensible for the
outside. Each copy sits somewhere different on the tile, with its own enable
route arriving and its own output route leaving, and the top SPEF does carry
those thirty-two nets. Their capacitance ranges from 1.00 to 12.81 fF on the
enable side and 2.89 to 29.46 fF on the output side, a factor of ten in each
direction. So "Arm B is one number" is currently an assumption about the parts
the extraction can see, and this deck is the test of it.

What the deck contains, in one file so that one ngspice run answers the whole
question:

  c_    control, the macro topology with no capacitance anywhere. Its frequency
        has to land on the same control value every other deck in this project
        returns at the same corner, 633.640 MHz at tt. That is what says the deck
        itself is built right rather than merely self-consistent.
  r_    reference, the macro plus its own internal extracted capacitance and
        nothing external. This is the existing Arm B model, the one that produced
        the number the paper quotes.
  k00_ .. k15_
        the sixteen real instances. Same internal macro model as r_, byte for
        byte, plus that instance's real enable driver, its real enable route, its
        real output route and the real selector cell the route ends at, all taken
        from the routed netlist and the top SPEF.

Because r_ sits in the same deck as the sixteen, the comparison does not depend
on the absolute frequency at all. The absolute value moves with the transient
timestep by about 0.2%, which is why I stopped quoting it to four digits, but
every ring in one deck sees the same timestep, so a difference between k05_ and
r_ is a difference in the circuit.

Two routes are modelled as the extraction wrote them, not lumped: series
resistors, per-node capacitance and coupling. Coupling that leaves the net is
grounded, and here that is the physically right model rather than a
simplification. The RTL drives one Arm B enable at a time,

    assign armb_en[i] = en_window & (active_sel == SB[SEL_W-1:0]);

so while ring i is being measured the other fifteen rings are stopped, their
outputs are static, and every enable except one is static too. A quiet neighbour
is exactly what a grounded coupling capacitor represents. There are 29 coupling
capacitors joining two Arm B boundary nets and this is why they are grounded.

What could still be wrong, written down so it is not discovered later. The macro
pin metal is extracted twice, once from inside the macro and once from the top,
so roughly 0.3 fF at each pin is counted twice. Both pins sit outside the
oscillator loop, so this cannot reach the frequency. And nothing here models
supply, which is item 5.

Run (WSL, after the usual PDK_ROOT and PDK exports):
    python3 gen_instance_decks.py --output-dir /tmp/inst
    python3 ../run_ngspice.py /tmp/inst/armb_instances.spice --log /tmp/inst/armb_instances_out.txt
    python3 analyze_instance.py --log /tmp/inst/armb_instances_out.txt \\
        --csv /tmp/inst/instance_parasitics.csv
"""

import argparse
import csv
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BUILD = os.path.join(ROOT, "dualarm", "build_current")
NETLIST = os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.nl.v")
TOP_SPEF = os.path.join(BUILD, "tt_um_nikodemetrashvili20_ro_puf.nom.spef")
MACRO_SPEF = os.path.join(ROOT, "macro", "romacro_final", "spef", "nom",
                          "ro_macro_hard.nom.spef")

sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
from pdk_paths import atomic_write_text, sky130_spice_paths  # noqa: E402

# The side-input table lives in gen_mux_sweep and is imported rather than copied.
# It is the part of this deck most able to be wrong quietly, and two copies of it
# would drift apart the first time either is corrected.
sys.path.insert(0, HERE)
from gen_mux_sweep import CELLS  # noqa: E402

NRO, NINV, TAP = 16, 30, 15

CORNERS = {
    "tt": dict(section="tt", temp=27,  supply=1.80, tstop_ns=80),
    "ss": dict(section="ss", temp=100, supply=1.60, tstop_ns=300),
    "ff": dict(section="ff", temp=-40, supply=1.95, tstop_ns=80),
}

# The enable arrives through one of these. Only the boolean is written down; the
# pin order is read from the PDK. A wrong side value on an AND holds the output
# low, the ring never starts, and the analyzer reports a dead instance, so a
# mistake here cannot pass as a result.
ENABLE_DRIVERS = {
    "sky130_fd_sc_hd__and3_2": {"data": "A", "sides": {"B": 1, "C": 1}},
    "sky130_fd_sc_hd__and2_2": {"data": "A", "sides": {"B": 1}},
    "sky130_fd_sc_hd__and4_2": {"data": "A", "sides": {"B": 1, "C": 1, "D": 1}},
}

MACRO_CELLS = ("sky130_fd_sc_hd__clkdlybuf4s25_1", "sky130_fd_sc_hd__nand2_1",
               "sky130_fd_sc_hd__inv_1", "sky130_fd_sc_hd__buf_1")
OUT_PINS = {"X", "Y"}
PWR = {"VGND": "0", "VNB": "0", "VPB": "VPWR", "VPWR": "VPWR"}


# ---------------------------------------------------------------- PDK and files

def read_pin_order(lib_path, want):
    """Pin order of the named cells, straight out of the PDK's own subckt lines.

    gen_mux_sweep has a version of this with a fixed cell list. This one takes
    the list as an argument because the cells here are discovered from the
    netlist rather than known in advance. Nothing about pin order is written
    down in this file.
    """
    order = {}
    with open(lib_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.lower().startswith(".subckt"):
                continue
            parts = line.split()
            if len(parts) > 2 and parts[1] in want:
                order[parts[1]] = parts[2:]
    missing = sorted(set(want) - set(order))
    if missing:
        raise SystemExit("cells absent from %s: %s" % (lib_path, ", ".join(missing)))
    return order


def out_pin(cell, order):
    """The one output port of a cell, found rather than assumed."""
    found = [p for p in order[cell] if p in OUT_PINS]
    if len(found) != 1:
        raise SystemExit("cell %s has %d output pins in the PDK (%s); expected one"
                         % (cell, len(found), " ".join(order[cell])))
    return found[0]


def wire(cell, order, mapping):
    """Positional argument list for a subckt call, in the PDK's own pin order."""
    args = []
    for pin in order[cell]:
        if pin in PWR:
            args.append(PWR[pin])
        elif pin in mapping:
            args.append(mapping[pin])
        else:
            args.append("0")
    return " ".join(args)


def read_netlist(path):
    """Instances, plus which instance drives each net and which load it."""
    text = open(path, encoding="utf-8").read()
    pat = re.compile(r'\b(sky130_fd_sc_hd__[a-z0-9_]+|ro_macro_hard)\s+(\S+)\s*\((.*?)\);',
                     re.S)
    insts, drivers, loads = {}, {}, {}
    for m in pat.finditer(text):
        pins = dict(re.findall(r'\.(\w+)\s*\(\s*([^)]*?)\s*\)', m.group(3)))
        insts[m.group(2)] = (m.group(1), pins)
    for name, (cell, pins) in insts.items():
        for pin, net in pins.items():
            if not net:
                continue
            driving = pin in OUT_PINS or (cell == "ro_macro_hard" and pin == "out")
            if driving:
                drivers[net] = (name, cell, pin)
            elif pin not in PWR:
                loads.setdefault(net, []).append((name, cell, pin))
    return insts, drivers, loads


def parse_spef_total(path):
    """{net name: total capacitance in pF}, the lumped convention."""
    num2name, name2cap = {}, {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r'^\*(\d+)\s+(\S+)\s*$', line)
            if m:
                num2name[m.group(1)] = m.group(2).replace("\\", "")
                continue
            if line.startswith("*D_NET"):
                p = line.split()
                nm = num2name.get(p[1].lstrip("*"))
                if nm:
                    name2cap[nm] = float(p[2])
    return name2cap


def parse_spef_full(path):
    """Name map plus the whole RC network of every net.

    Same shape as gen_rc_decks.parse_spef. Kept here rather than imported
    because that module resolves its default SPEF at import time against a path
    this script does not use.
    """
    txt = open(path, encoding="utf-8", errors="replace").read()
    names = {k: v.replace("\\", "")
             for k, v in re.findall(r'^\*(\d+)\s+(\S+)\s*$', txt, re.M)}
    nets = {}
    for m in re.finditer(r'^\*D_NET \*(\d+)\s+([0-9.eE+-]+)\s*\n(.*?)^\*END',
                         txt, re.S | re.M):
        num, total, body = m.group(1), float(m.group(2)), m.group(3)
        conn = re.findall(r'^\*I \*(\d+):(\S+)\s+([IO])\s', body, re.M)
        caps, res = [], []
        cs = re.search(r'^\*CAP\n(.*?)(?=^\*RES|\Z)', body, re.S | re.M)
        rs = re.search(r'^\*RES\n(.*?)\Z', body, re.S | re.M)
        for line in (cs.group(1).splitlines() if cs else []):
            p = line.split()
            if len(p) == 3:
                caps.append((p[1], None, float(p[2])))
            elif len(p) == 4:
                caps.append((p[1], p[2], float(p[3])))
        for line in (rs.group(1).splitlines() if rs else []):
            p = line.split()
            if len(p) == 4:
                res.append((p[1], p[2], float(p[3])))
        nets[num] = dict(total=total, conn=conn, caps=caps, res=res)
    return names, nets


# ------------------------------------------------------------------ the network

def emit_net(prefix, num, net, fixed):
    """One top-level net as the extraction wrote it: resistors, caps, coupling.

    `fixed` maps the SPEF nodes that connect to something this deck instantiates
    onto the deck node they must become. Every other node of the net gets a
    private name derived from the SPEF's own label, so the topology is the
    extraction's and not mine.

    A node that carries capacitance but no resistor would float, and ngspice
    would either fail to converge or, worse, converge on nonsense, so that is
    checked here rather than left to the simulator.
    """
    conn_nodes = {"*%s:%s" % (i, p) for i, p, _ in net["conn"]}

    def on_net(spefnode):
        head, _, _ = spefnode.lstrip("*").partition(":")
        return head == num or spefnode in conn_nodes

    def name(spefnode):
        if spefnode in fixed:
            return fixed[spefnode]
        head, _, rest = spefnode.lstrip("*").partition(":")
        return "%s%s_%s" % (prefix, head, re.sub(r'[^A-Za-z0-9_]', "_", rest))

    lines, stats = [], dict(res=0, cg=0, ccoup=0, cext=0, carried=0.0, zeros=0)
    resistive = set()
    for a, b, ohm in net["res"]:
        na, nb = name(a), name(b)
        resistive.add(na)
        resistive.add(nb)
        if na == nb or ohm == 0.0:
            continue
        lines.append("R%s%d %s %s %.4f" % (prefix, stats["res"], na, nb, ohm))
        stats["res"] += 1

    orphans = set()
    for a, b, pf in net["caps"]:
        a_on, b_on = on_net(a), (on_net(b) if b else False)
        if not (a_on or b_on):
            continue
        stats["carried"] += pf
        if pf == 0.0:
            # the extraction writes these; a zero-valued capacitor is not a
            # component, and emitting it only makes the deck harder to read
            stats["zeros"] += 1
            continue
        if b is None:
            node = name(a)
            lines.append("C%sg%d %s 0 %.6e" % (prefix, stats["cg"], node, pf * 1e-12))
            stats["cg"] += 1
            if node not in resistive:
                orphans.add(node)
        elif a_on and b_on:
            # both ends move and both are simulated, so the coupling is real
            lines.append("C%sc%d %s %s %.6e"
                         % (prefix, stats["ccoup"], name(a), name(b), pf * 1e-12))
            stats["ccoup"] += 1
        else:
            # the far end belongs to another net. Only one Arm B ring runs at a
            # time, so that net is quiet and a grounded capacitor is what it is.
            node = name(a if a_on else b)
            lines.append("C%sx%d %s 0 %.6e" % (prefix, stats["cext"], node, pf * 1e-12))
            stats["cext"] += 1
            if node not in resistive:
                orphans.add(node)

    orphans -= set(fixed.values())
    if orphans:
        raise SystemExit(
            "net %s has node(s) with capacitance but no resistor: %s. That would "
            "float in the deck, so the SPEF is not being read the way this script "
            "assumes." % (num, ", ".join(sorted(orphans))))
    # Every capacitor the extraction filed under this net has to end up in the
    # deck, either between two of its nodes or from one of them to ground. If the
    # two totals disagree the parser is dropping something, which is the failure
    # mode that would quietly make every route look lighter than it is.
    #
    # The tolerance is loose because the D_NET header is printed to six
    # significant figures while the components are not, so the two never agree
    # exactly; measured across these 32 nets that rounding reaches 3.6 parts per
    # million. The smallest single capacitor on any of them is two parts per
    # thousand of its net, so a dropped component still lands far outside this.
    if abs(stats["carried"] - net["total"]) > max(1e-9, 1e-4 * net["total"]):
        raise SystemExit(
            "net %s: the deck carries %.6g pF but the SPEF declares %.6g pF"
            % (num, stats["carried"], net["total"]))
    return lines, stats


# --------------------------------------------------------------------- the deck

def emit_macro(tag, en_node, out_node, mcaps, order):
    """One complete ro_macro_hard: the loop, the tap, the two delay buffers.

    Ring is the enable NAND plus 30 inverters with feedback from n[30]; the tap
    buffer hangs off n[15]. Both delay buffers sit outside the loop. With
    mcaps None this is the bare topology, which is the control.
    """
    p = "%s_" % tag
    dly = "sky130_fd_sc_hd__clkdlybuf4s25_1"
    nand = "sky130_fd_sc_hd__nand2_1"
    inv = "sky130_fd_sc_hd__inv_1"
    buf = "sky130_fd_sc_hd__buf_1"
    L = ["X%sdlyin %s %s" % (p, wire(dly, order,
                                    {"A": en_node, out_pin(dly, order): p + "net1"}), dly),
         "X%snand %s %s" % (p, wire(nand, order,
                                    {"A": p + "net1", "B": "%sn%d" % (p, NINV),
                                     out_pin(nand, order): p + "n0"}), nand)]
    for k in range(1, NINV + 1):
        L.append("X%sinv%d %s %s"
                 % (p, k, wire(inv, order, {"A": "%sn%d" % (p, k - 1),
                                            out_pin(inv, order): "%sn%d" % (p, k)}), inv))
    L.append("X%sbuf %s %s" % (p, wire(buf, order, {"A": "%sn%d" % (p, TAP),
                                                    out_pin(buf, order): p + "net2"}), buf))
    L.append("X%sdlyout %s %s" % (p, wire(dly, order, {"A": p + "net2",
                                                       out_pin(dly, order): out_node}), dly))
    if mcaps:
        for k in range(NINV + 1):
            c = mcaps.get("u_ro.n[%d]" % k, 0.0)
            if c > 0:
                L.append("C%sn%d %sn%d 0 %.6e" % (p, k, p, k, c * 1e-12))
        for key, node in (("net1", p + "net1"), ("net2", p + "net2"),
                          ("en", en_node), ("out", out_node)):
            c = mcaps.get(key, 0.0)
            if c > 0:
                L.append("C%s%s %s 0 %.6e" % (p, key, node, c * 1e-12))
    return L


def build(corner, order, insts, drivers, loads, topnames, topnets, topcaps, mcaps):
    v = corner["supply"]
    lib, cells = sky130_spice_paths()
    q = lambda path: '"' + str(path).replace("\\", "/") + '"'
    head = ["* Arm B per-instance integration, hardware item 8",
            "* auto-generated by gen_instance_decks.py",
            "* control c_, reference r_, and the 16 real instances k00_ to k15_",
            ".lib %s %s" % (q(lib), corner["section"]),
            ".include %s" % q(cells)]
    if corner["temp"] != 27:
        head.append(".temp %g" % corner["temp"])
    head += [".param SUPPLY=%g" % v,
             "Vdd VPWR 0 {SUPPLY}",
             "Vone ONE 0 %g" % v,
             "Ven EN 0 PULSE(0 %g 2n 50p 50p 1 2)" % v,
             ""]

    body = ["* --- control: macro topology, no capacitance at all ---"]
    body += emit_macro("c", "EN", "c_out", None, order)
    body += ["", "* --- reference: macro internal extraction only, nothing external ---"]
    body += emit_macro("r", "EN", "r_out", mcaps, order)

    byname = {v2: k for k, v2 in topnames.items()}
    rows, totals = [], []
    for k in range(NRO):
        tag = "k%02d" % k
        macro_inst = "u_rob%d" % k
        en_net = insts[macro_inst][1]["en"]
        out_net = insts[macro_inst][1]["out"]
        en_key = en_net.lstrip("\\").strip()
        out_key = out_net.lstrip("\\").strip()
        for key in (en_key, out_key):
            if key not in byname:
                raise SystemExit("net %s is not in the top SPEF" % key)
        en_num, out_num = byname[en_key], byname[out_key]

        drv_name, drv_cell, drv_pin = drivers[en_net]
        if drv_cell not in ENABLE_DRIVERS:
            raise SystemExit("instance %d enable is driven by %s, which this script "
                             "has no boolean for" % (k, drv_cell))
        rcv = [(n, c, p) for n, c, p in loads.get(out_net, []) if c in CELLS]
        if len(rcv) != 1:
            raise SystemExit("instance %d output reaches %d known selector cells; "
                             "expected exactly one" % (k, len(rcv)))
        rcv_name, rcv_cell, rcv_pin = rcv[0]
        if rcv_pin not in CELLS[rcv_cell]:
            raise SystemExit("selector cell %s has no data pin %s in the side-input "
                             "table" % (rcv_cell, rcv_pin))

        n_edrv, n_epin = tag + "_edrv", tag + "_epin"
        n_omac, n_orx = tag + "_omac", tag + "_orx"
        body += ["",
                 "* --- instance %d: %s, enable from %s.%s, output into %s.%s ---"
                 % (k, macro_inst, drv_name, drv_pin, rcv_name, rcv_pin)]

        spec = ENABLE_DRIVERS[drv_cell]
        m = {spec["data"]: "EN", out_pin(drv_cell, order): n_edrv}
        for pin, val in spec["sides"].items():
            m[pin] = "ONE" if val else "0"
        body.append("X%s_drv %s %s" % (tag, wire(drv_cell, order, m), drv_cell))

        en_lines, en_stats = emit_net(
            "%s_e" % tag, en_num, topnets[en_num],
            {"*%s:%s" % (byname[drv_name], drv_pin): n_edrv,
             "*%s:en" % byname[macro_inst]: n_epin})
        body += en_lines
        body += emit_macro(tag, n_epin, n_omac, mcaps, order)
        out_lines, out_stats = emit_net(
            "%s_o" % tag, out_num, topnets[out_num],
            {"*%s:out" % byname[macro_inst]: n_omac,
             "*%s:%s" % (byname[rcv_name], rcv_pin): n_orx})
        body += out_lines

        m = {rcv_pin: n_orx, out_pin(rcv_cell, order): tag + "_rxout"}
        for pin, val in CELLS[rcv_cell][rcv_pin].items():
            m[pin] = "ONE" if val else "0"
        body.append("X%s_rcv %s %s" % (tag, wire(rcv_cell, order, m), rcv_cell))
        rx_out_net = insts[rcv_name][1][out_pin(rcv_cell, order)].lstrip("\\").strip()
        c = topcaps.get(rx_out_net)
        if c is None:
            raise SystemExit("selector output net %s has no SPEF entry" % rx_out_net)
        body.append("C%s_rxout %s_rxout 0 %.6e" % (tag, tag, c * 1e-12))

        totals.append((k, topnets[en_num]["total"] * 1000, topnets[out_num]["total"] * 1000))
        rows.append([k, macro_inst,
                     "%s.%s" % (drv_name, drv_pin), drv_cell.replace("sky130_fd_sc_hd__", ""),
                     "%.3f" % (topnets[en_num]["total"] * 1000), en_stats["res"],
                     en_stats["cg"] + en_stats["cext"], en_stats["ccoup"],
                     "%s.%s" % (rcv_name, rcv_pin), rcv_cell.replace("sky130_fd_sc_hd__", ""),
                     "%.3f" % (topnets[out_num]["total"] * 1000), out_stats["res"],
                     out_stats["cg"] + out_stats["cext"], out_stats["ccoup"]])

    th, lo, hi = v / 2.0, 0.2 * v, 0.8 * v
    first, last = corner["first_edge"], corner["last_edge"]
    span = last - first

    probes = ["c_out", "r_out"] + ["k%02d_%s" % (k, s) for k in range(NRO)
                                   for s in ("omac", "orx")]
    tail = ["", ".save " + " ".join("v(%s)" % p for p in probes),
            ".tran %dp %gn" % (corner["step_ps"], corner["tstop_ns"]),
            ".control", "run"]

    def meas(name, node, val_a, edge_a, node_b, val_b, edge_b):
        return ("meas tran %s TRIG v(%s) VAL=%g %s TARG v(%s) VAL=%g %s"
                % (name, node, val_a, edge_a, node_b, val_b, edge_b))

    mid = (first + last) // 2
    for name, node in (("c", "c_out"), ("r", "r_out")):
        tail.append(meas("tp_%s" % name, node, th, "RISE=%d" % first, node, th,
                         "RISE=%d" % last))
        tail.append(meas("hi_%s" % name, node, th, "RISE=%d" % mid, node, th,
                         "FALL=%d" % mid))
    for k in range(NRO):
        t = "k%02d" % k
        a, b = t + "_omac", t + "_orx"
        tail.append(meas("tp_%s" % t, a, th, "RISE=%d" % first, a, th, "RISE=%d" % last))
        tail.append(meas("tq_%s" % t, b, th, "RISE=%d" % first, b, th, "RISE=%d" % last))
        tail.append(meas("hi_%s" % t, a, th, "RISE=%d" % mid, a, th, "FALL=%d" % mid))
        tail.append(meas("hx_%s" % t, b, th, "RISE=%d" % mid, b, th, "FALL=%d" % mid))
        tail.append(meas("dr_%s" % t, a, th, "RISE=%d" % mid, b, th, "RISE=%d" % mid))
        tail.append(meas("df_%s" % t, a, th, "FALL=%d" % mid, b, th, "FALL=%d" % mid))
        tail.append(meas("sm_%s" % t, a, lo, "RISE=%d" % mid, a, hi, "RISE=%d" % mid))
        tail.append(meas("sr_%s" % t, b, lo, "RISE=%d" % mid, b, hi, "RISE=%d" % mid))
    for name in ["c", "r"] + ["k%02d" % k for k in range(NRO)]:
        tail.append("let f_%s = %d / tp_%s" % (name, span, name))
    for name in ["c", "r"] + ["k%02d" % k for k in range(NRO)]:
        tail.append("print f_%s" % name)
    tail += ["quit", ".endc", ".end"]

    csv_buf = io.StringIO(newline="")
    w = csv.writer(csv_buf, lineterminator="\n")
    w.writerow(["instance", "macro", "en_driver", "en_cell", "en_cap_fF", "en_res",
                "en_caps_grounded", "en_caps_coupled", "out_receiver", "out_cell",
                "out_cap_fF", "out_res", "out_caps_grounded", "out_caps_coupled"])
    w.writerows(rows)
    return "\n".join(head + body + tail) + "\n", csv_buf.getvalue(), totals


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output-dir", default="/tmp/inst")
    ap.add_argument("--corner", default="tt", choices=sorted(CORNERS))
    ap.add_argument("--netlist", default=NETLIST)
    ap.add_argument("--top-spef", default=TOP_SPEF)
    ap.add_argument("--macro-spef", default=MACRO_SPEF)
    ap.add_argument("--lib", default=None,
                    help="sky130_fd_sc_hd.spice; default comes from PDK_ROOT")
    ap.add_argument("--step-ps", type=int, default=1,
                    help="transient timestep, ps (default 1; the route delays "
                         "being measured are single-digit ps)")
    ap.add_argument("--smoke", action="store_true",
                    help="short run that proves the deck elaborates and every ring "
                         "starts, before spending an hour on the real one")
    args = ap.parse_args(argv)

    corner = dict(CORNERS[args.corner])
    corner["step_ps"] = args.step_ps
    if args.smoke:
        corner["tstop_ns"] = 20 if args.corner != "ss" else 60
        corner["first_edge"], corner["last_edge"] = 2, 7
    else:
        corner["first_edge"], corner["last_edge"] = 5, 25

    lib = args.lib if args.lib else str(sky130_spice_paths()[1])
    insts, drivers, loads = read_netlist(args.netlist)
    topnames, topnets = parse_spef_full(args.top_spef)
    topcaps = parse_spef_total(args.top_spef)
    mcaps = parse_spef_total(args.macro_spef)

    missing = [k for k in range(NINV + 1) if "u_ro.n[%d]" % k not in mcaps]
    if missing:
        raise SystemExit("the macro SPEF is missing ring nets %s" % missing[:5])

    want = set(MACRO_CELLS)
    for k in range(NRO):
        en_net = insts["u_rob%d" % k][1]["en"]
        out_net = insts["u_rob%d" % k][1]["out"]
        want.add(drivers[en_net][1])
        want |= {c for _, c, _ in loads.get(out_net, []) if c in CELLS}
    order = read_pin_order(lib, want)

    text, table, totals = build(corner, order, insts, drivers, loads,
                                topnames, topnets, topcaps, mcaps)
    os.makedirs(args.output_dir, exist_ok=True)
    sfx = "" if args.corner == "tt" else "_%s" % args.corner
    if args.smoke:
        sfx += "_smoke"
    deck = os.path.join(args.output_dir, "armb_instances%s.spice" % sfx)
    atomic_write_text(deck, text)
    atomic_write_text(os.path.join(args.output_dir, "instance_parasitics.csv"), table)

    ring = sum(mcaps.get("u_ro.n[%d]" % k, 0.0) for k in range(NINV + 1)) * 1000
    en = [e for _, e, _ in totals]
    ou = [o for _, _, o in totals]
    print("corner %s: %g C, %g V, %d ps step, %g ns"
          % (args.corner, corner["temp"], corner["supply"], corner["step_ps"],
             corner["tstop_ns"]))
    print("pin order for %d cells read from %s" % (len(order), lib))
    print("macro ring capacitance, identical in all 18 rings: %.2f fF" % ring)
    print("enable route capacitance: %.2f to %.2f fF, mean %.2f"
          % (min(en), max(en), sum(en) / len(en)))
    print("output route capacitance: %.2f to %.2f fF, mean %.2f"
          % (min(ou), max(ou), sum(ou) / len(ou)))
    print("rings in the deck: 1 control, 1 reference, %d instances" % NRO)
    print("deck: %s" % deck)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
