# Simulations

Two kinds of work sit here. The Python files at this level are architectural
models that need no external tools. The SPICE work is under `spice/`.

`ref_model.py` reproduces the measurement core in plain Python and checks the
architecture when no Verilog simulator is around. `montecarlo.py` models many
chips and measures how far apart two chips' keys are on average, where the
ideal for a PUF is one half. `h3_audit.py` plays an attacker who knows only an
oscillator's position and tries to predict a chip's key. `ro_macro_sim.v` is a
simulation-only oscillator model.

The two Python chip models are parametric. They show the mechanism with assumed
spread and mismatch numbers, not silicon measurements, and the paper presents
them that way.

`spice/gono/` is a nominal lumped-capacitance experiment on routed-layout
artifacts. `spice/mc/` is a first-order mismatch-sensitivity study. Neither is
a silicon measurement or an entropy/reliability validation; the exact modeled
scope and omitted effects are stated in each subdirectory README.
