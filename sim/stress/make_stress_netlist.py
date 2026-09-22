#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Turn the gate-level netlist into one an event simulator can run.

The sky130 functional models give combinational cells no delay, so an
enabled ring in the gate-level netlist is a zero-delay loop and simulated
time stops. This script swaps the master of every cell that sits on a
ring (the enable NAND, the 30 inverters and the tap buffer of each Arm A
and Arm C ring in the top netlist, and the same three kinds inside the
Arm B macro netlist) for a delayed copy with the same ports, and gives
every ring its own per-stage delay so that a count identifies the ring
that ran. Nothing else in the netlist is touched: every flop, decoder,
mux, buffer and tie cell stays the real sky130 model.

Delays in ps per stage, half period = 31 * D:
  Arm A ring i : D = 26 + 2i   (26..56)
  Arm C ring i : D = 27 + 2i   (27..57)
  Arm B ring i : D = 60 + i    (60..75)
All 48 are distinct. stress.py carries the same table.

  python3 make_stress_netlist.py TOP.nl.v ro_macro_hard.nl.v OUT.v
  python3 make_stress_netlist.py --selftest TOP.nl.v ro_macro_hard.nl.v
"""
import re
import sys


def delay(arm, i):
    return {"A": 26 + 2 * i, "C": 27 + 2 * i, "B": 60 + i}[arm]


SWAP = {
    "sky130_fd_sc_hd__inv_1": "ring_inv_1",
    "sky130_fd_sc_hd__nand2_1": "ring_nand2_1",
    "sky130_fd_sc_hd__buf_1": "ring_buf_1",
}

RING_RE = re.compile(
    r"^ (sky130_fd_sc_hd__(?:inv_1|nand2_1|buf_1)) "
    r"(\\u_puf\.u_core\.(g_ro_bank|g_armc)\[(\d+)\]\.(?:u_ro|u_roc)\.\S+)  \(")
MACRO_RE = re.compile(
    r"^ (sky130_fd_sc_hd__(?:inv_1|nand2_1|buf_1)) (\\u_ro\.\S+)  \(")
INST_RE = re.compile(r"^ ro_macro_hard (u_rob(\d+)) \(")
HEADER = "module ro_macro_hard ("

CELLS = """
// Delayed copies of the three ring cells. Same ports as the sky130
// models, an inertial delay of D ps per stage, nothing else.
`timescale 1ps/1ps
module ring_inv_1 #(parameter integer D = 30) (input A, output Y);
    assign #D Y = ~A;
endmodule
module ring_nand2_1 #(parameter integer D = 30) (input A, input B,
                                                 output Y);
    assign #D Y = ~(A & B);
endmodule
module ring_buf_1 #(parameter integer D = 30) (input A, output X);
    assign #D X = A;
endmodule
"""


def transform(top_text, macro_text):
    """Return the simulation netlist. Raises ValueError when the cell
    counts are not the 1024 + 16 and 32 of this design, so a netlist
    from some other build cannot go through quietly."""
    out = []
    swapped = 0
    for line in top_text.splitlines():
        m = RING_RE.match(line)
        if m:
            master, name = m.group(1), m.group(2)
            arm = "A" if m.group(3) == "g_ro_bank" else "C"
            d = delay(arm, int(m.group(4)))
            line = (" %s #(.D(%d)) %s  (" % (SWAP[master], d, name)
                    + line[m.end():])
            swapped += 1
        m = INST_RE.match(line)
        if m:
            d = delay("B", int(m.group(2)))
            line = (" ro_macro_hard #(.D(%d)) %s (" % (d, m.group(1))
                    + line[m.end():])
            swapped += 1
        out.append(line)
    if swapped != 32 * 32 + 16:
        raise ValueError("top netlist: swapped %d, expected 1040" % swapped)

    mout = []
    mswapped = 0
    header = False
    for line in macro_text.splitlines():
        if line.startswith(HEADER):
            line = "module ro_macro_hard #(parameter integer D = 60) (" + \
                line[len(HEADER):]
            header = True
        m = MACRO_RE.match(line)
        if m:
            line = " %s #(.D(D)) %s  (" % (SWAP[m.group(1)], m.group(2)) + \
                line[m.end():]
            mswapped += 1
        mout.append(line)
    if mswapped != 32 or not header:
        raise ValueError("macro netlist: swapped %d of 32, header %s"
                         % (mswapped, header))
    return CELLS + "\n".join(mout) + "\n" + "\n".join(out) + "\n"


def selftest(top, macro):
    """Plant what the transform must refuse: a ring cell missing from the
    top netlist, one missing from the macro, and a macro header it does
    not recognise. Each must raise; the real files must not."""
    transform(top, macro)
    faults = [
        ("top ring cell retyped", top.replace(
            " sky130_fd_sc_hd__inv_1 \\u_puf.u_core.g_ro_bank[3].u_ro.g_inv[1",
            " sky130_fd_sc_hd__inv_2 \\u_puf.u_core.g_ro_bank[3].u_ro.g_inv[1",
            1),
         macro),
        ("macro ring cell retyped", top, macro.replace(
            " sky130_fd_sc_hd__nand2_1 \\u_ro.u_nand  (",
            " sky130_fd_sc_hd__nand2_2 \\u_ro.u_nand  (", 1)),
        ("macro header renamed", top,
         macro.replace(HEADER, "module ro_macro_hard_x (", 1)),
    ]
    caught = 0
    for name, t, mm in faults:
        if t == top and mm == macro:
            print("planted %s: the fixture did not change anything" % name)
            return 1
        try:
            transform(t, mm)
        except ValueError as e:
            print("planted %s: refused (%s)" % (name, e))
            caught += 1
        else:
            print("planted %s: NOT refused" % name)
    print("selftest %d of %d" % (caught, len(faults)))
    return 0 if caught == len(faults) else 1


def main(argv):
    if argv[1] == "--selftest":
        return selftest(open(argv[2]).read(), open(argv[3]).read())
    top_in, macro_in, out_path = argv[1], argv[2], argv[3]
    text = transform(open(top_in).read(), open(macro_in).read())
    with open(out_path, "w") as f:
        f.write("// Generated by make_stress_netlist.py from\n")
        f.write("//   %s\n//   %s\n" % (top_in, macro_in))
        f.write(text)
    print("wrote %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
