#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Per-ring loop capacitance from a flat magic extraction.

A ring's loop is its 31 nets, each named by magic after one of the ring's
own cell pins (A, B or Y of the NAND and inverters, A of the tap buffer).
A net's load is every capacitor that touches it, to the rails, to other
nets and to fill, the way a SPEF total counts it; a ring's load is the sum
over its 31 nets.

Fill squares come out as unlabelled top-level nodes (m1_X_Y# and the
like). The base layout has none, which the count of fill nodes shows.
Two readings of fill:
  grounded  every capacitor to fill counts in full (the most fill can add)
  floating  a fill square couples Crf to the ring net and Cf in all, and
            adds Crf * (Cf - Crf) / Cf, the series path through it with
            everything else on it held still

Usage: python3 ring_loads.py NAME.spice OUT.csv
"""
import csv
import re
import sys
from collections import defaultdict

RING = [
    ("A", re.compile(r"^u_puf\.u_core\.g_ro_bank\\\[(\d+)\\\]\.u_ro\.(.+)/"
                     r"([ABY])$")),
    ("C", re.compile(r"^u_puf\.u_core\.g_armc\\\[(\d+)\\\]\.u_roc\.(.+)/"
                     r"([ABY])$")),
    ("B", re.compile(r"^u_rob(\d+)/u_ro\.(.+)/([ABY])$")),
]
# magic names an unlabelled node after its layer and lower left corner,
# a_ (poly), li_ or m1_ to m5_, with n for a minus sign: a_120_n46#
FILL = re.compile(r"^(a|li|m\d)_n?\d+_n?\d+#$")
SI = {"f": 1.0, "p": 1e3, "a": 1e-3, "n": 1e6, "u": 1e9}


def value_ff(tok):
    tok = tok.strip()
    if tok[-1] in SI:
        return float(tok[:-1]) * SI[tok[-1]]
    return float(tok) * 1e15


def ring_of(node):
    for arm, rx in RING:
        m = rx.match(node)
        if m:
            cell, pin = m.group(2), m.group(3)
            if cell == "u_nand" and pin == "A":
                return None  # the enable, not the loop
            return "%s%02d" % (arm, int(m.group(1)))
    return None


def read(path):
    caps = []
    with open(path) as f:
        for line in f:
            if not line.startswith("C"):
                continue
            t = line.split()
            caps.append((t[1], t[2], value_ff(t[3])))
    return caps


def loads(path):
    caps = read(path)
    node_total = defaultdict(float)
    for a, b, v in caps:
        node_total[a] += v
        node_total[b] += v
    ring_nodes = defaultdict(set)
    for n in node_total:
        r = ring_of(n)
        if r:
            ring_nodes[r].add(n)
    fill_nodes = {n for n in node_total if FILL.match(n)}
    grounded = defaultdict(float)
    floating = defaultdict(float)
    to_fill = defaultdict(float)
    for a, b, v in caps:
        for x, y in ((a, b), (b, a)):
            r = ring_of(x)
            if not r:
                continue
            grounded[r] += v
            if y in fill_nodes:
                cf = node_total[y]
                floating[r] += v * (cf - v) / cf if cf > 0 else 0.0
                to_fill[r] += v
            else:
                floating[r] += v
    return ring_nodes, fill_nodes, grounded, floating, to_fill


def main(spice, outcsv):
    ring_nodes, fill_nodes, grounded, floating, to_fill = loads(spice)
    rings = sorted(ring_nodes)
    bad = {r: len(ring_nodes[r]) for r in rings if len(ring_nodes[r]) != 31}
    print("rings", len(rings), "fill nodes", len(fill_nodes),
          "rings without 31 loop nets:", bad or "none")
    with open(outcsv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ring", "loop_nets", "grounded_fF", "floating_fF",
                    "to_fill_fF"])
        for r in rings:
            w.writerow([r, len(ring_nodes[r]), "%.4f" % grounded[r],
                        "%.4f" % floating[r], "%.4f" % to_fill[r]])
    return 0 if not bad and len(rings) == 48 else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
