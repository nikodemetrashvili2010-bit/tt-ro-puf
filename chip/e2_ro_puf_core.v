// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Serial RO-PUF measurement core, three-arm version (v3).
//
// Produced by chip/gen_e2_rtl.py from dualarm/src/ro_puf_core.v by
// named edits. Do not edit this copy: edit the live file or the
// generator, whichever the change belongs to.
//
// Arm A (oscillators 0..N_A-1) is generated here as ro_macro
// instances and auto-placed by the flow. Arm C (2*N_A..3*N_A-1) is
// generated here too, as ro_armc, the same ring under its own name
// so that the placement constraints in chip/armc_place.tcl can hold
// it to equalized regions. Arm B (N_A..2*N_A-1) lives OUTSIDE this
// module: the top level instantiates the hardened ro_macro_hard
// macros flat (so their instance names match the MACROS placement
// keys in config.json) and connects them through the armb_en /
// armb_out buses.
// `start` latches the selector, resets the ripple counter during a quiet arm
// cycle, runs exactly `window` xclk periods, stops the RO, synchronizes the
// stopped counter, and publishes it only after repeated stable samples.

`timescale 1ps/1ps
`default_nettype none

module ro_puf_core #(
    parameter integer N_RO  = 12,
    parameter integer SEL_W = 4,
    parameter integer CNT_W = 16
) (
    input  wire                 xclk,
    input  wire                 rst_n,
    input  wire                 start,
    input  wire [SEL_W-1:0]     ro_sel,
    input  wire [CNT_W-1:0]     window,
    output wire [N_RO/3-1:0]    armb_en,   // per-oscillator enables for Arm B
    input  wire [N_RO/3-1:0]    armb_out,  // Arm B oscillator outputs
    output reg                  done,
    output wire                 active,    // the window is open
    output reg                  overflow,  // sticky: a run wrapped the counter
    output wire [CNT_W-1:0]     count_out
);
    localparam integer N_A            = N_RO / 3;
    localparam integer N_SLOT         = 1 << SEL_W;
    localparam [2:0] MIN_SETTLE_CYCLES = 3'd2;
    localparam [1:0] REQUIRED_STABLE_SAMPLES = 2'd3;
    localparam [1:0] ST_IDLE          = 2'd0;
    localparam [1:0] ST_ARM           = 2'd1;
    localparam [1:0] ST_RUN           = 2'd2;
    localparam [1:0] ST_SETTLE        = 2'd3;

    reg             en_window;
    reg [CNT_W-1:0] wtimer;
    reg [SEL_W-1:0] active_sel;
    reg [1:0]       state;
    reg [2:0]       settle_timer;
    reg [1:0]       stable_samples;
    reg [CNT_W-1:0] count_latched;
    // One bit wider than the counter. Bit CNT_W is the ring-domain
    // wrap flag, so a wrap crosses into xclk through the same two
    // async_reg stages and the same stable-sample rule as the count,
    // rather than through a path of its own.
    (* async_reg = "true" *) reg [CNT_W:0] cnt_meta;
    (* async_reg = "true" *) reg [CNT_W:0] cnt_sync;
    reg [CNT_W:0]   cnt_sync_prev;

    // Arm A: only the selected oscillator runs, and only while the window is
    // open. ro_macro is the real cell for synthesis; a matching behavioural
    // ro_macro (ro_macro_sim.v) stands in for simulation.
    wire [N_SLOT-1:0] ro_out;
    genvar i;
    generate
        for (i = 0; i < N_A; i = i + 1) begin : g_ro_bank
            ro_macro #(.IDX(i)) u_ro (
                .en (en_window & (active_sel == i[SEL_W-1:0])),
                .out(ro_out[i])
            );
        end
    endgenerate

    // Arm B: enables computed here, oscillators instantiated at the top.
    generate
        for (i = 0; i < N_A; i = i + 1) begin : g_armb
            localparam integer SB = N_A + i;
            assign armb_en[i]     = en_window & (active_sel == SB[SEL_W-1:0]);
            assign ro_out[N_A+i]  = armb_out[i];
        end
    endgenerate

    // Arm C: the same ring as Arm A, under its own module name so
    // synthesis cannot share cells between the arms, placed inside
    // the equalized regions chip/armc_place.tcl declares. The select
    // constant goes through a localparam the way Arm B's does,
    // because a part-select applies to a name and never to a
    // parenthesised expression.
    generate
        for (i = 0; i < N_A; i = i + 1) begin : g_armc
            localparam integer SC = 2 * N_A + i;
            ro_armc #(.IDX(i)) u_roc (
                .en (en_window & (active_sel == SC[SEL_W-1:0])),
                .out(ro_out[2*N_A+i])
            );
        end
    endgenerate

    // Two arm bits name four arms and there are three, so active_sel
    // can point at a slot no oscillator fills. Those slots are tied
    // low here rather than left off the vector, which keeps the
    // selection below a plain index with no gate in front of it.
    generate
        for (i = N_RO; i < N_SLOT; i = i + 1) begin : g_no_arm
            assign ro_out[i] = 1'b0;
        end
    endgenerate

    // The measurement-active flag is the window enable brought out,
    // not a second timer that could disagree with it.
    assign active = en_window;

    wire sel_ro = ro_out[active_sel];

    // The counter is clocked by the raw selected ring output. An earlier
    // revision put `sel_ro & en_window` here, but en_window belongs to the
    // xclk domain and can fall at any phase of the ~570 MHz ring, so that AND
    // gate could chop the final high pulse into a runt on the clock net.
    // Clocking from the raw ring removes the gate: every edge the flop sees is
    // a clean full-swing ring transition, and the window is enforced through
    // the oscillator enables instead (see g_ro_bank / g_armb above).
    //
    // Stopping a free ring still leaves one boundary effect. When en_window
    // falls the NAND disables the selected ring, and the final tap pulse before
    // it settles can be any width, down to nearly zero, depending on where the
    // disable lands in the cycle. A SPICE phase sweep of the extracted ring
    // driving a real dfrtp flop (sim/spice/gono/gen_flop_sweep.py) shows the
    // flop resolves that boundary cleanly at every phase: it either counts the
    // last edge or it does not, the output never hangs mid-rail, and the
    // captured value moves by at most one count. That one-count ambiguity,
    // about one part in twenty thousand of the full window, is absorbed by the
    // stopped-ring settle handshake below, which latches only after the
    // synchronized counter reads equal three times and otherwise leaves done
    // low rather than returning a torn word.
    wire cnt_rst_n = rst_n & ~start;        // clear before each measurement

    // Asynchronous ripple counter, one toggle flip-flop per bit (single-driver
    // per signal, as the linter requires).
    wire [CNT_W-1:0] cnt;
    wire [CNT_W:0]   tff_clk;
    assign tff_clk[0] = sel_ro;

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

    // Wrap flag, in the ring domain. tff_clk[CNT_W] is the top bit's
    // Q-bar, so its rising edge is the counter rolling over. The
    // flop only ever sets and its D is tied high, so there is no
    // data edge for the ring clock to catch. cnt_rst_n clears it
    // with the counter at the start of each measurement, which is
    // also why the falling edge the counter's own clear produces on
    // tff_clk[CNT_W] cannot set it: the clear is asserted first and
    // is held for the whole of ST_ARM.
    //
    // Set-only and not a seventeenth toggle bit, deliberately. The
    // overflow window wraps once at the slow corner and four times
    // at the fast one, and a toggle would read back as no wrap at
    // all on a fast die.
    reg wrapped;
    always @(posedge tff_clk[CNT_W] or negedge cnt_rst_n)
        if (!cnt_rst_n) wrapped <= 1'b0;
        else            wrapped <= 1'b1;

    // The ripple counter is not published while it is changing. ST_SETTLE
    // first stops every oscillator, lets a two-flop sampler drain, and then
    // requires three consecutive equal synchronized samples before capture.
    // This is a stopped-clock stability handshake, not a claim that the ripple
    // counter is synchronous to xclk. If the counter does not settle, done
    // remains low instead of returning a torn binary word.
    //
    // ST_ARM also guarantees a quiet cycle after each start/restart. It lets
    // the asynchronous counter reset finish and makes active_sel stable before
    // an oscillator is enabled.
    always @(posedge xclk or negedge rst_n) begin
        if (!rst_n) begin
            en_window    <= 1'b0;
            wtimer       <= {CNT_W{1'b0}};
            active_sel   <= {SEL_W{1'b0}};
            state        <= ST_IDLE;
            settle_timer <= 3'd0;
            stable_samples <= 2'd0;
            count_latched <= {CNT_W{1'b0}};
            cnt_meta      <= {(CNT_W+1){1'b0}};
            cnt_sync      <= {(CNT_W+1){1'b0}};
            cnt_sync_prev <= {(CNT_W+1){1'b0}};
            done         <= 1'b0;
            overflow     <= 1'b0;
        end else begin
            cnt_meta <= {wrapped, cnt};
            cnt_sync <= cnt_meta;

            if (start) begin
                en_window      <= 1'b0;
                wtimer         <= {CNT_W{1'b0}};
                active_sel     <= ro_sel;
                state          <= ST_ARM;
                settle_timer   <= 3'd0;
                stable_samples <= 2'd0;
                cnt_sync_prev  <= {(CNT_W+1){1'b0}};
                count_latched  <= {CNT_W{1'b0}};
                done           <= 1'b0;
            end else begin
            case (state)
                ST_ARM: begin
                    wtimer <= {CNT_W{1'b0}};
                    if (window == {CNT_W{1'b0}}) begin
                        en_window    <= 1'b0;
                        settle_timer <= 3'd0;
                        stable_samples <= 2'd0;
                        state        <= ST_SETTLE;
                    end else begin
                        en_window <= 1'b1;
                        state     <= ST_RUN;
                    end
                end

                ST_RUN: begin
                    // en_window is high for exactly `window` complete xclk
                    // periods. For WINDOW=1000, this branch closes it on the
                    // 1000th RUN edge, not the 1001st.
                    if (wtimer == window - 1'b1) begin
                        en_window    <= 1'b0;
                        settle_timer <= 3'd0;
                        stable_samples <= 2'd0;
                        state        <= ST_SETTLE;
                    end else begin
                        wtimer <= wtimer + 1'b1;
                    end
                end

                ST_SETTLE: begin
                    cnt_sync_prev <= cnt_sync;
                    if (settle_timer < MIN_SETTLE_CYCLES) begin
                        settle_timer   <= settle_timer + 1'b1;
                        stable_samples <= 2'd0;
                    end else if (cnt_sync == cnt_sync_prev) begin
                        if (stable_samples == REQUIRED_STABLE_SAMPLES - 1'b1) begin
                            count_latched  <= cnt_sync[CNT_W-1:0];
                            if (cnt_sync[CNT_W])
                                overflow   <= 1'b1;
                            done           <= 1'b1;
                            state          <= ST_IDLE;
                            stable_samples <= 2'd0;
                        end else begin
                            stable_samples <= stable_samples + 1'b1;
                        end
                    end else begin
                        stable_samples <= 2'd0;
                    end
                end

                default: begin
                    en_window <= 1'b0;
                    state     <= ST_IDLE;
                end
            endcase
            end
        end
    end

    assign count_out = count_latched;

endmodule

`default_nettype wire
