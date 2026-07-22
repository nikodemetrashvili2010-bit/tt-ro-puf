# The dual-arm chip

This directory is the dual-arm integration candidate. Arm A is the RO-PUF built the ordinary way,
with the oscillators auto-placed by the flow. Arm B is the same circuit built
from matched macros. Both sit in one TinyTapeout 2x2 allocation so they share
the same die and process conditions.

`src/` holds the TinyTapeout sources: the RTL, the hardened macro views, the
config, and the custom power script. `test/` is the cocotb RTL test.
`gen_dualarm.py` writes `src/config.json`, including where each macro sits and
how its power lines align. `build_debug/` is a partial, mixed-stage diagnostic
snapshot: render, Magic DRC report, metrics, checkpoint DEF, later netlist, and
nominal SPEF. It does **not** contain a final GDS/LEF/SDF/Liberty bundle or
KLayout results. The archived run had KLayout XOR and DRC disabled; the current
configuration enables both for the required fresh build. The old metrics also
record 462 lint warnings, 81 max-slew violations,
one max-fanout violation, 10 noncritical disconnected pins, and 26 unannotated
nets. Zero route/Magic DRC, LVS, antenna, and power-grid counts do not erase
those gaps. See `../SIGNOFF.md` before making tapeout or signoff claims.

The checkpoint DEF contains 1,320 components and does not represent all
later-netlist placement detail; for example, Arm A placement extraction yields
missing coordinates. Do not join it to later netlists/SPEF as though all files
were exported from one final database. `info.yaml` is the tile configuration.

The repository root has its own `src/`, `test/` and `info.yaml`. Those are
copies of the files here, and they are what the TinyTapeout build actually uses.
