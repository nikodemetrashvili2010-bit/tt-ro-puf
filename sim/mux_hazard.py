#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Static hazards in the counter clock mux of a gate-level netlist.

The ripple counter is clocked by sel_ro, the output of the 64:1 mux that
synthesis built from `ro_out[active_sel]`. With every ring stopped, every
ring output is 0 and sel_ro must be 0 whatever the selector says, and it
is. But the counter's reset is released on the same clock edge that
switches the six selector flops, and while they change the mux can pulse.
A pulse after the reset is released is a count.

The method is ternary simulation (Eichelberger 1965). For a transition
from selector a to selector b, every selector bit that changes is X, every
ring output is 0, and every cell in the cone of sel_ro is evaluated in
three-valued logic: a cell whose output is the same for every way its X
inputs could resolve takes that value, otherwise it is X. If sel_ro comes
out X although it is 0 at both ends, some assignment of gate and wire
delays can pulse it on that transition. That is a statement about what the
structure allows, not about what the silicon does. Which of these
transitions really pulse depends on delays, and that takes a timed run
against the extracted layout.

An origin is a cell whose output is X, is the same at both ends, and has
no input that is itself such a static X: the place the pulse starts.

Found on 22 September 2026 by a gate-level run that counted one extra on
slot 41. The first version of this script checked each cell on its own
and reported one origin and 832 transitions; the ternary run on the 23rd
found twelve origins and 1728 transitions. `docs/phaseG_hazard.md`.

  python3 sim/mux_hazard.py --netlist dualarm/build_armc/<top>.nl.v
  python3 sim/mux_hazard.py --netlist ... --expect 1728   (exit 1 if not)
  python3 sim/mux_hazard.py --selftest
