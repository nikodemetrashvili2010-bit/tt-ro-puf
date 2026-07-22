# Production cocotb test

This directory tests the dual-arm TinyTapeout source set in `../src`.
Behavioral oscillator models replace the two physical feedback-loop
implementations during RTL simulation.

The test exercises all 32 selectors, both output bytes, the exact 1000-cycle
measurement window, Arm-B one-hot enables, stable latched controls, held-start
behavior, in-flight restart, reset recovery, asynchronous `ena` shutdown, and
clock-synchronized reset release.
When the hard-macro instances remain visible after synthesis, the test reads
their actual enable pins so selector-to-instance permutations cannot hide
behind identical oscillator models. Assertions produce a nonzero test exit.

## Run

Install the pinned Python dependencies and Icarus Verilog, then run:

```sh
python -m pip install -r requirements.txt
make clean
make
```

The default RTL run writes `results.xml` and `tb.fst`.

Gate-level simulation is normally launched by the TinyTapeout GDS workflow.
For a local run, copy the generated top-level netlist to
`gate_level_netlist.v`, set `PDK_ROOT`, and run:

```sh
make clean
make GATES=yes
```

The generated top-level netlist preserves `ro_macro_hard` as a physical
black box, so the gate-level target supplies the parameterless functional
model in `ro_macro_hard_sim.v` at that boundary.
