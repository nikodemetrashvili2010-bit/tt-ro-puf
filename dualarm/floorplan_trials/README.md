# Floorplan trials: can the two arms share the die evenly?

Arm B is sixteen hardened macros on a fixed grid. Arm A is standard cells that the
flow places wherever room is left. In the shipped build that means the macros tile
x = 3.22 to 243.22 and all sixteen Arm A oscillators end up inside a box roughly
44 by 78 um on the right of the tile. Arm A samples one small region while Arm B
samples nearly the whole die, which is a poor arrangement for a hypothesis about
spatial pattern. It is also why Arm A output nets carry about 0.84 fF against Arm
B's 14.46.

I tried to fix it by moving macros, and it did not work. This folder records what
I measured, because the negative result is worth keeping.

## What was tried

Both trials keep everything else frozen: same RTL, same macro GDS, same
constraints, same PDN settings, same tool and PDK. Only macro locations move, and
in the second trial the row pitch. The configs are committed, so either build can
be reproduced:

    python3 gen_dualarm.py --interleaved            --out src/config_interleaved.json
    python3 gen_dualarm.py --interleaved --pitch-y 52 --out src/config_interleaved_p52.json

Interleaving means skipping the middle column of the 60 um power grid, so a 60 um
standard-cell channel runs down the centre of the macro field instead of Arm A
being pushed to one edge. Columns become 3.22, 63.22, 183.22, 243.22.

## What happened

| run | Arm A ring cap spread | excluding worst ring | worst ring bbox | Arm A x-span |
|---|---|---|---|---|
| shipped block, pitch 48 | 6.18 fF (44%) | 42% | 22 x 14 um | 43.5 um |
| interleaved, pitch 48 | 26.68 fF (199%) | 74% | RO9 126 x 3 um | 100.0 um |
| interleaved, pitch 52 | 20.11 fF (135%) | 84% | RO4 106 x 19 um | 123.9 um |

Both interleaved builds pass DRC, LVS, antenna and the power grid with no setup or
hold violations, so this is not a signoff problem. The problem is placement
quality. In each trial the placer stretched one entire oscillator into a long thin
line, 126 um in the first and 106 um in the second, and that ring's loop then has
to route back and forth across the whole span. Its capacitance roughly doubles
against the rest of the field.

My first guess was the 8 um gap between macro rows, which after 2 um halos leaves
a single 2.72 um cell row, so I raised the row pitch to 52 to give two rows per
band. That was wrong. The outlier did not go away, it moved to a different
oscillator, and the spread among the remaining fifteen got worse rather than
better. Two independent trials, two different victims, so the cause is the
fragmented space itself and not the band height.

Interleaving does deliver what it promised elsewhere. Arm A's x-span nearly
tripled, and Arm B's output loads became more uniform, tightening from 2.89 to
29.46 fF down to 7.28 to 18.30. Neither gain is worth a layout whose headline
statistic is hostage to one stretched ring, which is the exact fragility I removed
when I stopped quoting a single build.

## Why this is geometric

Four macro rows is the maximum that fits: at pitch 48 the top row already ends at
204 um against a core limit of 223.04. Sixteen macros in four rows therefore need
four columns, and only five column positions exist, because each has to sit on the
60 um power grid for the met4 stripes to land on the macro power pins. So the only
freedom is which four of five columns to use. The shipped choice puts them
together and leaves Arm A one contiguous 92 um strip. Every other choice leaves a
60 um channel plus a 29 um remnant, and that is what fragments Arm A.

The confound is a consequence of the die size, the macro footprint and the grid
pitch, not a configuration oversight. Removing it properly needs more area, a
larger tile or a smaller or less numerous macro set, and each of those changes the
experiment or the budget. For this tapeout the block floorplan ships and the
region difference is stated as a limitation.

## Files

`floorplan_trials.csv` has, for each of the three builds and all sixteen Arm A
oscillators: total ring capacitance, placement bounding box, centroid, and the
output-net capacitance of both arms. The bulky netlists, DEFs and SPEFs are not
kept here; rebuild from the configs above if the raw extraction is needed.
