// Blackbox declaration of the hardened oscillator macro, for synthesis and
// lint. Ports only, NO parameters (a parameterized blackbox would be
// uniquified by yosys and break the MACROS instance-name matching). The real
// physical/gate views come from the GDS/LEF/nl supplied via MACROS in
// config.json.
`default_nettype none
(* blackbox *)
module ro_macro_hard (
    input  wire en,
    output wire out
);
endmodule
`default_nettype wire
