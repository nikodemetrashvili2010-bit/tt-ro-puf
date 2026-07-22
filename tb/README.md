# Testbenches

Self-checking Verilog testbenches for the three levels of the production
dual-arm design in `src/`.
`tb_ro_puf_core.v` drives the measurement core, `tb_ro_puf.v` drives the
two-arm PUF with its oscillator bank, and `tb_tt_um_ro_puf.v` drives the full
TinyTapeout wrapper. They exercise every available selector, verify the exact
measurement-window length, check the hardened-arm enable is one-hot, and exit
nonzero through `$fatal` on a failure, unknown count, or timeout.

From the repository root, `make` runs the two-arm test, `make tt` runs the
wrapper, `make core` runs the core, and `make check` runs all three. They use
Icarus Verilog and behavioral models for both physical oscillator variants,
since their real feedback loops require extracted-delay simulation.
