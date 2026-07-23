#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Prove every Arm A ring in the final netlist is the intended topology.

The go/no-go generator reconstructs each Arm A oscillator as one enable NAND,
30 inverters, and a tap buffer, and reads the ring-net capacitances from the
SPEF. That is only valid if the placed-and-routed netlist actually still has
that ring, with no timing-repair buffer inserted into the feedback loop. This
script parses the final gate-level netlist and asserts, for every Arm A bank,
exactly:

    1 x sky130_fd_sc_hd__nand2_1   (u_nand, the enable stage)
    30 x sky130_fd_sc_hd__inv_1    (g_inv[1..30].u_inv, the delay chain)
    1 x sky130_fd_sc_hd__buf_1     (u_buf, the isolating tap)

and nothing else under u_ro. Any extra, missing, or retyped cell fails the run,
which is what would happen if the flow buffered a ring net. Arm B is a sealed
hardened macro and is checked by the physical flow, not here.

Usage:
    python3 verify_ring_topology.py [--netlist PATH] [--n-ro N]
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_NL = os.path.join(
    PROJ, "dualarm", "build_current", "tt_um_nikodemetrashvili20_ro_puf.nl.v")

CELL_RE = re.compile(r"^\s*sky130_fd_sc_hd__(\S+)\s+\\(\S+)\s")
BANK_RE = re.compile(r"^u_puf\.u_core\.g_ro_bank\[(\d+)\]\.u_ro\.(.+)$")


def expected_leaves():
    leaves = {"u_nand": "nand2_1", "u_buf": "buf_1"}
    for k in range(1, 31):
        leaves["g_inv[%d].u_inv" % k] = "inv_1"
    return leaves


def parse_banks(netlist_path):
    banks = {}
    with open(netlist_path, encoding="utf-8") as fh:
        for line in fh:
            m = CELL_RE.match(line)
            if not m:
                continue
            cell_type, inst = m.group(1), m.group(2)
            b = BANK_RE.match(inst)
            if not b:
                continue
            banks.setdefault(int(b.group(1)), {})[b.group(2)] = cell_type
    return banks


def check_bank(leaves, want):
    problems = []
    for leaf, cell in want.items():
        if leaf not in leaves:
            problems.append("missing %s (%s)" % (leaf, cell))
        elif leaves[leaf] != cell:
            problems.append("%s is %s, expected %s" % (leaf, leaves[leaf], cell))
    for leaf, cell in leaves.items():
        if leaf not in want:
            problems.append("unexpected cell in ring: %s (%s)" % (leaf, cell))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--netlist", default=DEFAULT_NL)
    ap.add_argument("--n-ro", type=int, default=16)
    args = ap.parse_args(argv)

    if not os.path.exists(args.netlist):
        print("error: netlist not found: %s\n"
              "copy the final netlist from the flow run "
              "(runs/<tag>/final/nl/*.nl.v) into dualarm/build_current/, or pass "
              "--netlist" % args.netlist, file=sys.stderr)
        return 2

    banks = parse_banks(args.netlist)
    want = expected_leaves()
    failed = 0
    for i in range(args.n_ro):
        if i not in banks:
            print("[FAIL] Arm A bank %d: not found in netlist" % i)
            failed += 1
            continue
        problems = check_bank(banks[i], want)
        if problems:
            failed += 1
            print("[FAIL] Arm A bank %d: %s" % (i, "; ".join(problems)))
        else:
            print("[ok]   Arm A bank %d: 1 nand + 30 inv + 1 buf, nothing inserted"
                  % i)

    print("== SUMMARY == %d/%d Arm A rings structurally intact"
          % (args.n_ro - failed, args.n_ro))
    if failed:
        print("A failing ring means the flow changed the oscillator (for example "
              "buffered a ring net); the lumped-C go/no-go assumption no longer "
              "holds for that oscillator.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
