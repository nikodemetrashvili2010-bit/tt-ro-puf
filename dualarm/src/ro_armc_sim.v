// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Simulation-only behavioural model of ro_armc, the Arm C ring. Same ports
// and parameters as the real cell (src/ro_armc.v), so the core instantiates
// `ro_armc` identically for simulation and for synthesis.
//
// The real one is an enable NAND, thirty inverters and a buffered mid-chain
// tap, which is a zero-delay logic loop and cannot run in an event
// simulator. That is the same reason ro_macro_sim.v exists for Arm A.
//
// The half period below is a fiction and is not a prediction. Arm C is the
// Arm A ring under placement equalization, and what it will actually run at
// is the thing the chip is being built to find out. What the model has to do
// is let a testbench see which arm a selector landed on, so it takes Arm A's
// ladder and shifts it: same slope, 100 ps faster at every index. A selector
// that reaches the wrong arm then reads a different count at the same index
// rather than an identical one.

`timescale 1ps/1ps
`default_nettype none

module ro_armc #(
    parameter integer N_INV = 30,
    parameter integer IDX   = 0
) (
    input  wire en,
    output reg  out
);
    localparam integer HALF_PERIOD_PS = 1400 + IDX * 40;

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
