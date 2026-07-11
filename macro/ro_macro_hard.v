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
// Because every Arm B instance is the SAME hardened GDS, their internal ring
// parasitics are identical -> no per-oscillator layout bias (see the go/no-go:
// the auto-placed Arm A spread 8.8% peak-to-peak; matched Arm B -> ~0).
//
// NOT yet wired into the build: this file is intentionally absent from
// info.yaml source_files, so the current (green) design is unaffected. It is
// added to the build only when the Arm B integration step begins, on a branch.

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
