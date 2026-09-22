#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Static-0 hazard search in the counter clock mux of a gate-level netlist.

The ripple counter is clocked by sel_ro, the output of the 64:1 mux that
synthesis built from `ro_out[active_sel]`. With every ring output held at
0 (the idle case, and the case at every start from idle) sel_ro must be 0
whatever the selector says, and it is. But the mux is a multi-level
network, and while the six selector flops change together a cell inside
it can see the old value of one input and the new value of another. A
cell whose output is 0 for every selector value but which has two or more
inputs that are each 1 for some selector values is a static-0 hazard
site: on a transition between selector values where the old value of one
input and the new value of another are both 1, the output can pulse. The
counter's reset is released on the edge that switches the selector, so a
pulse there is a count.

This reads the netlist, evaluates every net in the cone of sel_ro as a
64-entry table over the selector with rings at 0, using the sky130 cell
functions, and reports the hazard sites and the selector transitions that
expose each. Found on 22 September 2026 by a gate-level run that counted
one extra on slot 41; test/stress/stress.py pins the behaviour.

  python3 sim/mux_hazard.py --netlist dualarm/build_armc/<top>.nl.v
  python3 sim/mux_hazard.py --netlist ... --expect-sites 1   (exit 1 if not)
  python3 sim/mux_hazard.py --selftest
