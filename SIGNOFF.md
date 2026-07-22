# What the physical evidence shows

I keep the flow artifacts in the repo so anyone can check what was actually
run. This file is my inventory of that evidence, including the gaps. It is not
a foundry signoff, and a zero in one metric is never used to claim a check that
was not run.

## The hardened macro (macro/romacro_final/)

This is the strongest bundle. It has the GDS, LEF, DEF, powered and unpowered
netlists, SPEF, Liberty, SDF, extracted SPICE, Magic and KLayout views, a
render, and the metrics file. Every recorded check is clean: routing DRC 0,
Magic DRC 0, KLayout DRC 0, XOR 0, LVS matched, antenna 0, power grid 0, no
disconnected pins, no slew or fanout violations. Two caveats. I did not record
the exact PDK commit of the original run, so the bundle depends on an
environment I can no longer point to precisely. And clean Liberty/SDF timing
says nothing about whether a ring oscillator actually oscillates; the SPICE
runs are what cover that.

## The standalone matched array (array/pdnfix4_final/)

Same kind of bundle and almost the same result, with one exception: a single
max-slew violation at the slow corner. It is documented rather than hidden,
but it means the array is not literally violation free.

A related note on array/met4only_debug/: its metrics.json describes a
3,616-instance final run while its ro_array.def is a 409-component checkpoint.
Those files are useful diagnostics from the PDN debugging, not two exports of
one final database.

## The dual-arm chip snapshot (dualarm/build_debug/)

This is a partial debug snapshot, not a signoff package, and I want to be
plain about that. It contains the render, the Magic DRC report, the metrics,
a mid-flow DEF, a later netlist, and the nominal SPEF. The metrics show
routing DRC 0, Magic DRC 0, LVS matched, antenna 0, and power grid 0. They
also show 462 lint warnings, 81 max-slew violations, 1 max-fanout violation,
10 disconnected pins (none critical), and 26 unannotated nets, and that run
had KLayout DRC and XOR switched off. There is no final GDS in the bundle.
The DEF has 1,320 components and no placement coordinates for the Arm A
oscillators, while the netlist is from a later stage with filler cells, which
is why dualarm_positions.csv holds nan coordinates: the two files do not
describe the same database state.

A note on the render: a PNG is visual evidence only. It cannot substitute for
the GDS, the extraction database, and the machine-readable reports that
produced it.

## The RTL is newer than the snapshot

The current src/ RTL synchronizes the control inputs, latches the selector,
runs an exact measurement window, and publishes the count only after a
stability handshake. The archived dual-arm netlist is the older
implementation. So the snapshot's render, SPEF, metrics, and the frequency
numbers derived from it describe the previous source revision, not this one.
A fresh flow run from the current source is required before ordering silicon,
and that run will replace this snapshot.

## What is still missing before I call it tapeout-ready

The rebuild has to start from a recorded source commit with pinned LibreLane,
OpenROAD, support-tools, and PDK versions, and it has to export one coherent
final bundle: GDS, LEF, final DEF, both netlists, SPEF, and full metrics from
the same database, with KLayout DRC and XOR enabled and passing alongside the
Magic, LVS, antenna, and power-grid checks. Every lint, slew, fanout,
disconnected-pin, and unannotated-net item needs a fix or an explicit waiver
with the instance named; a bare count is not a waiver. After that, extracted
simulation should be repeated with distributed RC and across corners, and the
PUF claims themselves can only be settled by measuring multiple dies at
several voltage and temperature points once the chips exist.

Until those steps are done, the honest description of this project is a
pre-silicon prototype with strong macro and array evidence and an incomplete
dual-arm package. Not tapeout-ready, and not silicon-validated.
