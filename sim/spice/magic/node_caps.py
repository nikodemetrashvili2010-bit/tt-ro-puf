#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Per-node loads of every ring, from a flat magic extraction, by stage.

Stage k is the deck node nk of sim/spice/gono/gen_rc_decks.py's lumped
decks: n0 the NAND's output, nk inverter k's output, n30 the last
inverter's output back into the NAND, and the tap buffer on n15. magic
names each loop net after one of its pins, so the name gives the stage:
u_nand/Y 0, u_nand/B 30, u_buf/A 15, g_inv[k]/A k-1, g_inv[k]/Y k, with
k counted from 1 (Arm C's own indices start at 0 and are shifted).

Loads are as in ring_loads.py: every capacitor on the net, fill counted
grounded and floating. Writes JSON {ring: {"grounded": [31], "floating":
[31]}} in fF.

Usage: python3 node_caps.py NAME.spice OUT.json
"""
import json
import re
import sys
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from ring_loads import read, ring_of, FILL  # noqa: E402

INV = re.compile(r"g_inv\\\[(\d+)\\\]\.u_inv/([AY])$")


def stage(node):
    if node.endswith("u_nand/Y"):
        return 0
    if node.endswith("u_nand/B"):
        return 30
    if node.endswith("u_buf/A"):
        return 15
    m = INV.search(node)
    if m:
        # Arm A and the macro number their inverters 1 to 30, Arm C 0 to
        # 29 (ro_armc.v); in both, n[k] is the k-th stage's output
        k = int(m.group(1)) + (1 if ".u_roc." in node else 0)
        return k - 1 if m.group(2) == "A" else k
    raise ValueError(node)


def main(spice, out):
    caps = read(spice)
    total = defaultdict(float)
    for a, b, v in caps:
        total[a] += v
        total[b] += v
    fill = {n for n in total if FILL.match(n)}
    g = defaultdict(lambda: [0.0] * 31)
    f = defaultdict(lambda: [0.0] * 31)
    seen = defaultdict(dict)
    for a, b, v in caps:
        for x, y in ((a, b), (b, a)):
            r = ring_of(x)
            if not r:
                continue
            k = stage(x)
            prev = seen[r].setdefault(k, x)
            assert prev == x, (r, k, prev, x)
            g[r][k] += v
            if y in fill:
                cf = total[y]
                f[r][k] += v * (cf - v) / cf if cf > 0 else 0.0
            else:
                f[r][k] += v
    for r in seen:
        assert sorted(seen[r]) == list(range(31)), (r, sorted(seen[r]))
    json.dump({r: {"grounded": g[r], "floating": f[r]} for r in sorted(g)},
              open(out, "w"), indent=0)
    print(spice, "rings", len(g), "fill nodes", len(fill))


if __name__ == "__main__":
    main(*sys.argv[1:3])
