// Blackbox declaration of the hardened oscillator macro for the array's
// synthesis. Ports only; the real physical/gate views come from the GDS/LEF/nl
// supplied via MACROS in config.json.
`default_nettype none
(* blackbox *)
module ro_macro_hard (
    input  wire en,
    output wire out
);
endmodule
`default_nettype wire
