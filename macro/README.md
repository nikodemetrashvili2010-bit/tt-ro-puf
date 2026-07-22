# The hardened oscillator macro

Arm B is built from one oscillator hardened into a fixed piece of layout, then
stamped down as identical copies. This folder is that one macro.

`ro_macro.v` is the oscillator and `ro_macro_hard.v` is the wrapper that gets
hardened. `config.json` is the LibreLane configuration that hardens it as a
plain macro, with power pins on met4 and no clock. `romacro_final/` is the
complete archived build bundle: GDS, LEF, netlists, extracted SPEF, timing
libraries, SDF, SPICE, and render views. Its archived metrics report zero final
route DRC, Magic DRC, KLayout DRC, XOR, LVS, antenna, power-grid,
disconnected-pin, max-slew, and max-fanout violations. These are flow reports
for the archived tool/PDK environment, not independent foundry signoff; exact
provenance and limitations are summarized in `../SIGNOFF.md`.

Because every Arm B instance uses the same hardened GDS, its internal geometry
is identical by construction. Top-level loading, local mismatch, power, and
environment may still differ between instances. The nominal lumped-C model
predicts 569.5 MHz, close to the auto-placed arm's modeled mean. That number is
derived from the archived ngspice log; it is not a silicon measurement and
omits distributed RC/coupling, mismatch, and PVT.

The generated Liberty/SDF views are conventional timing-delivery artifacts for
integration. A free-running combinational ring is not a normal synchronous
timing path, so those views do not by themselves validate oscillation behavior.
