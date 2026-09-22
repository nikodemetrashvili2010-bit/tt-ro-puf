# Signoff status

What has been run against the design, and what came back. This is my own
checking. It is not a foundry signoff.

Since 21 September this file is about the release build: run 83's three-arm
build, archived in `dualarm/build_armc/`, which is the GDS going to the
shuttle. Until then it described the two-arm build in `dualarm/build_current/`
as if that were the chip, and it is not any more. That build stays in the
repository, frozen, as the baseline the paper measured. Its rows are in their
own table further down, with a column for whether each result still holds.

Nearly every row points at archived flow output or at logs a script reads,
and where the logs were not kept the row says so.
`sim/spice/gono/verify_build_bundle.py` checks that a build folder holds one
flow run and not a mixture. It exists because `dualarm/build_current` once
carried a stale metrics file, real and clean checks that belonged to the build
before the counter-gating change, 123 instances smaller. Two warning counts
quoted from it were wrong: max slew 171 where the build had 140, and max
capacitance 3 where it had none. Rebuilding from the source gave a DEF and a
netlist byte for byte identical to the archived ones.

## The release build

| Item | Status | Evidence | Blocks tapeout? |
|---|---|---|---|
| Three-arm build, run 83 | Magic DRC 0, KLayout DRC 0, XOR 0, LVS 0, antenna 0 after 10 diodes, route DRC 0, power grid 0 on both rails, no setup or hold violation at any of nine corners; precheck and the gate-level test green on the same run | `dualarm/build_armc/`, run 83 on `8f8939a` | no |
| Archived bundle is one flow run | 8 of 8 agree, 6218 instances in the DEF, the netlist and the metrics | `verify_build_bundle.py --dir dualarm/build_armc` | no |
| Rings survive place and route | 32 of 32, Arm A and Arm C, each a NAND, 30 inverters and the tap buffer with nothing else on the loop | `verify_ring_topology.py --arms AC`, on the archive and on every CI build | no |
| Placement held | Arm A 512 of 512 cells at the baseline's coordinates and orientations; Arm C 512 of 512 where its template put them, none moved, turned or resized | `placement_fidelity.py`, `gen_armc_fix.py --verify-def` | no |
| Frequency across PVT corners, Arm A | all sixteen start at ss, tt and ff: 275.4 to 291.3, 538.4 to 570.0 and 837.2 to 887.2 MHz, 5.63%, 5.73% and 5.83% peak to peak, bits `11100000` at all three | the six decks and their logs in `build_armc/`, `verify_predictability.py` | no |
| Frequency across PVT corners, Arm C | all sixteen start at ss, tt and ff: 291.4 to 297.6, 570.9 to 583.4 and 891.2 to 911.1 MHz lumped, 2.12%, 2.17% and 2.21%, bits `11010110` at all three | `sim/spice/gono/rc3/`, `rc_validation_armc.csv` | no |
| Counter range | the fastest ring on the chip is Arm C's ring 10 at ff, and it reads 37318 of 65535 at the 2048-cycle window and 50 MHz; a wrap would latch `uio[4]` rather than pass as a reading | `verify_datasheet.py` | no |
| Lumped capacitance against the full RC network | Arm A widens from 5.75% to 5.88%, every ring 0.67% to 1.67% slower, rank correlation 0.965; Arm C 2.17% to 2.19%, rank correlation 0.906; no pair bit reverses in either arm | `rc_validation_3arm.csv` and `rc_validation_armc.csv`, logs in `sim/spice/gono/rc3/`, both tables regenerated in CI | no |
| 48-to-1 selector at the fast corner | all 48 paths carry every edge, 30 of 30 matched and 15 flop rises on each, 48 blocked controls silent; rise delay 174 to 349 ps; every path lengthens its high level by 90 to 209 ps and shortens its low by the same, period preserved | `sim/spice/gono/mux3/`, `mux3_validation.csv`, regenerated in CI | no |
| Boundary pulse through the selector | B13, the slowest rise of the 48, at ff: 38 enable-fall phases 50 ps apart, every one settles to a rail and the count steps by at most one; the last edge is lost on 2 of them | `boundary_validation_B13_3arm.csv`, raw logs not archived | no |
| Fine boundary sweep | not run on this build; the 50 ps grid only places B13's step somewhere between 68 and 104 ps at the tap, and no other path was swept at the boundary | `docs/phaseG_g3_extract.md` | before final trust |
| Flow warning classes | 14 of 14 derived counts agree with `metrics.json`, each class named per net or shown to be a flow constant; notes below | `triage_warnings.py --build dualarm/build_armc` | no |
| Heat, wire current, supply drop, taps | 20 of 20 checks, 8 planted faults caught: a running ring 0.23 mW at tt and 0.40 mW at ff, under 0.2 K of self-heating, the busiest ring wire 13 times under the tech LEF's RMS current limit, the supply at most 0.58 mV down under a ring with no bit changed, every tap where the baseline had it | `real_world.py`, decks and logs in `sim/spice/gono/real_world/`, `docs/phaseG_realworld.md` | no |
| Drawn spacing, checked a second way | KLayout width and space on li1 to met4, no failures, the smallest gaps equal to the rule | `real_world/space_width.py` and its output; needs KLayout, so not in the gate | no |
| Arm B on this build's routes | not run; the sixteen instances have only been run with the baseline's top-level routes, see the table below | - | no |
| Silicon measurements | chips not fabricated | - | next phase |

