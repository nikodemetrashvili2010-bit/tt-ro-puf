# RTL modules

`ro_puf_core.v` is the legacy/reference serial RO-PUF measurement engine. It
latches the selected oscillator, runs it for an exact crystal-referenced
window, stops it, waits for the asynchronous ripple counter to settle, and
then captures a stable result.

`ro_behavioural.v` is a simulation-only ring-oscillator model with a
parameterised period. On silicon it is replaced by a hardened GDS macro.

The tapeout production sources, including the hardened Arm B macro interface,
are in `src/`. The root Makefile tests that production source set. See the
top-level README for build and simulation instructions.
