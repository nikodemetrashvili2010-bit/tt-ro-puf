# Signoff status

What has been run against the design, and what came back. This is my own
checking. It is not a foundry signoff.

Every row below points at a folder of archived flow output. Those folders are now
checked by `sim/spice/gono/verify_build_bundle.py`, which rejects a bundle whose
DEF, netlist, SPEF and metrics did not come from one run. I wrote it after
finding a stale metrics file in `dualarm/build_current`. Its checks were real and
clean, but they belonged to the build before the counter-gating change, and that
build had 123 fewer instances than the layout I am submitting. Two of the warning
counts quoted below came from it and were wrong: max slew was 171 across corners
when the real build has 140, and max capacitance was 3 when the real build has
none.

The repair was to rebuild from the current source. That run returned a DEF and a
gate-level netlist byte for byte identical to the archived ones, so the flow
reproduces this layout exactly. GDS and SPEF differ only in the creation date
each carries inside it, and both kept the same length.

| Item | Status | Evidence | Blocks tapeout? |
|---|---|---|---|
| Dual-arm build from the current source | Magic DRC 0, KLayout DRC 0, XOR 0, LVS 0, antenna 0, route DRC 0, power grid 0 on both rails, no setup or hold violations | `dualarm/build_current/` | no |
| Archived bundle is one flow run | 8 of 8 agree | `verify_build_bundle.py` | no |
| Arm A rings survive place and route | 16 of 16 intact, nothing inserted in a loop | `verify_ring_topology.py` | no |
| Counter clocking at the ring boundary | 38 enable-fall phases at tt and at ff, each settles to a rail, count moves by at most one edge | `gen_flop_sweep.py`, `analyze_flop_sweep.py`, sweep logs not archived | no |
| Frequency across PVT corners | every ring starts at ss, tt and ff; dispersion 5.46%, 5.53%, 5.56%; worst count 35532 of 65535 | `analyze_corners.py` on the logs in `build_current/` | no |
| Lumped capacitance against distributed RC | dispersion widens from 5.55% to 5.84%, rank correlation 0.994, no pair bit reverses; re-simulated 2026-07-30 after the coupling capacitors were found to be double counted | `rc_validation.csv`, raw logs not archived | no |
| Placement sensitivity | nine builds, median 5.75%, range 4.19% to 6.99% | `dualarm/placement_sweep/` | no |
| Hardened Arm B macro | recorded checks clean, bundle 8 of 8 | `macro/romacro_final/` | no |
| Standalone 16-copy array | clean apart from one max-slew violation at the slow corner, bundle 8 of 8 | `array/pdnfix4_final/` | no |
| Earlier dual-arm snapshot | mixed checkpoints, not a usable bundle | `dualarm/build_debug/` | informational |
| 32-to-1 selector path at the fast corner | all 32 paths carry every edge into the flop, 32 blocked controls silent, rise delay 157 to 375 ps, every path lengthens its high level by 102 to 182 ps and shortens its low by the same, period preserved at both nodes | `mux_validation.csv`, `gen_mux_sweep.py`, `analyze_mux_sweep.py`, raw logs not archived | no |
| Boundary pulse measured through the selector | 252 phases over seven sweeps, three paths at ff plus B15 repeated at tt and ss, every one settles to a rail and the count steps by at most one; the narrowest clock any of them delivered is 80 ps on B00, against the 77.5 ps the library characterizes at that corner | seven `boundary_validation_*.csv`, `check_pulse_width.py`, raw logs not archived | no |
| Boundary through the other 29 selector paths | not simulated; every one of them carries all 30 judged edges in the item 2 sweep, but none was swept at the stopping boundary | `docs/hardware_todo.md` item 1 | before final trust |
| Arm B per-instance integration | sixteen instances carrying their own real enable and output routes spread 0.0025% peak to peak, which is 0.57 of one counter count, against 5.84% for Arm A on the same build; 37 of 37 checks re-derived by separate code | `armb_instances_out.txt`, `instance_parasitics.csv`, `verify_instance.py` | no |
| Supply resistance confound | series resistance swept over four decades in both arms; at the layout's own 7.81 and 4.32 ohm the arms differ by 0.0348% of frequency, 168 times under Arm A's dispersion, with Ohm's law closing at every point and the implied pushing figure reproducing the independent 105.9 percent per volt | `gen_supply_decks.py`, `analyze_supply.py`, logs in `sim/spice/gono/supply/` | no |
| Silicon measurements | chips not fabricated | - | next phase |

## Notes per artifact

