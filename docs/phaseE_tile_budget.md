# Phase E.1a: what is actually left on the 2x2 die

`chip/tile_budget.py`, `chip/TILE_BUDGET.json`. Written 2026-08-25.

E.1 asks what a third layout treatment costs. Before that can be answered
there has to be a number for what there is, and until today the only figure
on record was the comment above `tiles: "2x2"` in `info.yaml`:

    # 16 hardened 60x40um macros on a 4x4 grid need a 2x2 tile
    # (334.88x225.76).

That says what Arm B needs. It says nothing about what is left over, and the
leftover is the number the Arm C decision turns on.

## The answer

**17272.816 um2 of placeable row area is free.** That is 64.0 percent of the
rows and 22.8 percent of the die. All sixteen Arm A rings together occupy
1921.843 um2, so the free area is nine Arm A banks, or about 143 more rings
of the shape this design already builds.

The rest of this file is where that number comes from and what it does not
account for.

## The die adds up, four ways

| region | area um2 | share |
|---|---:|---:|
| Arm B macros, 16 at 60 x 40 | 38400.000 | 50.79% |
| channel inside the macro block | 5107.200 | 6.76% |
| placeable rows, 81 of them | 26980.877 | 35.69% |
| margin between the outermost row or macro and the die edge | 5114.432 | 6.76% |
| die, 334.88 x 225.76 | 75602.509 | 100% |

The channel is the one people forget. The macro pitch is 60 um across and
48 um down, and a macro is 60 x 40, so there is no gap between columns and an
8 um gap between rows of macros. Three gaps, each 240 um wide. That is where
the Arm B enable and output nets get out of the block, and it is not
placeable.

**Corrected 2026-08-30.** The first version of this table read 5760.000 for
the channel and 4461.632 for the margin, and said the four figures adding to
the die exactly was the first sign the geometry had been read correctly. Both
halves of that were wrong.

The macro block's bounding box is a construction, not an object, and a row
can run through it. One does. `ROW_22` sits in the 8 um gap between the
second and third rows of macros and crosses the whole block, 240.0 by 2.72
um, 652.800 um2. Charging that to the channel and to the rows at once counts
it twice. It is subtracted from the channel now and appears in the JSON as
`row_area_inside_macro_block_um2` so nobody has to rediscover it.

And the sum proved nothing. The margin is computed as what is left after the
other three, so it absorbs any error in them and the total is exact whatever
they say. A check with a free variable in it is not a check. What actually
holds the split together is `T09`, which requires that no macro overlaps any
row and can fail, and the overlap above being measured rather than assumed to
be zero.

The error surfaced on 30 August while looking for somewhere to put sixteen
Arm C regions, because the region search reads the same row geometry and
`ROW_22` is the one row in the middle of the macro block.

## Where the free area is

The rows come in two shapes. Twelve of them run the full width of the die,
above and below the macro block. The other sixty-nine are the strip to the
right of the macros, 86.48 um wide, and that is where the placer put Arm A.

| region | rows | row area um2 | free um2 | held um2 |
|---|---:|---:|---:|---:|
| band, above and below the macros | 12 | 10750.310 | 6433.670 | 4316.640 |
| strip, right of the macros | 69 | 16230.566 | 10839.146 | 5391.421 |

Arm A's bounding box is 247.48 to 307.74 across and 70.72 to 171.36 down. It
sits entirely inside the strip and clear of the macro block, which the script
checks rather than assumes.

## What is in the rows

| class | count | area um2 | reclaimable |
|---|---:|---:|---|
| decap | 4292 | 16110.451 | yes |
| logic | 563 | 7256.960 | no |
| arma_ring | 512 | 1921.843 | no |
| fill | 673 | 1162.365 | yes |
| tap | 419 | 524.253 | no |
| diode | 2 | 5.005 | no |
| armb_macro | 16 | 38400.000 | no, and not on a row |
| total | 6477 | 65380.877 | |

Two thirds of the row area is decap. That is not a design decision anybody
made; it is what filler insertion does with a floorplan that has more room
than the logic needs.

The reclaimable/held split is the only judgement in the script and it is
stated rather than derived. Filler and decap come out and go back in around
whatever is placed instead. Taps do not: sky130 wants one within a fixed
distance of every cell, so the tap count follows the row area rather than the
occupancy, and 419 of them will still be there afterwards. Antenna diodes
stay. Logic and Arm A stay by definition.

