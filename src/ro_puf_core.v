// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Serial RO-PUF measurement core. One oscillator is measured at a time:
// `start` clears the counter and opens a window of `window` xclk cycles, the
// selected oscillator's edges are counted, and the count freezes when the
// window closes (`done` high). The count tracks frequency. Using a single
// shared counter keeps the measurement identical for every oscillator.
//
// On silicon each oscillator is a hardened black-box macro (so Yosys never
// sees the loop) and the window gate is sky130_fd_sc_hd__dlclkp_1, not an AND.

`timescale 1ps/1ps
`default_nettype none

module ro_puf_core #(
    parameter integer N_RO  = 8,
    parameter integer SEL_W = 3,
    parameter integer CNT_W = 16
) (
    input  wire             xclk,
    input  wire             rst_n,
    input  wire             start,
    input  wire [SEL_W-1:0] ro_sel,
    input  wire [CNT_W-1:0] window,
    output reg              done,
    output wire [CNT_W-1:0] count_out
);

    reg             en_window;
    reg [CNT_W-1:0] wtimer;

    // Only the selected oscillator runs, and only while the window is open.
    // ro_macro is the real cell for synthesis; a matching behavioural ro_macro
    // (sim/ro_macro_sim.v) stands in for simulation. IDX gives each instance a
    // distinct frequency in simulation; it is ignored in hardware.
    wire [N_RO-1:0] ro_out;
    genvar i;
    generate
        for (i = 0; i < N_RO; i = i + 1) begin : g_ro_bank
            ro_macro #(.IDX(i)) u_ro (
                .en (en_window & (ro_sel == i[SEL_W-1:0])),
                .out(ro_out[i])
            );
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

    // Ripple counter. Higher bits clock off the falling edge of the bit below,
    // so the chain counts up; a synchronous adder can't keep up at RO speed.
    reg [CNT_W-1:0] cnt;
    always @(posedge gated_ro or negedge cnt_rst_n)
        if (!cnt_rst_n) cnt[0] <= 1'b0;
        else            cnt[0] <= ~cnt[0];

    genvar b;
    generate
        for (b = 1; b < CNT_W; b = b + 1) begin : g_ripple
            always @(negedge cnt[b-1] or negedge cnt_rst_n)
                if (!cnt_rst_n) cnt[b] <= 1'b0;
                else            cnt[b] <= ~cnt[b];
        end
    endgenerate

    assign count_out = cnt;

endmodule

`default_nettype wire
