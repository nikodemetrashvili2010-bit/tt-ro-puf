// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Simulation-only behavioural model of ro_macro. It has the same ports and
// parameters as the real cell (rtl/ro_macro.v), so the rest of the design
// instantiates `ro_macro` identically for both simulation and synthesis.
//
// Use this file in local testbenches in place of rtl/ro_macro.v, which is a
// real logic loop and cannot run in an event simulator. The frequency depends
// on IDX so each oscillator in the bank differs, imitating the variation that
// the counting tests rely on.

`timescale 1ps/1ps
`default_nettype none

module ro_macro #(
    parameter integer N_INV = 30,
    parameter integer IDX   = 0
) (
    input  wire en,
    output reg  out
);
    localparam integer HALF_PERIOD_PS = 1500 + IDX * 40;

    initial out = 1'b0;

    always begin
        if (en) #(HALF_PERIOD_PS) out = ~out;
        else begin
            out = 1'b0;
            #(HALF_PERIOD_PS);
        end
    end
endmodule

`default_nettype wire
