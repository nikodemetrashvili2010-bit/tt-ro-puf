// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0
//
// Behavioural ring oscillator for simulation. Toggles every HALF_PERIOD_PS
// while enabled, held low otherwise. Not synthesisable; on silicon the
// oscillator is a hardened GDS macro.

`timescale 1ps/1ps
`default_nettype none

module ro_behavioural #(
    parameter integer HALF_PERIOD_PS = 1667
) (
    input  wire en,
    output reg  out
);
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
