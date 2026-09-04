// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// TinyTapeout top level for the two-arm RO-PUF.
//
// Pin map:
//   clk           measurement reference clock (drive from a clean source)
//   rst_n         active-low reset
//   ui_in[0]      start, a rising edge begins one measurement
//   ui_in[1]      arm select (0 = Arm A, 1 = Arm B)
//   ui_in[5:2]    ro_idx, oscillator within the arm (0..15)
//   ui_in[6]      byte select for readout (0 = low byte, 1 = high byte)
//   uo_out[7:0]   selected byte of the 16-bit count
//   uio_out[0]    done, high when the count is valid (uio_oe = 0x01)
//
// To read a result: set arm and ro_idx, pulse ui_in[0], wait for done, then
// read the low byte (ui_in[6]=0) and the high byte (ui_in[6]=1) off uo_out.
// The window length is fixed by the WINDOW parameter.

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

    // One-cycle start pulse from the rising edge of ui_in[0], so a slow
    // software write that holds the pin high still starts exactly one run.
    reg start_d;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) start_d <= 1'b0;
        else        start_d <= ui_in[0];
    wire start_pulse = ui_in[0] & ~start_d;

    wire        done;
    wire [15:0] count;

    ro_puf #(.N_PER_ARM(16), .CNT_W(16)) u_puf (
        .xclk     (clk),
        .rst_n    (rst_n),
        .start    (start_pulse),
        .arm      (arm),
        .ro_idx   (ro_idx),
        .window   (WINDOW),
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