"""
import argparse
import itertools
import re
import sys

INST_RE = re.compile(
    r"^\s*(sky130_fd_sc_hd__\w+|ro_macro_hard)\s+(\S+)\s*\((.*?)\);",
    re.S | re.M)
PIN_RE = re.compile(r"\.(\w+)\(\s*([^()]*?)\s*\)")
OUT_PINS = {"Q", "Y", "X", "HI", "LO", "out"}
ROOT = "\\u_puf.u_core.sel_ro"
SEL = ["\\u_puf.u_core.active_sel[%d]" % i for i in range(6)]
X = 2

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
    "mux4": lambda A0, A1, A2, A3, S0, S1: (A0, A1, A2, A3)[S0 + 2 * S1],
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


def tie_value(net, drivers):
    """1 or 0 for a net driven by a tie cell, None otherwise."""
    d = drivers.get(net)
    if d is None or "conb" not in d[0]:
        return None
    return 1 if d[2].get("HI") == net else 0


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
        self.root = root
        self.tables = {}
        self.table(root)

    def inputs(self, net):
        master, name, pins = self.drivers[net]
        return {k: v for k, v in pins.items() if k not in OUT_PINS}

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
        elif tie_value(net, self.drivers) is not None:
            t = (bool(tie_value(net, self.drivers)),) * 64
        else:
            master, name, pins = self.drivers[net]
            if "dfrtp" in master or "dfxtp" in master:
                raise KeyError("a flop other than active_sel feeds the mux: "
                               + name)
            f = cell_function(master)
            ins = self.inputs(net)
            tabs = {k: self.table(v) for k, v in ins.items()}
            t = tuple(bool(f(**{k: tabs[k][s] for k in ins}))
                      for s in range(64))
        self.tables[net] = t
        return t

    def ternary(self, a, b):
        """Three-valued value of every net in the cone for a -> b."""
        memo = {}

        def val(net):
            if net in memo:
                return memo[net]
            if net in self.sel:
                i = self.sel.index(net)
                va, vb = (a >> i) & 1, (b >> i) & 1
                v = va if va == vb else X
            elif is_ring_out(net):
                v = 0
            elif tie_value(net, self.drivers) is not None:
                v = tie_value(net, self.drivers)
            else:
                f = cell_function(self.drivers[net][0])
                ins = self.inputs(net)
                vals = {k: val(n) for k, n in ins.items()}
                xs = [k for k, v in vals.items() if v == X]
                seen = set()
                for combo in itertools.product((0, 1), repeat=len(xs)):
                    d = dict(vals)
                    d.update(zip(xs, combo))
                    seen.add(bool(f(**d)))
                v = int(seen.pop()) if len(seen) == 1 else X
            memo[net] = v
            return v

        val(self.root)
        return memo

    def static_x(self, net, memo, a, b):
        return (memo.get(net) == X and net not in self.sel
                and not is_ring_out(net)
                and self.tables[net][a] == self.tables[net][b])

    def hazards(self):
        """Transitions on which sel_ro can pulse, and the origin cells."""
        found = []
        origins = {}
        for a in range(64):
            for b in range(64):
                if a == b:
                    continue
                memo = self.ternary(a, b)
                if memo[self.root] != X:
                    continue
                found.append((a, b))
                for net in memo:
                    if not self.static_x(net, memo, a, b):
                        continue
                    ins = self.inputs(net).values()
                    if any(self.static_x(n, memo, a, b) for n in ins
                           if n in memo):
                        continue
                    name = self.drivers[net][1]
                    origins[name] = origins.get(name, 0) + 1
        return found, origins


def report(cone, found, origins):
    print("sel_ro with every ring at 0 is 0 for all 64 selectors:",
          not any(cone.tables[cone.root]))
    print("nets in the cone of sel_ro: %d" % len(cone.tables))
    print("transitions on which sel_ro can pulse: %d of 4032" % len(found))
    print("origin cells: %d" % len(origins))
    for name in sorted(origins, key=lambda n: -origins[n]):
        net = next(k for k, v in cone.drivers.items() if v[1] == name)
        master = cone.drivers[net][0].replace("sky130_fd_sc_hd__", "")
        print("  %-8s %-10s starts %d" % (name, master, origins[name]))
    dests = sorted(set(b for _, b in found))
    print("destinations reached: %d of 64" % len(dests))


def fixture(extra=""):
    sel = "".join(" wire \\u_puf.u_core.active_sel[%d] ;\n" % i
                  for i in range(6))
    return ("module top (a, b);\n" + sel +
            " sky130_fd_sc_hd__and2_2 g1 (.A(\\u_puf.u_core.active_sel[0] ),"
            "\n    .B(\\u_puf.u_core.active_sel[1] ), .X(p01));\n"
            " sky130_fd_sc_hd__a21o_2 g2 (.A1(p01), .A2(p2n), .B1(leaf),"
            "\n    .X(\\u_puf.u_core.sel_ro ));\n"
            " sky130_fd_sc_hd__and2_2 g3 (.A(\\u_puf.u_core.active_sel[3] ),"
            "\n    .B(\\u_puf.u_core.g_ro_bank[0].u_ro.out ), .X(leaf));\n"
            + extra + "endmodule\n")


def selftest():
    """Plant a two-level function hazard and require exactly its
    transitions; then take it away and require none.

    g1 ANDs selector bits 0 and 1 and g2 passes that to sel_ro while
    bit 2 is 0 (p2n is NOT bit 2), so with the ring at 0 sel_ro is
    s0 AND s1 AND NOT s2. Only transitions whose two ends are both 0
    are asked about, where any pulse is a hazard. The expected set is
    written in closed form rather than by resolving X: an AND of known
    and unknown inputs is X exactly when no input is known 0, so the
    pulse is possible unless s2 is 1 at both ends, or s0 is 0 at both
    ends, or s1 is 0 at both ends.

    The first version of this script only examined cells whose output
    is 0 for every selector value, and g1 and g2 are each 1 somewhere,
    so it could not have seen this. The clean twin ties g2's A2 low,
    which makes sel_ro constant 0, and ternary simulation must report
    nothing on it.
    """
    inv2 = (" sky130_fd_sc_hd__inv_2 g4 (.A(\\u_puf.u_core.active_sel[2] ),"
            " .Y(p2n));\n")
    cone = Cone(parse(fixture(inv2)))
    const0 = not any(cone.tables[ROOT])
    if const0:
        print("selftest: the planted fixture is constant 0, not a test")
        return 1
    # Ask only about transitions whose two ends are both 0, where a
    # pulse is a hazard and not a legitimate change.
    zero = [s for s in range(64) if not cone.tables[ROOT][s]]
    got = set()
    for a in zero:
        for b in zero:
            if a != b and cone.ternary(a, b)[ROOT] == X:
                got.add((a, b))

    def both(bit, v, a, b):
        return (a >> bit) & 1 == v and (b >> bit) & 1 == v

    def expect(a, b):
        return not (both(2, 1, a, b) or both(0, 0, a, b)
                    or both(1, 0, a, b))
    want = set((a, b) for a in zero for b in zero if a != b and expect(a, b))
    if not want:
        print("selftest: the expectation is empty, not a test")
        return 1
    if got != want:
        print("selftest: planted hazard, %d transitions found, %d expected"
              % (len(got), len(want)))
        return 1
    clean = Cone(parse(fixture(
        " sky130_fd_sc_hd__conb_1 g4 (.LO(p2n));\n")))
    if any(clean.tables[ROOT]):
        print("selftest: the clean fixture is not constant 0")
        return 1
    found, origins = clean.hazards()
    if found:
        print("selftest: the clean fixture reported %d transitions"
              % len(found))
        return 1
    print("selftest: planted two-level hazard found on exactly its %d "
          "transitions; clean twin reports none" % len(want))
    return 0



def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--netlist")
    ap.add_argument("--expect", type=int,
                    help="exit 1 unless this many transitions can pulse")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.netlist:
        ap.error("--netlist or --selftest")
    cone = Cone(parse(open(a.netlist).read()))
    found, origins = cone.hazards()
    report(cone, found, origins)
    if a.expect is not None and len(found) != a.expect:
        print("FAIL: %d transitions, expected %d" % (len(found), a.expect))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