"""
import argparse
import re
import sys
from itertools import product

INST_RE = re.compile(
    r"^\s*(sky130_fd_sc_hd__\w+|ro_macro_hard)\s+(\S+)\s*\((.*?)\);",
    re.S | re.M)
PIN_RE = re.compile(r"\.(\w+)\(\s*([^()]*?)\s*\)")
OUT_PINS = {"Q", "Y", "X", "HI", "LO", "out"}
ROOT = "\\u_puf.u_core.sel_ro"
SEL = ["\\u_puf.u_core.active_sel[%d]" % i for i in range(6)]

FUNCS = {
    "inv": lambda A: not A,
    "buf": lambda A: A,
    "clkbuf": lambda A: A,
    "clkdlybuf4s25": lambda A: A,
    "dlygate4sd3": lambda A: A,
    "and2": lambda A, B: A and B,
    "and2b": lambda A_N, B: (not A_N) and B,
    "and3": lambda A, B, C: A and B and C,
    "and3b": lambda A_N, B, C: (not A_N) and B and C,
    "and4": lambda A, B, C, D: A and B and C and D,
    "and4b": lambda A_N, B, C, D: (not A_N) and B and C and D,
    "or2": lambda A, B: A or B,
    "or3": lambda A, B, C: A or B or C,
    "or3b": lambda A, B, C_N: A or B or (not C_N),
    "or4": lambda A, B, C, D: A or B or C or D,
    "or4b": lambda A, B, C, D_N: A or B or C or (not D_N),
    "nand2": lambda A, B: not (A and B),
    "nand2b": lambda A_N, B: not ((not A_N) and B),
    "nand3": lambda A, B, C: not (A and B and C),
    "nand4": lambda A, B, C, D: not (A and B and C and D),
    "nor2": lambda A, B: not (A or B),
    "nor3": lambda A, B, C: not (A or B or C),
    "xor2": lambda A, B: A != B,
    "xnor2": lambda A, B: A == B,
    "mux2": lambda A0, A1, S: A1 if S else A0,
    "a21o": lambda A1, A2, B1: (A1 and A2) or B1,
    "a21oi": lambda A1, A2, B1: not ((A1 and A2) or B1),
    "a21bo": lambda A1, A2, B1_N: (A1 and A2) or (not B1_N),
    "a22o": lambda A1, A2, B1, B2: (A1 and A2) or (B1 and B2),
    "a31o": lambda A1, A2, A3, B1: (A1 and A2 and A3) or B1,
    "a32o": lambda A1, A2, A3, B1, B2: (A1 and A2 and A3) or (B1 and B2),
    "a211o": lambda A1, A2, B1, C1: (A1 and A2) or B1 or C1,
    "a211oi": lambda A1, A2, B1, C1: not ((A1 and A2) or B1 or C1),
    "a221o": lambda A1, A2, B1, B2, C1: (A1 and A2) or (B1 and B2) or C1,
    "a2111o": lambda A1, A2, B1, C1, D1: (A1 and A2) or B1 or C1 or D1,
    "o21a": lambda A1, A2, B1: (A1 or A2) and B1,
    "o21ai": lambda A1, A2, B1: not ((A1 or A2) and B1),
    "o21ba": lambda A1, A2, B1_N: (A1 or A2) and (not B1_N),
    "o22a": lambda A1, A2, B1, B2: (A1 or A2) and (B1 or B2),
    "o31ai": lambda A1, A2, A3, B1: not ((A1 or A2 or A3) and B1),
    "o211a": lambda A1, A2, B1, C1: (A1 or A2) and B1 and C1,
    "o221a": lambda A1, A2, B1, B2, C1: (A1 or A2) and (B1 or B2) and C1,
    "o2111a": lambda A1, A2, B1, C1, D1: (A1 or A2) and B1 and C1 and D1,
    "o2111ai": lambda A1, A2, B1, C1, D1:
        not ((A1 or A2) and B1 and C1 and D1),
    "o2bb2a": lambda A1_N, A2_N, B1, B2: (not (A1_N and A2_N)) and (B1 or B2),
}


def cell_function(master):
    base = master.replace("sky130_fd_sc_hd__", "").rsplit("_", 1)[0]
    return FUNCS[base]


def is_ring_out(net):
    return (net.endswith(".u_ro.out") or net.endswith(".u_roc.out")
            or net.startswith("\\armb_out"))


def parse(text):
    """{net: (master, name, pins)} for every driven net."""
    drivers = {}
    for m in INST_RE.finditer(text):
        master, name = m.group(1), m.group(2)
        pins = {p: n.strip() for p, n in PIN_RE.findall(m.group(3))}
        for k, v in pins.items():
            if k in OUT_PINS:
                drivers[v] = (master, name, pins)
    return drivers


class Cone:
    def __init__(self, drivers, root=ROOT, sel=SEL):
        self.drivers = drivers
        self.sel = sel
        self.tables = {}
        self.root = root
        self.table(root)

    def table(self, net):
        """Value of net for each of the 64 selector values, rings at 0."""
        if net in self.tables:
            return self.tables[net]
        if net in self.sel:
            i = self.sel.index(net)
            t = tuple(bool((s >> i) & 1) for s in range(64))
        elif is_ring_out(net):
            t = (False,) * 64
        elif net not in self.drivers:
            raise KeyError("undriven net in the mux cone: " + net)
        else:
            master, name, pins = self.drivers[net]
            if "dfrtp" in master or "dfxtp" in master:
                raise KeyError("a flop other than active_sel feeds the mux: "
                               + name)
            f = cell_function(master)
            ins = {k: v for k, v in pins.items() if k not in OUT_PINS}
            tabs = {k: self.table(v) for k, v in ins.items()}
            t = tuple(bool(f(**{k: tabs[k][s] for k in ins}))
                      for s in range(64))
        self.tables[net] = t
        return t

    def sites(self):
        """Hazard sites: (name, master, inputs, exposed transitions)."""
        found = []
        seen = set()

        def walk(net):
            if net in seen or net in self.sel or is_ring_out(net):
                return
            seen.add(net)
            master, name, pins = self.drivers[net]
            ins = {k: v for k, v in pins.items() if k not in OUT_PINS}
            if not any(self.tables[net]):
                varying = [k for k in ins if any(self.tables[ins[k]])
                           and not all(self.tables[ins[k]])]
                if len(varying) >= 2:
                    found.append((name, master, ins,
                                  self.exposed(master, ins)))
            for v in ins.values():
                walk(v)

        walk(self.root)
        return [s for s in found if s[3]], len(seen)

    def exposed(self, master, ins):
        """Transitions a -> b on which some mix of old and new input
        values makes the cell's output 1."""
        f = cell_function(master)
        keys = list(ins)
        tabs = [self.tables[ins[k]] for k in keys]
        haz = []
        for a in range(64):
            old = [t[a] for t in tabs]
            for b in range(64):
                if a == b:
                    continue
                new = [t[b] for t in tabs]
                for mask in product((0, 1), repeat=len(keys)):
                    mix = {k: (new[i] if bit else old[i])
                           for i, (k, bit) in enumerate(zip(keys, mask))}
                    if f(**mix):
                        haz.append((a, b))
                        break
        return haz


