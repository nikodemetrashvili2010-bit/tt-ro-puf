// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Simulation-only behavioural model of the hardened Arm B oscillator macro.
// Parameterless on purpose, exactly like the synthesis blackbox
// (src/ro_macro_hard_bb.v). All 16 copies toggle at the same nominal rate,
// which is precisely the point of the matched arm. Used only by the cocotb
// RTL testbench; never synthesized.

`timescale 1ps/1ps
`default_nettype none

module ro_macro_hard (
    input  wire en,
    output reg  out
);
    localparam integer HALF_PERIOD_PS = 1580;

    initial out = 1'b0;

    always begin
        if (en) #(HALF_PERIOD_PS) out = ~out;
        else begin
            out = 1'b0;
            @(posedge en);
        end
    end
endmodule

`default_nettype wire
