// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Serial RO-PUF measurement core, dual-arm version (v2).
// Arm A (oscillators 0..N_RO/2-1) is generated here as ro_macro instances and
// auto-placed by the flow. Arm B (oscillators N_RO/2..N_RO-1) lives OUTSIDE
// this module: the top level instantiates the hardened ro_macro_hard macros
// flat (so their instance names match the MACROS placement keys in
// config.json) and connects them through the armb_en / armb_out buses.
// Everything else (window, ripple counter) is unchanged from the green v1.

`timescale 1ps/1ps
`default_nettype none

module ro_puf_core #(
    parameter integer N_RO  = 8,
    parameter integer SEL_W = 3,
    parameter integer CNT_W = 16
) (
    input  wire                 xclk,
    input  wire                 rst_n,
    input  wire                 start,
    input  wire [SEL_W-1:0]     ro_sel,
    input  wire [CNT_W-1:0]     window,
    output wire [N_RO/2-1:0]    armb_en,   // per-oscillator enables for Arm B
    input  wire [N_RO/2-1:0]    armb_out,  // Arm B oscillator outputs
    output reg                  done,
    output wire [CNT_W-1:0]     count_out
);
    localparam integer N_A = N_RO / 2;

    reg             en_window;
    reg [CNT_W-1:0] wtimer;

    // Arm A: only the selected oscillator runs, and only while the window is
    // open. ro_macro is the real cell for synthesis; a matching behavioural
    // ro_macro (ro_macro_sim.v) stands in for simulation.
    wire [N_RO-1:0] ro_out;
    genvar i;
    generate
        for (i = 0; i < N_A; i = i + 1) begin : g_ro_bank
            ro_macro #(.IDX(i)) u_ro (
                .en (en_window & (ro_sel == i[SEL_W-1:0])),
                .out(ro_out[i])
            );
        end
    endgenerate

    // Arm B: enables computed here, oscillators instantiated at the top.
    generate
        for (i = 0; i < N_A; i = i + 1) begin : g_armb
            localparam integer SB = N_A + i;
            assign armb_en[i]     = en_window & (ro_sel == SB[SEL_W-1:0]);
            assign ro_out[N_A+i]  = armb_out[i];
        end
    endgenerate

    wire sel_ro = ro_out[ro_sel];

    // Window timer, clocked by the external crystal.
    always @(posedge xclk or negedge rst_n) begin
        if (!rst_n) begin
            en_window <= 1'b0;
            wtimer    <= {CNT_W{1'b0}};
            done      <= 1'b0;
        end else if (start) begin
            en_window <= 1'b1;
            wtimer    <= {CNT_W{1'b0}};
            done      <= 1'b0;
        end else if (en_window) begin
            if (wtimer == window) begin
                en_window <= 1'b0;
                done      <= 1'b1;
            end else begin
                wtimer <= wtimer + 1'b1;
            end
        end
    end

    wire gated_ro  = sel_ro & en_window;
    wire cnt_rst_n = rst_n & ~start;        // clear before each measurement

    // Asynchronous ripple counter, one toggle flip-flop per bit (single-driver
    // per signal, as the linter requires).
    wire [CNT_W-1:0] cnt;
    wire [CNT_W:0]   tff_clk;
    assign tff_clk[0] = gated_ro;

    genvar b;
    generate
        for (b = 0; b < CNT_W; b = b + 1) begin : g_ripple
            reg q;
            always @(posedge tff_clk[b] or negedge cnt_rst_n)
                if (!cnt_rst_n) q <= 1'b0;
                else            q <= ~q;
            assign cnt[b]       = q;
            assign tff_clk[b+1] = ~q;   // Q-bar clocks the next stage
        end
    endgenerate

    assign count_out = cnt;

endmodule

`default_nettype wire
