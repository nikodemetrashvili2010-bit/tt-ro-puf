// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Three-arm RO-PUF top, version v3. 48 oscillators, 16 per arm,
// measured by one shared core. Arm A is auto-placed by the flow;
// Arm B is 16 bit-identical hardened macros instantiated at the
// TinyTapeout top level and wired through here via armb_en /
// armb_out; Arm C is auto-placed under the equalization
// constraints. `arm` selects the arm and `ro_idx` the oscillator
// within it.
//
// Produced by chip/gen_e2_rtl.py from dualarm/src/ro_puf.v. Do not
// edit this copy.

`timescale 1ps/1ps
`default_nettype none

module ro_puf #(
    parameter integer N_PER_ARM = 16,
    parameter integer CNT_W     = 16
) (
    input  wire                 xclk,
    input  wire                 rst_n,
    input  wire                 start,
    input  wire [1:0]           arm,        // 0 = A, 1 = B, 2 = C
    input  wire [3:0]           ro_idx,     // oscillator within the arm, 0..15
    input  wire [CNT_W-1:0]     window,
    output wire [N_PER_ARM-1:0] armb_en,
    input  wire [N_PER_ARM-1:0] armb_out,
    output wire                 done,
    output wire                 active,
    output wire                 overflow,
    output wire [CNT_W-1:0]     count_out
);
    localparam integer N_RO  = 3 * N_PER_ARM;
    localparam integer SEL_W = 6;

    wire [SEL_W-1:0] ro_sel = {arm, ro_idx};   // arm is the high bit

    ro_puf_core #(.N_RO(N_RO), .SEL_W(SEL_W), .CNT_W(CNT_W)) u_core (
        .xclk     (xclk),
        .rst_n    (rst_n),
        .start    (start),
        .ro_sel   (ro_sel),
        .window   (window),
        .armb_en  (armb_en),
        .armb_out (armb_out),
        .done     (done),
        .active   (active),
        .overflow (overflow),
        .count_out(count_out)
    );
endmodule

`default_nettype wire
