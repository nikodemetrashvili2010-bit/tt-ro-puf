# Signoff status

This file tracks the physical evidence: what was run, what passed, and what
still blocks the shuttle order. It is not a foundry signoff.

| Item | Status | Evidence | Blocks tapeout? |
|---|---|---|---|
| Hardened macro: Magic + KLayout DRC, LVS, XOR, antenna, power grid | pass | `macro/romacro_final/` | no |
| Standalone 16-copy array checks | pass, one max-slew violation at the slow corner | `array/pdnfix4_final/` | no |
| Archived dual-arm build | partial debug snapshot, no final GDS | `dualarm/build_debug/` | informational |
| Fresh flow run from the current RTL | not yet run | - | yes |
| KLayout DRC and XOR on the fresh build | pending | - | yes |
| Lint, slew, fanout, and pin triage on the fresh build | pending | - | yes |
| Recorded tool and PDK versions for the fresh build | pending | - | yes |
| Silicon measurements | chips not fabricated | - | next phase |

## Notes per artifact

**macro/romacro_final/** is the strongest bundle: GDS, LEF, DEF, both
netlists, SPEF, Liberty, SDF, extracted SPICE, tool views, a render, and the
metrics file, with every recorded check clean. One gap: I did not record the
exact PDK commit of that run. Clean timing reports also say nothing about
whether a ring actually oscillates; the SPICE runs cover that.

**array/pdnfix4_final/** is almost as complete. The one blemish is a single
max-slew violation at the slow corner, documented rather than hidden.
`array/met4only_debug/` holds PDN debugging diagnostics; its metrics file and
DEF come from different checkpoints, so they do not describe one final
database.

**dualarm/build_debug/** is a debug snapshot of an older RTL revision. Its
recorded checks pass (routing DRC 0, Magic DRC 0, LVS matched, antenna 0,
power grid 0), but that run had KLayout DRC and XOR switched off and left 462
lint warnings, 81 max-slew violations, one max-fanout violation, ten
disconnected pins, and 26 unannotated nets. There is no final GDS in the
bundle, and the DEF and netlist come from different stages, which is why
`dualarm_positions.csv` holds nan coordinates. Frequency numbers derived from
this snapshot describe the older source revision.

## What tapeout-ready means here

One flow run from a recorded source commit with pinned LibreLane, OpenROAD,
support-tools, and PDK versions, exporting a coherent final bundle (GDS, LEF,
final DEF, both netlists, SPEF, full metrics) with KLayout DRC and XOR
passing alongside Magic, LVS, antenna, and power grid. Every lint, slew,
fanout, and pin item fixed or waived by name; a bare count is not a waiver.
Extracted simulation then repeats from that exact build. The PUF claims
themselves wait for measured dies. Until that run lands, this project is a
pre-silicon prototype with strong macro and array evidence.
