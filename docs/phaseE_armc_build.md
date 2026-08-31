# Phase E.1c: where the sixteen Arm C rings go

`chip/gen_armc.py`, `chip/ARMC_REGIONS.json`, `chip/armc_place.tcl`,
`chip/ro_armc.v`. Written 2026-08-30.

G.2 chose Arm C and froze the criterion it has to meet: every ring in an
identical region. This works out where those regions are and emits what the
build reads. `src/` is untouched.

## The three decisions, and why none of them is a preference

**The region is 25.76 by 10.88 um**, 56 sites by 4 rows, 280.2688 um2.

That size is not chosen for tidiness. A region holds one ring, 120.1152 um2
of cells, and is charged in full whether the cells fill it or not, so its size
sets Arm C's density. The width picked is the integer number of sites whose
density lands closest to **0.4276, the mean density an unconstrained placer
already reached on Arm A**. It comes out at 0.42857, which is 0.23 percent
away.

That matters more than it looks. If Arm C's regions were tighter or looser
than Arm A's placements, the treatment would be two things at once,
uniformity and density, and a frequency difference could not be attributed to
either. The experiment is about uniformity. The density is held.

**Arm A has to be pinned, all 512 cells.**

This is the part I did not expect to have to write down. E.1's own rule is to
preserve the existing two-arm result rather than sacrifice it for a third
sample. A rebuild re-places every standard cell in the design. So unless Arm
A's cells are fixed at the coordinates they already have, the Arm A on the
26d die is not the Arm A the paper measured, and the two-arm result is a
claim about a build that no longer exists.

Pinning it is legitimate rather than a fudge. Arm A's treatment is "these
cells were placed by an unconstrained flow", and that stays true of a
placement replayed from the run that produced it. What it is not is a fresh
draw from the unconstrained placer, and anybody reading a variance claim
about Arm A should know that the sixteen rings are one sample, placed once,
and not sixteen independent trials of the placer.

The consequence for this script is that **Arm A's cells, and nothing else,
block where Arm C can go**. Filler, decap, taps and all 563 control cells are
re-placed by the rebuild, so they constrain the total area and not the
position of anything.

**The sixteen are split: eight in the strip, four in each band.**

Arm A is pinned in the strip beside the macro block. Putting all of Arm C in
the bands above and below would give a clean regular lattice and would alias
the treatment with die position: every supply or temperature gradient across
the die would land squarely on the Arm A against Arm C comparison, and no
measurement could separate it from the placement constraint.

So eight Arm C regions go in the strip, the eight nearest Arm A's centroid at
273.19, 114.34 um, and the other eight go four to the lower band and four to
the upper, spread across the die's width. The position contrast is now
**inside** Arm C, where it can be measured. If the strip rings and the band
rings agree, position does not matter and the main comparison is clean. If
they differ, that difference is the correction the main comparison needs.

| ring | where | x0 um | y0 um |
|---:|---|---:|---:|
| 0 to 7 | strip | 271.40 to 301.76 | 76.16 to 163.20 |
| 8 to 11 | band_low | 2.76, 109.48, 189.52, 296.24 | 2.72 |
| 12 to 15 | band_high | 2.76, 109.48, 189.52, 296.24 | 206.72 |

Full coordinates are in `chip/ARMC_REGIONS.json`.

## How much room there was

57 places a region of that shape fits: 33 in the strip, 12 in each band. The
sixteen used take 4484.301 um2, **25.96 percent of the free row area**, well
inside the 75 percent G.2's H1 reserves.

The strip's 33 are at irregular x positions because Arm A's pinned cells
fragment it. The bands' 24 sit on an exact 26.68 um lattice, because nothing
is pinned there.

## The one thing this cannot emit

`chip/armc_place.tcl` has two halves.

The first is 512 `place_cell` lines, one per Arm A cell, with the coordinate
and orientation the DEF already records and `-status FIRM`. That is a real
OpenROAD command and the file is ready to source.

The second half is the sixteen regions, written as coordinates in a Tcl array
and **not** as a command that binds cells to them. That is deliberate. The
command that constrains a cell group to a region differs between OpenLane and
OpenROAD versions, this script has not run either of them, and writing an API
call I have not executed would be inventing evidence. The geometry is
generated and checked; the binding is one line to fill in against the flow the
build actually uses, and the log has to say all sixteen groups were
constrained.

Say that plainly rather than shipping a file that looks complete.

## The RTL, emitted and unsimulated

`chip/ro_armc.v` is Arm C's ring: an enable NAND and 30 inverters, the same
circuit as `src/ro_macro.v`, under its own module name so synthesis cannot
share cells between the arms, with `keep` attributes so the optimiser cannot
collapse a stage.

The select arithmetic the third arm forces is checked here rather than
emitted: 48 oscillators need 6 select bits, two of them the arm, four the
index. That is one more input pin than today and it is `ui[7]`, which E.1b
established is genuinely unconnected and E.2 then routed around.

None of this has been simulated. It is structure, checked as structure. The
lint, the gate-level tests and the acceptance table from E.2 all run in the
build step and are what G.3 re-verifies.

## Checks and faults

Eleven checks, all passing on the real design. Eight planted faults on the
fixture plus three that come from elsewhere, each naming the one check it
must trip.

Two are worth explaining because they were wrong first.

**A region on a pinned Arm A cell and a region between two rows are the same
fault.** The free-site table holds only sites that are both on a row and clear
of Arm A, so nothing can trip one without the other. They are one check with
two faults, the same shape as `T06` in `tile_budget.py`.

**Deciding a band row is "low" or "high" used to compare it against the bottom
of the macro block.** That made the macro-overlap fault also a quota fault,
because moving a macro moved the line. It compares against the middle of the
die now, which no macro can move.

Two checks cannot be reached from the fixture's geometry. `A09` guards the
G.2 area reserve and `A10` is arithmetic on the arm count, so each is faulted
from its own side: a free area small enough that the regions do not fit, and
a ring count the select width cannot carry. `A01` and `A11` count sixteen
rings and 512 cells, which the fixture has one and eight of, so they are
excused on the fixture by name and exercised on the real design.

## What the build does next

1. Source `chip/armc_place.tcl` after floorplanning, with the region binding
   filled in.
2. Install `chip/ro_armc.v` and the select change into `src/`, which is the
   first edit to that directory since 7 August.
3. Build.
4. Check against G.2's criterion: identical bounding boxes, identical row
   spans, densities agreeing to 0.02, Arm A and Arm B unchanged.
   `chip/tile_budget.py` measures all four.
5. Two builds. If the criterion is not met, stop and build the ladder.

## A correction this work forced upstream

Looking for somewhere to put sixteen regions meant reading the row geometry
carefully, and that turned up an error in E.1a. `ROW_22` runs through the 8 um
gap in the middle of the macro block, so the "channel" figure and the row area
both counted the same 652.800 um2. The channel was 5760.000 and is 5107.200;
the margin was 4461.632 and is 5114.432. `docs/phaseE_tile_budget.md` carries
the correction and the reason the check that should have caught it could not.
