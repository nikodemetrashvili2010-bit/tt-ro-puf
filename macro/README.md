# The hardened oscillator macro

Arm B is built from one oscillator hardened into a fixed piece of layout, then
stamped down as identical copies. This folder is that one macro.

`ro_macro.v` is the oscillator and `ro_macro_hard.v` is the wrapper that gets
hardened. `config.json` is the LibreLane configuration that hardens it as a
plain macro, with power pins on met4 and no clock. `romacro_final/` is the
signed-off build: GDS, LEF, the netlist, the extracted SPEF, timing libraries
for every corner, and a render. It passes DRC, LVS and antenna.

Because every Arm B instance is the same hardened GDS, the internal ring
parasitics are identical, so there is no per-oscillator layout bias. The
matched oscillator runs at 569.5 MHz, close to the auto-placed arm's mean, so
the fix keeps the operating point.
