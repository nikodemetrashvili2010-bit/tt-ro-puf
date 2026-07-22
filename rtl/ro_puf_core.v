// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Serial RO-PUF measurement core. One oscillator is measured at a time:
// `start` clears the counter and opens a window of `window` xclk cycles, the
// selected oscillator's edges are counted, and the count freezes when the
// window closes (`done` high). The count tracks frequency. Using a single
// shared counter keeps the measurement identical for every oscillator.
//
// This legacy/reference variant keeps all oscillators inside one bank. The
// production dual-arm implementation is in src/.

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

    localparam integer SETTLE_CYCLES = 2;
    localparam [1:0] ST_IDLE         = 2'd0;
    localparam [1:0] ST_ARM          = 2'd1;
    localparam [1:0] ST_RUN          = 2'd2;
    localparam [1:0] ST_SETTLE       = 2'd3;

    reg             en_window;
    reg [CNT_W-1:0] wtimer;
    reg [SEL_W-1:0] active_sel;
    reg [1:0]       state;
    reg [1:0]       settle_timer;
    reg [CNT_W-1:0] count_latched;

    // Only the selected oscillator runs, and only while the window is open.
    // ro_macro is the real cell for synthesis; a matching behavioural ro_macro
    // (sim/ro_macro_sim.v) stands in for simulation. IDX gives each instance a
    // distinct frequency in simulation; it is ignored in hardware.
    wire [N_RO-1:0] ro_out;
    genvar i;
    generate
        for (i = 0; i < N_RO; i = i + 1) begin : g_ro_bank
            ro_macro #(.IDX(i)) u_ro (
                .en (en_window & (active_sel == i[SEL_W-1:0])),
                .out(ro_out[i])
            );
        end
    endgenerate
    wire sel_ro = ro_out[active_sel];

    wire gated_ro  = sel_ro & en_window;
    wire cnt_rst_n = rst_n & ~start;        // clear before each measurement

    // Asynchronous ripple counter, built as one toggle flip-flop per bit. Each
    // stage is clocked by the previous stage's inverted output (Q-bar), so a
    // bit flips when the bit below it falls, which makes the chain count up.
    // Building it bit by bit keeps every flip-flop a single-driver signal,
    // which the linter requires (one reg vector driven by many clocked blocks
    // is rejected as multiply-driven).
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

    // Stop the asynchronous source and wait two complete reference cycles
    // before capturing the stationary ripple-count bus.
    always @(posedge xclk or negedge rst_n) begin
        if (!rst_n) begin
            en_window     <= 1'b0;
            wtimer        <= {CNT_W{1'b0}};
            active_sel    <= {SEL_W{1'b0}};
            state         <= ST_IDLE;
            settle_timer  <= 2'd0;
            count_latched <= {CNT_W{1'b0}};
            done          <= 1'b0;
        end else if (start) begin
            en_window     <= 1'b0;
            wtimer        <= {CNT_W{1'b0}};
            active_sel    <= ro_sel;
            state         <= ST_ARM;
            settle_timer  <= 2'd0;
            count_latched <= {CNT_W{1'b0}};
            done          <= 1'b0;
        end else begin
            case (state)
                ST_ARM: begin
                    wtimer <= {CNT_W{1'b0}};
                    if (window == {CNT_W{1'b0}}) begin
                        en_window    <= 1'b0;
                        settle_timer <= 2'd0;
                        state        <= ST_SETTLE;
                    end else begin
                        en_window <= 1'b1;
                        state     <= ST_RUN;
                    end
                end

                ST_RUN: begin
                    if (wtimer == window - 1'b1) begin
                        en_window    <= 1'b0;
                        settle_timer <= 2'd0;
                        state        <= ST_SETTLE;
                    end else begin
                        wtimer <= wtimer + 1'b1;
                    end
                end

                ST_SETTLE: begin
                    if (settle_timer == SETTLE_CYCLES - 1) begin
                        count_latched <= cnt;
                        done          <= 1'b1;
                        state         <= ST_IDLE;
                    end else begin
                        settle_timer <= settle_timer + 1'b1;
                    end
                end

                default: begin
                    en_window <= 1'b0;
                    state     <= ST_IDLE;
                end
            endcase
        end
    end

    assign count_out = count_latched;

endmodule

`default_nettype wire
