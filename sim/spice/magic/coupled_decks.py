#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The same rings with their own couplings kept as couplings.

The lumped decks ground every capacitor, including the ones between two
nodes of the same ring, which swing against each other. The archive did
the same and its full RC decks moved every ring by about one percent and
no bit. This checks that the magic numbers behave the same way: for the
named rings, capacitors between two loop nodes of one ring become real
capacitors between the deck nodes, everything else stays grounded (fill
floating, as before).

Usage: python3 coupled_decks.py NAME.spice MODE OUTDIR LIB CELLS RING...
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from ring_loads import read, ring_of, FILL  # noqa: E402
from node_caps import stage  # noqa: E402
import gen_decks  # noqa: E402


def main(spice, mode, outdir, lib, cells, *rings):
    caps = read(spice)
    total = defaultdict(float)
    for a, b, v in caps:
        total[a] += v
        total[b] += v
    fill = {n for n in total if FILL.match(n)}
    os.makedirs(outdir, exist_ok=True)
    for ring in rings:
        ground = [0.0] * 31
        couple = defaultdict(float)
        for a, b, v in caps:
            ra, rb = ring_of(a), ring_of(b)
            if ra == ring and rb == ring:
                i, j = sorted((stage(a), stage(b)))
                if i != j:
                    couple[(i, j)] += v
                continue
            for x, y, r in ((a, b, ra), (b, a, rb)):
                if r != ring:
                    continue
                if y in fill and mode == "floating":
                    ground[stage(x)] += v * (total[y] - v) / total[y]
                else:
                    ground[stage(x)] += v
        text = gen_decks.deck(ring + " coupled", ground, lib, cells)
        extra = "".join("Cc%d_%d n%d n%d %.6e\n" % (i, j, i, j, c * 1e-15)
                        for (i, j), c in sorted(couple.items()))
        text = text.replace("Cout out 0", extra + "Cout out 0")
        with open(os.path.join(outdir, ring + ".spice"), "w") as f:
            f.write(text)
        print(ring, "grounded %.3f fF, within-ring couplings %d, %.3f fF"
              % (sum(ground), len(couple), sum(couple.values())))


if __name__ == "__main__":
    main(*sys.argv[1:6], *sys.argv[6:])