def report(cone, sites, cone_size):
    print("sel_ro with every ring at 0 is 0 for all 64 selectors:",
          not any(cone.tables[cone.root]))
    print("nets in the cone of sel_ro: %d" % cone_size)
    print("static-0 hazard sites exposed on some transition: %d" % len(sites))
    for name, master, ins, haz in sites:
        print("  cell %s %s" % (name, master.replace("sky130_fd_sc_hd__", "")))
        for k, v in ins.items():
            ones = [s for s in range(64) if cone.tables[v][s]]
            print("    %s = %s, 1 for %d selector values%s" % (
                k, v, len(ones), ": %s" % ones if len(ones) <= 16 else ""))
        dests = sorted(set(b for _, b in haz))
        srcs = sorted(set(a for a, _ in haz))
        print("    exposed on %d of 4032 transitions, %d destinations, "
              "%d sources" % (len(haz), len(dests), len(srcs)))


FIXTURE = """
module top (a, b);
 wire \\u_puf.u_core.active_sel[0] ;
 wire \\u_puf.u_core.active_sel[1] ;
 wire \\u_puf.u_core.active_sel[2] ;
 wire \\u_puf.u_core.active_sel[3] ;
 wire \\u_puf.u_core.active_sel[4] ;
 wire \\u_puf.u_core.active_sel[5] ;
 sky130_fd_sc_hd__inv_2 i0 (.A(\\u_puf.u_core.active_sel[0] ), .Y(nsel0));
 sky130_fd_sc_hd__and2_2 g1 (.A(\\u_puf.u_core.active_sel[0] ), .B(nsel0),
    .X(haz));
 sky130_fd_sc_hd__and2_2 g2 (.A(\\u_puf.u_core.active_sel[1] ),
    .B(\\u_puf.u_core.g_ro_bank[0].u_ro.out ), .X(leaf));
 sky130_fd_sc_hd__or2_2 g3 (.A(haz), .B(leaf), .X(\\u_puf.u_core.sel_ro ));
endmodule
"""


def selftest():
    """A four-cell mux with one planted hazard, sel0 AND NOT sel0, and one
    clean leaf, sel1 AND ring. Exactly the planted cell must be reported,
    exposed on every transition that flips sel0; then the planted cell is
    replaced by a clean one and nothing may be reported."""
    cone = Cone(parse(FIXTURE))
    sites, _ = cone.sites()
    names = [s[0] for s in sites]
    if names != ["g1"]:
        print("selftest: expected only g1, got %s" % names)
        return 1
    haz = sites[0][3]
    flips = [(a, b) for a in range(64) for b in range(64)
             if a != b and (a ^ b) & 1]
    if sorted(haz) != sorted(flips):
        print("selftest: g1 exposed on %d transitions, expected %d"
              % (len(haz), len(flips)))
        return 1
    clean = FIXTURE.replace(
        ".B(nsel0),", ".B(\\u_puf.u_core.g_ro_bank[1].u_ro.out ),")
    if clean == FIXTURE:
        print("selftest: the clean fixture did not change anything")
        return 1
    sites2, _ = Cone(parse(clean)).sites()
    if sites2:
        print("selftest: the clean fixture reported %s"
              % [s[0] for s in sites2])
        return 1
    print("selftest: planted hazard found on g1 and only g1, %d transitions; "
          "clean fixture reports none" % len(haz))
    return 0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--netlist")
    ap.add_argument("--expect-sites", type=int)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.netlist:
        ap.error("--netlist or --selftest")
    cone = Cone(parse(open(a.netlist).read()))
    sites, cone_size = cone.sites()
    report(cone, sites, cone_size)
    if a.expect_sites is not None and len(sites) != a.expect_sites:
        print("FAIL: %d hazard sites, expected %d"
              % (len(sites), a.expect_sites))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
