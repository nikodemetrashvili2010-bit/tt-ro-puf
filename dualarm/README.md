# The dual-arm chip

This is the chip I am submitting. Arm A is the RO-PUF built the ordinary way,
with the oscillators auto-placed by the flow. Arm B is the same circuit built
from matched macros. Both sit on one TinyTapeout tile so they see the same
process.

`src/` holds the TinyTapeout sources: the RTL, the hardened macro views, the
config, and the custom power script. `test/` is the cocotb RTL test.
`gen_dualarm.py` writes `src/config.json`, including where each macro sits and
how its power lines align. `build_debug/` is the built chip: a render, the DRC
report, the metrics, the DEF, the netlist and the extracted SPEF. `info.yaml`
is the tile configuration.

The repository root has its own `src/`, `test/` and `info.yaml`. Those are
copies of the files here, and they are what the TinyTapeout build actually uses.