**dualarm/build_current/** is the build I intend to submit. One flow run on the
current source with KLayout DRC and XOR switched on next to Magic, LVS, antenna
and the power grid, all zero. It places 6477 instances, of which 1496 are
standard cells and 16 are the Arm B macro, and the rest are fill, decap, well
taps and antenna diodes. The go/no-go analysis in `sim/spice/gono/` reads this
folder's SPEF, and the render in the README comes from it. The run also wrote
`commit_id.json`, which pins the Tiny Tapeout tooling it used. The commit hash in
that file belongs to my local build clone, not to this repository, so treat it as
a note to myself rather than a link.

The same run carries the warning classes that a free-running ring and a
black-boxed macro always raise under conventional static timing analysis: 461
lint warnings with no lint error, 140 max-slew violations across corners, one
max-fanout violation, two floating timing nets, nine disconnected pins, none of
them critical, and 25 unannotated timing nets per corner. Max capacitance is
clean. None of these is a routing or connectivity failure, but each class still
needs per-net triage against the timing reports before I order silicon. The
transitive tool versions are not pinned; the environment is described in
REPRODUCIBILITY.

**macro/romacro_final/** is the hardened oscillator macro: GDS, LEF, DEF, both
netlists, SPEF, Liberty, SDF, extracted SPICE, tool views, a render and metrics,
every recorded check clean and the bundle internally consistent. The exact PDK
commit of that run was not recorded. Clean timing reports also say nothing about
whether a ring oscillates, which is what the SPICE work is for.

**array/pdnfix4_final/** is the standalone 16-copy array. One max-slew violation
at the slow corner, documented rather than hidden, everything else clean.
`array/met4only_debug/` holds PDN debugging leftovers whose metrics file and DEF
come from different checkpoints, so it is not a bundle and is not treated as one.

**dualarm/build_debug/** is an older snapshot kept for contrast, and the bundle
check shows why it cannot be quoted. Its DEF is a pre-fill checkpoint with 1320
components while its netlist and metrics both describe a finished 7319-instance
build, and 51 clock-tree nets in its SPEF do not exist in that DEF at all. It
also predates KLayout DRC and XOR being enabled. The 5.4% dispersion derived from
it stays in the paper as a prior run, not as a result of this design.

## What is left

In the order I care about them.

The gap the selector left is closed, and then some. The boundary sweep runs with
the real selector cells in the path, on B15 which is the deepest and slowest, on
A05 which adds the least width, and on B00 which turned out to be the strict one,
plus B15 again at tt and at ss. That is 252 phases over seven sweeps and every
one of them resolved the flop to a clean rail. The chain behaves as a filter:
below a threshold at the tap it passes nothing at all, above it a full pulse, and
the threshold sits between nine and eleven percent of the ring period at every
corner measured.

One number in an earlier version of this file was wrong. It said the narrowest
clock the flop ever saw was 144 ps. Right at its own threshold B00 hands the flop
80 ps, because at the boundary the chain squeezes the last pulse instead of
lengthening it, which is the one place item 2's corrected result stops applying.
80 ps clears what the library characterizes for that flop at that corner, 77.5 ps
at ff_n40C_1v95, by 2.5 ps. Characterized, and marginal. The slow corners are not
close, 484 ps against 169.8 at tt and 810 ps against 353.8 at ss.

Getting there meant correcting item 2, and that correction is the part I would
want a reader to see. Its headline, that the selector shortens levels by up to
25%, came from comparing the narrowest level at the tap against the narrowest at
sel_ro, and those are opposite polarities. No path shortens a high level. Every
one lengthens it. `docs/hardware_todo.md` has the full account.

Item 8 answered its own question. The sixteen Arm B copies carrying their real
routes spread 0.0025 percent, which is 0.57 of one counter count, so the chip
cannot tell them apart even in principle. Item 5 closed the supply confound the
same week, with the arms differing by 0.0348 percent at the resistances the
layout actually has. What is next is not a simulation. It is the Arm B macro's
distributed re-extraction, the per-net triage of the flow's warning classes, and
the decision on item 10.

Second, several sweep results have no raw logs in the repository. The
distributed-RC comparison, the boundary flop sweep, the selector sweep and all
seven boundary sweeps through the selector were run in `/tmp`, and only their
derived numbers survive. The per-instance run and the supply sweep are the
exceptions, and both keep their logs, which is the pattern I want the rest to
follow. Each leaves a csv behind, so a stranger with a clone can read the
numbers, but none can be recomputed without rerunning ngspice. The decks are
deterministic and regenerate byte for byte, so archiving the logs is mechanical
work I owe rather than anything difficult.

Last is silicon. Uniqueness, reliability and any attack claim need measured dies
at several supply voltages and temperatures. Until those exist this is a
pre-silicon prototype with a clean, reproducible build behind it.
