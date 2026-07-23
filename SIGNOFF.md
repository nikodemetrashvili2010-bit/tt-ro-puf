# Signoff status

This file tracks the physical evidence: what was run and what passed. The
current design now has a coherent clean build from the current RTL; what
mainly remains is silicon. It is not a foundry signoff.

| Item | Status | Evidence | Blocks tapeout? |
|---|---|---|---|
| Coherent dual-arm build from current RTL | pass: Magic DRC, KLayout DRC, XOR, LVS, antenna, power grid all 0 | `dualarm/build_current/` | no |
| Hardened macro: Magic + KLayout DRC, LVS, XOR, antenna, power grid | pass | `macro/romacro_final/` | no |
| Standalone 16-copy array checks | pass, one max-slew violation at the slow corner | `array/pdnfix4_final/` | no |
| Earlier dual-arm snapshot | partial debug snapshot, older RTL | `dualarm/build_debug/` | informational |
| Ripple-counter interface timing across corners | behavioural only so far | - | before final trust |
| Silicon measurements | chips not fabricated | - | next phase |

## Notes per artifact

**dualarm/build_current/** is the coherent signed-off build. It comes from
one flow run on the current hardened RTL with KLayout DRC and XOR enabled,
and every sign-off check is clean: Magic DRC 0, KLayout DRC 0, KLayout XOR 0,
LVS 0, antenna 0, power grid 0 on both rails. The GDS, final DEF, nominal
SPEF, and metrics all come from that one run, and the go/no-go analysis in
`sim/spice/gono/` reads its parasitics. The build also carries the warning
classes a free-running ring oscillator and a black-boxed macro always raise
under conventional STA: 461 lint warnings, up to 171 max-slew and 3 max-cap
violations across corners, one max-fanout violation, two floating timing nets,
nine disconnected pins (none critical), and 25 unannotated timing nets per
corner. These are expected for asynchronous ring structures and unused
outputs, not detailed-route or connectivity failures, but each class still
needs per-net triage from the timing reports before final tapeout. I did not
pin every transitive tool version; the build environment is recorded in
REPRODUCIBILITY.

**macro/romacro_final/** is the hardened oscillator macro bundle: GDS, LEF,
DEF, both netlists, SPEF, Liberty, SDF, extracted SPICE, tool views, a
render, and metrics, with every recorded check clean. One gap: I did not
record the exact PDK commit of that run. Clean timing reports also say
nothing about whether a ring actually oscillates; the SPICE runs cover that.

**array/pdnfix4_final/** is the standalone 16-copy array, almost as complete.
The one blemish is a single max-slew violation at the slow corner, documented
rather than hidden. `array/met4only_debug/` holds PDN debugging diagnostics;
its metrics file and DEF come from different checkpoints, so they do not
describe one final database.

**dualarm/build_debug/** is an earlier debug snapshot of an older RTL
revision, kept for contrast. Its recorded checks pass, but that run had
KLayout DRC and XOR switched off and left lint, slew, and pin warnings, and
it has no final GDS. The coherent build above supersedes it; the 5.4% number
derived from it is now a prior data point, not the headline.

## What is left

The coherent flow this project needed has run. One build from the current
source, with KLayout DRC and XOR passing next to Magic, LVS, antenna, and power
grid, and the go/no-go regenerated from that same build. Two things are still
open. The oscillator-to-counter interface, where the ripple counter is clocked
by the ring itself, is checked only in behavioural simulation, so its fast-corner
timing is not yet proven. And the PUF claims come last: uniqueness, reliability,
and any attack need measured dies at several voltage and temperature points, not
a simulation. Until then this is a pre-silicon prototype with a clean coherent
build behind it.
