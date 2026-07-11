// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// TinyTapeout top level for the two-arm RO-PUF, dual-arm version (v2).
//
// Arm B's 16 oscillators are instantiated HERE, flat, as ro_macro_hard
// u_rob0..u_rob15. The instance names must not change: they are the keys of
// MACROS.ro_macro_hard.instances in src/config.json, which pins each copy of
// the hardened macro GDS to a fixed location on a uniform grid. They carry no
// parameters on purpose - parameterized blackboxes would be uniquified by
// yosys ($paramod...) and the MACROS name matching would break.
//
// Pin map (unchanged from v1):
//   clk           measurement reference clock
//   rst_n         active-low reset
//   ui_in[0]      start, a rising edge begins one measurement
//   ui_in[1]      arm select (0 = Arm A auto-placed, 1 = Arm B hardened)
//   ui_in[5:2]    ro_idx, oscillator within the arm (0..15)
//   ui_in[6]      byte select for readout (0 = low byte, 1 = high byte)
//   uo_out[7:0]   selected byte of the 16-bit count
//   uio_out[0]    done, high when the count is valid (uio_oe = 0x01)

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
    localparam [15:0] WINDOW = 16'd1000;

    wire       arm      = ui_in[1];
    wire [3:0] ro_idx   = ui_in[5:2];
    wire       byte_sel = ui_in[6];

    // One-cycle start pulse from the rising edge of ui_in[0].
    reg start_d;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) start_d <= 1'b0;
        else        start_d <= ui_in[0];
    wire start_pulse = ui_in[0] & ~start_d;

    wire        done;
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
        .rst_n    (rst_n),
        .start    (start_pulse),
        .arm      (arm),
        .ro_idx   (ro_idx),
        .window   (WINDOW),
        .armb_en  (armb_en),
        .armb_out (armb_out),
        .done     (done),
        .count_out(count)
    );

    assign uo_out  = byte_sel ? count[15:8] : count[7:0];
    assign uio_out = {7'b0, done};
    assign uio_oe  = 8'b0000_0001;        // only uio[0] is an output

    // Tie off unused inputs to keep the linter quiet.
    wire _unused = &{ena, uio_in, ui_in[7], 1'b0};

endmodule

`default_nettype wire
