# Run 83: all three arms placed, and held

16 September, commit `8f8939a`, pushed at 17:40 UTC. The first build
with Arm C placed, and the first on LibreLane 3.0.14 under the
`ttsky26d` tag. Both changes in one run, which is not how I like to do
it, and the tag change was not optional.

    archived-evidence   green   1m 01s   130 of 130
    gds                 green   4m 57s
    precheck            green   2m 06s
    gl_test             green     46s
    viewer              red       12s

`viewer` is Pages. Same red as runs 80 to 82, same one click.

## The annotations

Three, as the run page shows them.

    Arm C held 512 of 512 cells FIRM
    ok   K13: 512 of 512 present
    ok   K14: 0 moved
    ok   K15: 0 turned
    ok   K16: 0 unplaced
    ok   K17: 0 resized

First time that annotation has said anything. Every one of the 512
cells is at the coordinate `chip/ARMC_FIX.json` records, in the
orientation the template's row phase gave it, still the master the RTL
asked for, and legalization left all of them alone.

    Arm A: 512 of 512 at their coordinate
      box 247480,70720 to 307740,171360 holds 74 taps, 1137 fillers
      and 23 other cells

Unchanged from run 80 apart from the box: 23 foreign cells against 24,
three fewer fillers. Adding 512 fixed cells in the strip next door
barely moved the neighbourhood.

    Rings: 32 of 32 intact
    every loop is 1 nand + 30 inv + 1 buf with nothing else on it

## What the green settles

The taps. The template holds sites 11 and 39 clear on the assumption
that the three-arm floorplan puts its taps where the two-arm DEF had
them, in all 81 rows and not only the 37 Arm A stands in. Run 80's
writeup called that an assumption until a build said otherwise. A tap
on a cell site would have been an overlap and the build would have died
at step 32 with the cell named. It did not.

The flow version. The 3.0.5 to 3.0.14 comparison in
`chip/FLOW_SURFACE.json` said nothing that cuts a row, places a tap or
moves a cell changed. The build agrees.

The checkers. The gds job only finishes if Magic DRC, KLayout DRC, LVS
and antenna come back clean, because each of those is a step that
fails the flow on a violation. Precheck is Tiny Tapeout's own read of
the GDS and it passed too. So the GDS this run produced is the one to
submit.

## What it does not settle

Whether sixteen identical placements route to sixteen similar loads.
That is the experiment, and it is read out of the three-arm SPEF by
the extraction pass, G.3 steps 9 to 12, not out of a green job.

The soft box. Still there, still holding nothing now that both arms
are fixed, still waiting for a run that changes only that.

## Open

Pages. The soft box run. G.3 steps 9 to 12 on this build's outputs.
The two `info.yaml` lines that still say "equalized".