## The two-arm baseline

| Item | Status | Evidence | Still holds for the release build? |
|---|---|---|---|
| Two-arm build | Magic DRC 0, KLayout DRC 0, XOR 0, LVS 0, antenna 0, route DRC 0, power grid 0 on both rails, no setup or hold violations; frozen and hashed, not submitted | `dualarm/build_current/` | no, a different GDS with its own row above |
| Archived bundle is one flow run | 8 of 8 agree | `verify_build_bundle.py` | no, same reason |
| Counter clocking at the ring boundary | 38 enable-fall phases at tt and at ff through a real `dfrtp_2`, each settles to a rail and the count moves by at most one edge; the ff sweep repeated on 17 September on another machine, 38 of 38 | `gen_flop_sweep.py`, `analyze_flop_sweep.py`, sweep logs not archived | yes, the ring, the flop and the counter are the same circuit |
| Frequency across PVT corners, Arm A | 5.46%, 5.53%, 5.56% at ss, tt and ff, bits `01101000` | `analyze_corners.py` on the logs in `build_current/` | no, pairs 0/1 and 8/9 read the other way on the release build |
| Frequency across PVT corners, Arm B | sixteen instances with their own enable and output routes, 0.0001%, 0.0025% and 0.0009% peak to peak at ss, tt and ff, far under the 0.01% written down before the runs | `armb_instances_ss_out.txt`, `armb_instances_out.txt`, `armb_instances_ff_out.txt`, `analyze_instance.py --corner` | the macro, yes; the routes were drawn again and have not been rerun |
| Lumped capacitance against distributed RC, Arm A | 5.55% to 5.84%, rank correlation 0.994, no pair bit reverses; re-simulated 2026-07-30 after the coupling capacitors were found double counted, repeated 17 September | `rc_validation.csv`, raw logs not archived | no, replaced by the release build's row |
| Placement sensitivity | nine builds, median 5.75%, range 4.19% to 6.99% | `dualarm/placement_sweep/` | as context; Arm A's placement is the same in both builds |
| Hardened Arm B macro | recorded checks clean, bundle 8 of 8 | `macro/romacro_final/` | yes, the same macro |
| Arm B macro against its distributed RC network | 566.05 MHz against 570.62 lumped, a shift of -0.801%, 0.32 sigma from what the Arm A load fit predicts for a ring of its weight | `gen_macro_rc_deck.py`, `analyze_macro_rc.py`, logs in `sim/spice/gono/macrorc/` | yes, nothing inside the macro changed |
| Standalone 16-copy array | clean apart from one max-slew violation at the slow corner, bundle 8 of 8 | `array/pdnfix4_final/` | component evidence only |
| 32-to-1 selector at the fast corner | all 32 paths carry every edge, 32 blocked controls silent, rise delay 157 to 375 ps, high level lengthened by 102 to 182 ps, period preserved | `mux_validation.csv`, logs in `sim/spice/gono/mux/` | no, the selector is 48 to 1 now |
| Boundary pulse through the selector | 252 phases over seven sweeps, every one settles to a rail and the count steps by at most one; the narrowest clock delivered is 80 ps on B00, against the 77.5 ps the library gives at a 10 ps clock slew; repeated 17 September, identical column for column | seven `boundary_validation_*.csv`, `check_pulse_width.py`, raw logs not archived | the behaviour, yes, and 80 ps is still the working figure; the paths, no |
| Supply resistance confound | series resistance swept over four decades in both arms; at the layout's own 7.81 and 4.32 ohm the arms differ by 0.0348% of frequency, 168 times under Arm A's dispersion | `gen_supply_decks.py`, `analyze_supply.py`, logs in `sim/spice/gono/supply/` | the method, yes; the two resistances are the baseline's, and the release build's supply drop is in the physical checks above |
| Flow warning classes | all six named per net or shown to be flow constants; 14 of 14 here and 13 of 13 on a control build that answers differently | `triage_warnings.py`, `triage_warnings.json`, `docs/warning_triage.md` | the classes, yes; the counts are the release build's own |
| Earlier dual-arm snapshot | mixed checkpoints, not a usable bundle | `dualarm/build_debug/` | no |

