# RTL modules

`ro_puf_core.v` is the serial RO-PUF measurement engine: oscillator bank,
shared selector, crystal-referenced window timer, and asynchronous ripple
counter.

`ro_behavioural.v` is a simulation-only ring-oscillator model with a
parameterised period. On silicon it is replaced by a hardened GDS macro.

See the top-level README for build and simulation instructions.
