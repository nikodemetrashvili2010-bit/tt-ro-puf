// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Arm B oscillator: the ring oscillator that gets HARDENED into a fixed macro
// and stepped/repeated at uniform pitch. It is functionally identical to
// ro_macro (it just instantiates it), but kept as a separate module name so the
// top-level flow can:
//   * black-box it   (VERILOG_FILES_BLACKBOX in the OpenLane config), and
//   * place bit-identical copies of its hardened GDS/LEF at fixed locations
//     (MACROS.ro_macro_hard.instances.<inst>.location).
//
// Every Arm B instance is the SAME hardened GDS, so their internal ring
// parasitics are identical: no per-oscillator internal-layout bias. Hardening
// also inserts input and output clkdlybuf boundary buffers around the ring
// (visible in the extracted netlist; see macro/README.md), so the Arm A and
// Arm B external interfaces are not identical. The go/no-go compares the
// internal-layout term, not a perfectly matched boundary.
//
// This module is part of the integrated dual-arm design: src/tt_um_ro_puf.v
// instantiates 16 copies as u_rob0..u_rob15.

`default_nettype none

module ro_macro_hard #(
    parameter integer N_INV = 30,
    parameter integer IDX   = 0
) (
    input  wire en,
    output wire out
);
    ro_macro #(.N_INV(N_INV), .IDX(IDX)) u_ro (
        .en (en),
        .out(out)
    );
endmodule

`default_nettype wire