## Notes per artifact

**dualarm/build_armc/** is the build I intend to submit. Run 83 on commit
`8f8939a`, the first on LibreLane 3.0.14 under the `ttsky26d` tag and the first
with Arm C placed. The folder was filled from that job's artifacts on 18
September, G.3 step 10: DEF, netlist, nominal SPEF, GDS, `metrics.json`,
`commit_id.json`, and the six Arm A decks `gen_dualarm_decks.py` builds from
them, with their logs. Unlike the baseline's, its `commit_id.json` names a
commit in this repository and the workflow run that built it.

It places 6218 instances. 1726 are logic cells, and 1024 of those are the
rings of Arms A and C. Then the 16 Arm B macros, 419 well taps, 10 antenna
diodes and 4047 fill and decap cells.

Against the baseline, Arm A's cells did not move. The XOR of the two GDS files
inside the 512 Arm A cell footprints is identical on every layer that belongs
to the cells and different on the layers the router owns, so for Arm A the
difference between the builds is wire. The die around it did change, Arm C's
512 cells and a bigger selector among other things, and the router answered
with new paths. That was enough to move one ring's loop capacitance by 3.4 fF
and flip two of Arm A's eight bits, which is why every number in the first
table was read from this build and nothing was carried over.

The run raises the warning classes a free-running ring and a black-boxed macro
always raise under conventional static timing: 473 lint warnings and no lint
error, 291 max-slew violations at the worst slow corner, fewer at tt and none
at ff, two max-capacitance violations at ss, one max-fanout, two floating
timing nets, five disconnected pins with none critical, and 23 unannotated
timing nets per corner.

The 291 are on 30 nets, and every one of the 30 is driven by a
`clkdlybuf4s25_1` that placement repair put in to split a fanout above 10. The
baseline had 37 of those buffers and 140 violations; this build has 58 and 291,
because the select decode now fans out to 48 rings instead of 32. The nets are
the select decode, the counter reset, the start pulse, the project reset and
`uio_in[1]`. All of them are quiet during a measurement. They settle in the
ST_ARM cycle, the 20 ns the state machine leaves between `start` and the
window opening, and STA at all nine corners is clean with those slews in it:
worst setup slack 9.20 ns at ss, worst hold 0.110 ns at ff. Post-route slew
repair is off in the Tiny Tapeout defaults, so the flow reports these and never
fails on them. The two max-capacitance violations sit on two of the same
buffers, 4% and 1% over the 94 fF limit, ss only.

The max-fanout violation is `clknet_0_clk` at 16 against a limit of 10, the
clock-tree root. The floating nets are `VPWR` and `VGND`, the same two every
archived build reports. The five disconnected pins are `uio_in[0]` and
`uio_in[4]` to `uio_in[7]`: bits 0, 4 and 5 are outputs, so their input
halves have no use, and 6 and 7 are spare. The baseline had nine, `ui_in[7]`
and all eight of `uio_in`, before the second arm-select bit took `ui_in[7]` and
the window and version inputs took `uio_in[1:3]`. No ring net is near the heavy
end: the 992 ring nets of Arms A and C carry at most 1.849 fF, against 74.66 fF
on the clock root. `triage_warnings.py` derives all of it from the DEF, the
SPEF and the netlist and fails if a number disagrees with `metrics.json`.

**dualarm/build_current/** is the two-arm baseline. One flow run on the source
as it stood before the third arm, with KLayout DRC and XOR switched on next to
Magic, LVS, antenna and the power grid, all zero, and 6477 instances. It was
the build I meant to submit until the design grew Arm C. The paper's numbers
come from its SPEF, the release manifest hashes its raw files and the gate
checks those hashes, and several gate scripts read it as the two-arm
reference, so it cannot change without the gate going red.

Its warnings are the same classes at different counts, triaged in
`docs/warning_triage.md`: 461 lint warnings, 140 max-slew violations at the
worst corner, one max-fanout, two floating nets and nine disconnected pins,
`ui_in[7]` and `uio_in[7:0]`. Its `commit_id.json` names a commit in my local
build clone, not in this repository, so read it as a note rather than a link.

**macro/romacro_final/** is the hardened oscillator macro: GDS, LEF, DEF, both
netlists, SPEF, Liberty, SDF, extracted SPICE, tool views, a render and metrics,
every recorded check clean and the bundle internally consistent. Both builds
use it unchanged. The exact PDK commit of that run was not recorded. Clean
timing reports also say nothing about whether a ring oscillates, which is what
the SPICE work is for.

**array/pdnfix4_final/** is the standalone 16-copy array. One max-slew violation
at the slow corner, documented rather than hidden, everything else clean.
`array/met4only_debug/` holds PDN debugging leftovers whose metrics file and DEF
come from different checkpoints, so it is not a bundle and is not treated as one.

**dualarm/build_debug/** is an older snapshot kept for contrast, and the bundle
check shows why it cannot be quoted. Its DEF is a pre-fill checkpoint with 1320
components while its netlist and metrics both describe a finished 7319-instance
build, and 51 clock-tree nets in its SPEF do not exist in that DEF at all.

It also predates KLayout DRC and XOR being enabled. The 5.4% dispersion derived
from it stays in the paper as a prior run, not as a result of this design.

## What is left

In the order I care about them.

The fine boundary sweep on the release build. B13's coarse sweep says every
phase resolves and the count moves by one at most, and that is the claim that
matters. What it cannot say is where the step sits, only that it is somewhere
between 68 and 104 ps at the tap, or how narrow the pulse gets right at it. On
the baseline that pulse was 80 ps, on B00, and the fine sweeps that found it
are the model for this one.

About the 80 ps. An earlier version of this file called it a 2.5 ps margin over
the 77.5 ps the library characterizes for `dfrtp_2` at ff_n40C_1v95. I read the
liberty table on 17 September: 77.5 ps is the figure at a 10 ps clock slew, and
it climbs to 833 ps at a 500 ps slew. At any realistic slew the pulse is under
the characterized minimum, not over it.

That does not make it a problem. It is the last pulse before a stop, the flop's
answer to it was simulated at transistor level rather than looked up, and
whichever way it resolves the count moves by one, which is what the
three-sample handshake is for. It was never a margin, and I should not have
written it as one.

Arm B's sixteen instances on the release build's routes. The macro and its
inside are the same, but every instance's enable and output routes were drawn
again, to a bigger selector. `gen_instance_decks.py` already takes the netlist
and the top-level SPEF as arguments.

The soft obstruction around Arm A. With Arm A and Arm C both fixed in place it
holds nothing, and it wants one build with only that change to show whether it
still earns its place.

Raw logs. The release build's rings, selector and physical checks keep their
logs in the repository, and CI re-derives the numbers from them. The B13
boundary sweep does not, and on the baseline neither do the distributed-RC
comparison, the flop sweep and the seven boundary sweeps. All of those
baseline ones were run again on 17 September on a different machine, with a
different ngspice and PDK install, and came back the same
([docs/phaseG_spice_rerun.md](docs/phaseG_spice_rerun.md)). A repeat, not a
check against the original logs.

The bench. None of it is in the GDS and all of it can spoil a measurement. The
preregistered box reaches 125 C, while the RP2040 on the demo board is rated to
85 C and makes the reference clock, so only the breakout can be heated.
At -40 C a cold board condenses water out of the air, and frost melting on a
powered board shorts pins. And nothing in the repository says yet how the core
supply gets set to 1.62 and 1.98 V and measured at the chip.

Last is silicon. Uniqueness, reliability and any attack claim need measured dies
at several supply voltages and temperatures. Until those exist this is a
pre-silicon prototype with a clean, reproducible build behind it.
