// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// TinyTapeout top level for the three-arm RO-PUF, version v3.
//
// Produced by chip/gen_e2_rtl.py from the frozen two-arm design
// in dualarm/build_2arm_frozen/dualarm_src/tt_um_ro_puf.v and
// chip/OBSERVABILITY.json.
//
// Arm B's 16 oscillators are instantiated HERE, flat, as ro_macro_hard
// u_rob0..u_rob15. The instance names must not change: they are the keys of
// MACROS.ro_macro_hard.instances in src/config.json, which pins each copy of
// the hardened macro GDS to a fixed location on a uniform grid. They carry no
// parameters on purpose - parameterized blackboxes would be uniquified by
// yosys ($paramod...) and the MACROS name matching would break.
//
// Pin map, straight out of chip/OBSERVABILITY.json:
//   clk           measurement reference clock
//   rst_n         active-low reset
//   ui_in[0]      start
//   ui_in[1]      arm select bit 0
//   ui_in[2]      ro_idx[0]
//   ui_in[3]      ro_idx[1]
//   ui_in[4]      ro_idx[2]
//   ui_in[5]      ro_idx[3]
//   ui_in[6]      readout byte select
//   ui_in[7]      arm select bit 1
//   uio_out[0]    done
//   uio_in[1]     window select bit 0
//   uio_in[2]     window select bit 1
//   uio_in[3]     read version instead of count
//   uio_out[4]    counter overflowed, sticky
//   uio_out[5]    measurement active
//   uio_in[6]     reserved
//   uio_in[7]     reserved
//   uo_out[7:0]   count byte, or version byte when uio_in[3] is high
//   uio_oe = 0x31

`timescale 1ps/1ps
`default_nettype none