## How the widths were recovered, and why that is safe

The sky130 LEF is not in this repository. Adding a PDK to settle one
arithmetic question would be the wrong trade, so no cell width in this
analysis comes from a library file.

They come from the placement. A legalized row is packed edge to edge, so the
distance from one cell's origin to the next cell's origin is the left cell's
width. Every master in this design abuts something somewhere, so every width
comes out. Fifty-one standard-cell masters, all recovered; the macro is the
fifty-second and its size comes from its own LEF.

Three things make that safe rather than convenient, and they are one check
rather than three:

- no master may show two different widths across the abutments it takes part
  in,
- every row must be flush at both ends with no gap and no overlap between,
- the row site area must equal the area of the cells standing on it.

They are one property seen three ways. A width that is ambiguous is a row
that does not pack, and a row that does not pack has the wrong area, so no
planted fault can separate them. I tried, and every fixture I could write for
one of them tripped the other two. They are `T06`, one check with one message,
for the same reason the three name-audit checks in `ring_topology.py` became
one on 19 August.

The independent test is the total. Standard cells at row height, macros at
the height their own LEF declares, summed, is 65380.877 um2.
`metrics.json` says `design__instance__area` is 65380.9. OpenLane wrote that
during the same run out of its own database, this script does not read it
until the comparison, and they agree to the rounding step. That is the check
that would catch a systematically wrong width table, and it is `T12`.

## Two files, two escaping conventions

The DEF escapes bracket characters one at a time:

    - u_puf.u_core.g_ro_bank\[0\].u_ro.g_inv\[10\].u_inv sky130_...

The gate-level netlist escapes the whole identifier with a single leading
backslash and leaves the brackets alone:

    \u_puf.u_core.g_ro_bank[0].u_ro.g_inv[10].u_inv

Same flow, same run, two conventions. Phase A learned a version of this on
19 August with the SPEF's escaped dot. Here the fix is to strip backslashes
before comparing anything, which is what `unescape` does, and to compare the
two files rather than trusting either. `T14` builds each Arm A ring's
composition from the DEF and again from the netlist and requires them to
agree. They do: sixteen rings, one shape, thirty `inv_1` and one `buf_1` and
one `nand2_1` each.

## Checks and faults

Sixteen checks, all passing on the current build. Sixteen planted faults in
`--selftest`, each naming the one check it must trip and failing if a second
one fires. Three refusals: the parser must not accept a DEF with no
`DIEAREA`, no `ROW` records, or an empty `COMPONENTS` section.

The fixture is a miniature of the real design rather than a toy. Real site
width, real row height, the real 334.88 x 225.76 die, the real 4x4 macro grid
at the real pitch, and four rows in the strip beside it. That matters,
because with a toy fixture the checks that are statements about this die
would have had to be excused, and an excused check is one nobody exercises.
Nothing is excused here.

Two of the faults are worth naming because getting them wrong is easy.

The site-grid fault (`T05`) recuts one row as 30 sites of 368 units instead
of 24 sites of 460. The span is identical, so the row still packs and the row
area is unchanged, and the only thing that changes is that every cell in it
is suddenly off the grid. Moving a cell would have tripped the packing check
as well.

The macro-on-a-row fault (`T09`) slides the whole array right and down onto
the strip, not one macro. Moving one would also break the 4x4 grid check.

One check cannot be tripped by any input file. `T13` says the classes
partition the components exactly once, and `classify` returns a name from the
declared list for every master it is handed, so no DEF can make it fail. It
guards the classifier, so its fault comes from the other side: the selftest
passes in a classifier that invents a class for antenna diodes. Say that
plainly rather than letting a reader count `T13` as evidence about the
design.

## What this does not settle

Whether all 17272.816 um2 is really free is a power question, not a geometry
one, and this script cannot answer it. Decap is decoupling capacitance. Some
of it is holding the supply up under the switching of 6477 instances, and how
much is the difference between a filler cell and a design decision. Nothing
here has measured that. The E.1b cost model prices Arm C at several
fractions of the free area for that reason, and the answer gets settled by
an IR-drop run at build time, not by arithmetic.

The routing cost is also not here. Area is necessary and not sufficient: a
third arm adds nets, and whether they fit is a separate question that
`chip/armc_cost.py` takes up next.
