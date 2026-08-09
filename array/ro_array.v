// SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
// SPDX-License-Identifier: Apache-2.0

// Arm B matched array: 16 bit-identical hardened oscillator macros.
`default_nettype none
module ro_array (
    input  wire        en,
    output wire [15:0] out
);
  ro_macro_hard u_rob0 (.en(en), .out(out[0]));
  ro_macro_hard u_rob1 (.en(en), .out(out[1]));
  ro_macro_hard u_rob2 (.en(en), .out(out[2]));
  ro_macro_hard u_rob3 (.en(en), .out(out[3]));
  ro_macro_hard u_rob4 (.en(en), .out(out[4]));
  ro_macro_hard u_rob5 (.en(en), .out(out[5]));
  ro_macro_hard u_rob6 (.en(en), .out(out[6]));
  ro_macro_hard u_rob7 (.en(en), .out(out[7]));
  ro_macro_hard u_rob8 (.en(en), .out(out[8]));
  ro_macro_hard u_rob9 (.en(en), .out(out[9]));
  ro_macro_hard u_rob10 (.en(en), .out(out[10]));
  ro_macro_hard u_rob11 (.en(en), .out(out[11]));
  ro_macro_hard u_rob12 (.en(en), .out(out[12]));
  ro_macro_hard u_rob13 (.en(en), .out(out[13]));
  ro_macro_hard u_rob14 (.en(en), .out(out[14]));
  ro_macro_hard u_rob15 (.en(en), .out(out[15]));
endmodule
`default_nettype wire
