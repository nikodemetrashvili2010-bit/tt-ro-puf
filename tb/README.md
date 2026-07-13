# Testbenches

Self-checking Verilog testbenches for the three levels of the design.
`tb_ro_puf_core.v` drives the measurement core, `tb_ro_puf.v` drives the
two-arm PUF with its oscillator bank, and `tb_tt_um_ro_puf.v` drives the full
TinyTapeout wrapper. Each one checks the oscillator counts itself and reports
pass or fail.

From the repository root, `make` runs the two-arm test, `make tt` runs the
wrapper, and `make core` runs the core. They use Icarus Verilog and the
behavioural oscillator model, since the real macro is a logic loop that an
event simulator cannot run.
