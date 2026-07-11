// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Two-arm RO-PUF top, dual-arm version (v2). 32 oscillators, 16 per arm,
// measured by one shared core. Arm A is auto-placed by the flow; Arm B is 16
// bit-identical hardened macros instantiated at the TinyTapeout top level and
// wired through here via armb_en / armb_out. `arm` selects the arm and
// `ro_idx` the oscillator within it.

`timescale 1ps/1ps
`default_nettype none

module ro_puf #(
    parameter integer N_PER_ARM = 16,
    parameter integer CNT_W     = 16
) (
    input  wire                 xclk,
    input  wire                 rst_n,
    input  wire                 start,
    input  wire                 arm,        // 0 = Arm A, 1 = Arm B
    input  wire [3:0]           ro_idx,     // oscillator within the arm, 0..15
    input  wire [CNT_W-1:0]     window,
    output wire [N_PER_ARM-1:0] armb_en,
    input  wire [N_PER_ARM-1:0] armb_out,
    output wire                 done,
    output wire [CNT_W-1:0]     count_out
);
    localparam integer N_RO  = 2 * N_PER_ARM;
    localparam integer SEL_W = 5;

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
        .count_out(count_out)
    );
endmodule

`default_nettype wire
