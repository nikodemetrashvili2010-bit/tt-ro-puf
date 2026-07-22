// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Hardened ring-oscillator cell, built from sky130 standard cells. This is the
// real oscillator that goes on silicon, the synthesis and layout version of
// ro_behavioural.v.
//
// Structure: N_INV+1 inverting stages in a loop. Stage 0 is an enable NAND,
// which behaves as an inverter when en=1 and forces a fixed level when en=0 so
// the oscillation stops cleanly. The remaining N_INV stages are inverters. An
// odd total number of inversions makes the loop oscillate. The output leaves
// through a buffer so the load on the multiplexer downstream cannot pull on the
// loop and shift the frequency.
//
// Stage count: SPICE on the 15-stage version measured ~1.27 GHz, which is too
// close to the maximum toggle rate of a sky130 flip-flop to count reliably
// across corners. N_INV=30 (31 stages total) brings it to roughly 600 MHz,
// which leaves comfortable margin for the counter's first flip-flop. The count
// is a single knob, retune it once layout gives real area numbers.
//
// Notes:
//   - Not event-simulable: a zero-delay logic loop cannot run in Icarus. The
//     frequency is checked in SPICE (sim/spice/ro_osc_tb.spice) and, after
//     layout, with extracted parasitics. Functional simulation of the wider
//     design uses ro_behavioural.v.
//   - On the chip this cell is hardened into a fixed macro and black-boxed.
//   - Power pins (VPWR, VGND, VPB, VNB) are connected by the hardening flow.

`default_nettype none

module ro_macro #(
    parameter integer N_INV = 30,       // inverters after the enable NAND
    parameter integer IDX   = 0         // instance index: unused in hardware,
                                        // used only by the simulation model
) (
    input  wire en,
    output wire out
);
    wire [N_INV:0] n;

    // Stage 0: enable NAND (inverts when en = 1, holds when en = 0).
    (* keep *) sky130_fd_sc_hd__nand2_1 u_nand (.A(en), .B(n[N_INV]), .Y(n[0]));

    // Stages 1..N_INV: inverter chain. n[N_INV] feeds back into the NAND.
    genvar i;
    generate
        for (i = 1; i <= N_INV; i = i + 1) begin : g_inv
            (* keep *) sky130_fd_sc_hd__inv_1 u_inv (.A(n[i-1]), .Y(n[i]));
        end
    endgenerate

    // Isolating output buffer, tapped mid-chain.
    (* keep *) sky130_fd_sc_hd__buf_1 u_buf (.A(n[N_INV/2]), .X(out));

endmodule

`default_nettype wire
