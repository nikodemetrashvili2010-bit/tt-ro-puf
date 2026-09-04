# Production cocotb test

This directory tests the three-arm TinyTapeout source set in `../src`.
Behavioral oscillator models replace the three physical feedback-loop
implementations during RTL simulation: `ro_macro_sim.v` for Arm A,
`ro_armc_sim.v` for Arm C and `ro_macro_hard_sim.v` for Arm B.

Two modules. `test.py` is the protocol regression and `test_e2.py` is the
E.2 acceptance table, twenty-one rows read out of `../chip/e2_tb_plan.csv`
and worked one at a time. `make` runs the first, `make E2=yes` the second.

The regression exercises all 48 selectors, both output bytes, the measurement
window against the length the select bits ask for, the `active` pin against
the internal window signal, Arm-B one-hot enables, stable latched controls,
held-start behavior, in-flight restart, reset recovery, asynchronous `ena`
shutdown, and clock-synchronized reset release. It runs on the 256-cycle
window because it takes 48 measurements; the longer windows are exercised one
ring at a time in `test_e2.py`.

That count is the RTL run. The gate-level run covers **Arm B only, so sixteen
of the forty-eight**, because `GATES=yes` sets `ARMS = (1,)` in `test.py` and
moves the protocol tests onto arm 1 with it. Arm A is a zero-delay feedback
loop in a gate-level netlist, because sky130 gives its combinational cells no
delay in either view it ships, so enabling an Arm A ring there advances no
simulated time and the run never finishes. Arm C is the same circuit under its
own module name and is in exactly the same position. Those thirty-two
selectors are covered in RTL, and their frequencies are checked against SPICE
rather than against a gate-level simulation. The comment above `GL` in
`test.py` has the full account, `verify_ring_topology.py` checks Arm A's ring
structure against the same netlist this test elaborates, and `lint_rtl.py` R08
checks that Arm C is that ring node for node.

`test_e2.py` is RTL only for the same reason. Two of its rows sweep the
auto-placed arms, so a `GATES=yes` run of the table would hang rather than
fail.
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

The default RTL run writes `results.xml` and `tb.fst`. `make E2=yes` writes
the same two files from the acceptance table instead. `make clean` between
them; the two share a build directory.

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
