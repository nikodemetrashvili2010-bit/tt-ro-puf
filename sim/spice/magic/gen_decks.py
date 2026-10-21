#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Lumped ring decks with magic's loads, in gen_rc_decks.py's lumped shape.

Same cells, supply, start-up and measurement as the archived
rc3/armA/roNN_lumped.spice: a NAND, thirty inv_1, a buf_1 on n15, one
grounded capacitor per loop node, the period from the buffer's rising
edges. Only the capacitors differ, and the tap output load
is held at one value for every ring so it cannot tell rings apart. The
period here is taken over the 5th to 15th rising edge in a 40 ns run,
where the archive took the 5th to 25th in 140 ns: ten periods instead of
twenty, to fit 96 decks into an afternoon on two cores. The check deck
(the archive's own ro00 loads in this template) says what that costs.

Usage: python3 gen_decks.py LOADS.json MODE OUTDIR LIB CELLS
       MODE is grounded or floating
"""
import json
import os
import sys

COUT_F = 7.5e-15


def deck(ring, caps, lib, cells):
    lines = [
        "* %s: lumped loads from a magic extraction" % ring,
        '.lib "%s" tt' % lib,
        '.include "%s"' % cells,
        ".param SUPPLY=1.8",
        "Vdd VPWR 0 {SUPPLY}",
        "Ven EN 0 PULSE(0 1.8 2n 50p 50p 1 2)",
        "Xnand EN n30 0 0 VPWR VPWR n0 sky130_fd_sc_hd__nand2_1",
    ]
    for k in range(1, 31):
        lines.append("Xi%d n%d 0 0 VPWR VPWR n%d sky130_fd_sc_hd__inv_1"
                     % (k, k - 1, k))
    lines.append("Xbuf n15 0 0 VPWR VPWR out sky130_fd_sc_hd__buf_1")
    for k, c in enumerate(caps):
        lines.append("Cn%d n%d 0 %.6e" % (k, k, c * 1e-15))
    lines.append("Cout out 0 %.6e" % COUT_F)
    lines += [
        ".save v(out)",
        ".tran 1p 40n",
        ".control",
        "run",
        "meas tran tp TRIG v(out) VAL=0.9 RISE=5 TARG v(out) VAL=0.9 RISE=15",
        "let f = 10 / tp",
        "print f",
        ".endc",
        ".end",
    ]
    return "\n".join(lines) + "\n"


def main(loads, mode, outdir, lib, cells):
    data = json.load(open(loads))
    os.makedirs(outdir, exist_ok=True)
    for ring, d in sorted(data.items()):
        with open(os.path.join(outdir, ring + ".spice"), "w") as f:
            f.write(deck(ring, d[mode], lib, cells))
    print(len(data), "decks in", outdir)


if __name__ == "__main__":
    main(*sys.argv[1:6])