module tt_um_nikodemetrashvili20_ro_puf (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    // The four preregistered window lengths, in xclk cycles. The
    // first three are safe at every corner; the last overflows the
    // counter at every corner on purpose, so the sticky flag can be
    // exercised on any die. E.2 chose these, not this file. The
    // multiplexer that picks between them sits below the select
    // bits it reads.
    localparam [15:0] WIN0 = 16'd256;
    localparam [15:0] WIN1 = 16'd512;
    localparam [15:0] WIN2 = 16'd2048;
    localparam [15:0] WIN3 = 16'd16384;

    localparam [7:0] PROTOCOL_VERSION = 8'd2;
    localparam [7:0] BUILD_ID         = 8'h1A;

    // Project reset asserts immediately so deselection always shuts down an
    // active oscillator, even if clk has stopped. Release passes through two
    // clk stages so the rest of the design never sees an asynchronous reset
    // deassertion near a clock edge.
    wire async_project_rst_n = rst_n & ena;
    (* async_reg = "true" *) reg [1:0] reset_sync;
    always @(posedge clk or negedge async_project_rst_n) begin
        if (!async_project_rst_n)
            reset_sync <= 2'b00;
        else
            reset_sync <= {reset_sync[0], 1'b1};
    end
    wire project_rst_n = reset_sync[1];

    // The board GPIOs are asynchronous to clk. Synchronize the complete
    // control bundle, then edge-detect start in the synchronized domain.
    // E.2 put four more control signals on pins - the second arm bit, the
    // two window select bits and the version select - and they are no less
    // asynchronous than the rest, so they go through the same two stages
    // rather than being read raw. ui_in keeps the low eight bits of the
    // bundle so every existing decode stays where it was. The
    // host protocol keeps arm/index stable for three clocks before asserting
    // start, holds start for at least three clocks, and leaves the selection
    // unchanged until done. The core latches the synchronized selection before
    // enabling an oscillator. A shorter asynchronous pulse is not guaranteed
    // to be sampled.
    (* async_reg = "true" *) reg [10:0] ui_meta;
    (* async_reg = "true" *) reg [10:0] ui_sync;
    reg start_sync_d;

    always @(posedge clk or negedge project_rst_n) begin
        if (!project_rst_n) begin
            ui_meta      <= 11'b0;
            ui_sync      <= 11'b0;
            start_sync_d <= 1'b0;
        end else begin
            ui_meta      <= {uio_in[3:1], ui_in[7:0]};
            ui_sync      <= ui_meta;
            start_sync_d <= ui_sync[0];
        end
    end

    wire       start_pulse = ui_sync[0] & ~start_sync_d;
    wire [1:0] arm         = {ui_sync[7], ui_sync[1]};
    wire [3:0] ro_idx      = ui_sync[5:2];
    wire       byte_sel    = ui_sync[6];
    wire [1:0] win_sel     = ui_sync[9:8];
    wire       rd_ver      = ui_sync[10];

    // The window is one of the four lengths above, picked by the
    // two synchronized select bits. It sits here, under the wires
    // it reads, rather than up beside the constants.
    reg [15:0] window;
    always @(*) begin
        case (win_sel)
            2'd0:    window = WIN0;
            2'd1:    window = WIN1;
            2'd2:    window = WIN2;
            default: window = WIN3;
        endcase
    end

    wire        done;
    wire        active;
    wire        overflow;
    wire [15:0] count;
    wire [15:0] armb_en;
    wire [15:0] armb_out;

    // Arm B: 16 bit-identical hardened oscillator macros, placed on a uniform
    // grid by config.json. Flat instances, no parameters (see header).
    ro_macro_hard u_rob0  (.en(armb_en[0]),  .out(armb_out[0]));
    ro_macro_hard u_rob1  (.en(armb_en[1]),  .out(armb_out[1]));
    ro_macro_hard u_rob2  (.en(armb_en[2]),  .out(armb_out[2]));
    ro_macro_hard u_rob3  (.en(armb_en[3]),  .out(armb_out[3]));
    ro_macro_hard u_rob4  (.en(armb_en[4]),  .out(armb_out[4]));
    ro_macro_hard u_rob5  (.en(armb_en[5]),  .out(armb_out[5]));
    ro_macro_hard u_rob6  (.en(armb_en[6]),  .out(armb_out[6]));
    ro_macro_hard u_rob7  (.en(armb_en[7]),  .out(armb_out[7]));
    ro_macro_hard u_rob8  (.en(armb_en[8]),  .out(armb_out[8]));
    ro_macro_hard u_rob9  (.en(armb_en[9]),  .out(armb_out[9]));
    ro_macro_hard u_rob10 (.en(armb_en[10]), .out(armb_out[10]));
    ro_macro_hard u_rob11 (.en(armb_en[11]), .out(armb_out[11]));
    ro_macro_hard u_rob12 (.en(armb_en[12]), .out(armb_out[12]));
    ro_macro_hard u_rob13 (.en(armb_en[13]), .out(armb_out[13]));
    ro_macro_hard u_rob14 (.en(armb_en[14]), .out(armb_out[14]));
    ro_macro_hard u_rob15 (.en(armb_en[15]), .out(armb_out[15]));

    ro_puf #(.N_PER_ARM(16), .CNT_W(16)) u_puf (
        .xclk     (clk),
        .rst_n    (project_rst_n),
        .start    (start_pulse),
        .arm      (arm),
        .ro_idx   (ro_idx),
        .window   (window),
        .armb_en  (armb_en),
        .armb_out (armb_out),
        .done     (done),
        .active   (active),
        .overflow (overflow),
        .count_out(count)
    );

    // The version bytes read out through the same port as the count,
    // selected by a pin, so a board can identify the design without a
    // second readout path. byte_sel picks the half in both modes.
    wire [7:0] count_byte = byte_sel ? count[15:8] : count[7:0];
    wire [7:0] ver_byte   = byte_sel ? BUILD_ID : PROTOCOL_VERSION;
    assign uo_out  = rd_ver ? ver_byte : count_byte;
    assign uio_out = {2'b0, active, overflow, 3'b0, done};
    assign uio_oe  = 8'h31;             // uio[0], uio[4], uio[5] drive

    // Tie off unused inputs to keep the linter quiet. Pulling ena low is an
    // asynchronous project reset, so it also shuts down an active oscillator
    // even if the reference clock has stopped.
    wire _unused = &{uio_in[7:4], uio_in[0], 1'b0};

endmodule

`default_nettype wire
