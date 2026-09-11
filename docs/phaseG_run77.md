# Run 77: the two cells that moved Arm A, and the hook that fixes it

10 September, commit `440d15b`, the run 76 follow-up that Nikoloz pushed
himself while the shell was down. Written up on the 11th.

    archived-evidence   green   1m 25s
    gds                 green   4m 55s
    precheck            green   2m 22s
    gl_test             green     47s
    viewer              red        7s
    test / test         green     40s

`gl_test` is green for the first time. Seven of seven, so the deselect
probe at a quarter clock holds on the netlist and the two nanoseconds
were real. `viewer` is still Pages.

## The box report

Run 76 said five cells moved and could not say what moved them. This run
carries the report `440d15b` added, and it names them.

    box 247480,70720 to 307740,171360 holds 74 taps, 1160 fillers
      and 11 other cells
    g_armc[13].u_roc.g_inv[2].u_inv  inv_1                at 307280,70720
    _334_              and3_2                            at 292560,111520
    _681_              dfrtp_2                           at 307280,114240
    _684_              dfrtp_2                           at 306360,136000
    _461_              a221o_2                           at 251160,155040
    fanout54           clkdlybuf4s25_1  SOURCE TIMING    at 253920,157760
    clkbuf_4_10_0_clk  clkbuf_8         SOURCE TIMING    at 266340,157760
    clkload1           clkbuf_4         SOURCE TIMING    at 274620,160480
    clkbuf_4_11_0_clk  clkbuf_8         SOURCE TIMING    at 274620,163200
    _691_              dfrtp_2                           at 306360,163200
    _338_              and3_2                            at 266340,168640

Eleven, against 93 in the two-arm build's version of the same rectangle.

The five moves are the same five as run 76, to the dbu.

Two of the eleven stand exactly where an Arm A cell was supposed to be.
`_334_` is at 292560,111520, which is ring 9's `g_inv[26]`. That
inverter went down a row into ring 7's row, and ring 7's `g_inv[28]` and
`g_inv[27]` went sideways and its `g_inv[26]` down another row to make
room. One intruder, four moves. `clkbuf_4_10_0_clk` is at 266340,157760,
ring 14's `g_inv[11]`, which went left by three sites.

So run 76's reasoning was wrong about the cause.

It said the five were shoved by something that arrived after global
placement, and named the resizer as the only thing left that could.
`_334_` is not a resizer cell. It is a netlist gate, one of the sixteen
ring-enable decoders, and it was there at global placement.

The soft obstruction is a density penalty. Global placement marks every
site under a blockage unusable and then minimises wirelength against
that penalty; a decoder whose one output goes to a ring NAND inside the
box is pulled in by that wire hard enough to sit in the box regardless.

Legalization then ignores the soft box entirely. It places by area, an
and3_2 is larger than an inv_1, so the decoder kept its site and the
inverter went looking for another.

The clock buffer is the other kind. Clock tree synthesis puts its
buffers where the sinks are, after global placement, and legalizes them
the same way. Where its three buffers stand is where the tree wanted
them, and a soft box says nothing to it.

The dont-touch regex would have changed nothing about either. Run 76
held it back until the run named the cause, and the cause was not a
resize. That rule was right by exactly this much.

Four of the eleven straddle the edge: three `dfrtp_2` at x 306360 and
307280 with the box ending at 307740, so their origins are inside and
most of the cell is outside, and an Arm C inverter at the bottom right
corner. The report counts origins, which it says, and those four are
what that costs.

## Hard obstruction, and why not

The ring walk writeup, written the evening before this run came in,
named the fix: a hard obstruction, `PL_OBSTRUCTIONS`, covering the box
except Arm A's own sites and the taps. That variable does not exist.
The name was a guess and the writeup is left as it stands.

What does exist is `FP_OBSTRUCTIONS`, and reading it at source on the
morning of the 11th ended the idea.

`floorplan.tcl` in LibreLane 3.0.5 creates those blockages at lines 99
to 108, before `initialize_floorplan` at line 112. The soft ones come
after it, at 117 to 127. That order is the whole difference.
`InitFloorplan::makeRows` in the pinned OpenROAD ends, at lines 516 to
527, by collecting every blockage in the block and calling
`odb::cutRows` on the lot with a minimum row width of zero. Rows are
cut round every hard obstruction. LibreLane's own description of the
variable says the same thing in fewer words: placement sites are never
generated there.

Then step 19 puts an endcap at both ends of every row fragment. Arm A is
not a block. It is sixteen blobs the two-arm placer scattered across 37
rows, ring 14 alone spanning eight of them, with fillers and taps between
the cells. Any obstruction shaped round it fragments those rows into
runs a few sites long, each of which gains two endcaps of three sites,
and the taps re-pitch from each fragment's start. The frozen coordinates
would land on endcaps and taps and the legalizer would move all of them.

And a hard blockage that survives to the end stops fill insertion too.
`Grid.cpp` at 193 to 213 marks every pixel under a non-soft blockage
invalid, and `FillerPlacement.cpp` at 166 and 175 skips invalid pixels.
Two cells in a row with a blocked gap of one or two sites between them
would be left with their nwells at most 0.46 or 0.92 um apart against a
1.27 um rule. That is a DRC failure by design.

So no obstruction, hard or soft, holds a PLACED cell against a larger
cell that wants its site. Only FIRM does, and FIRM at step 17 breaks
row cutting.

That was the corner the 8th left us in.

## The hook

The flow has one user-supplied Tcl file it sources after the rows are
cut and before anything is placed. It is `PDN_CFG`.

`OpenROAD.GeneratePDN` is step 21 in the Classic flow this build runs.
`Odb.ManualMacroPlacement` is 17, `OpenROAD.CutRows` 18,
`OpenROAD.TapEndcapInsertion` 19, and the first placement step,
`OpenROAD.GlobalPlacementSkipIO`, is 24. `pdn.tcl` reads the ODB, calls
`read_pdn_cfg`, which is `source $::env(PDN_CFG)` inside a catch at
`io.tcl` line 176, runs `pdngen`, and writes the views. Whatever the
sourced file does to the ODB is what step 22 reads.

This design already owns that file. `src/pdn_cfg.tcl` is the met4-only
macro grid from the dffram example, modified in August so the stripes
land on the macros' internal straps. It runs inside OpenROAD with the
block in hand.

So `PDN_CFG` now names `src/pdn_hook.tcl`, which is two live lines:
source `pdn_cfg.tcl`, then source `arma_place.tcl`, both by the path of
the file being sourced rather than the working directory. The recipe
file is untouched. `sim/verify_macro_provenance.py` holds it directive
for directive against `array/pdn_cfg.tcl`, and my first version of this
appended the source line to the recipe itself and tripped that check,
which is the check doing its job. The wrapper is the fix.

`src/arma_place.tcl` is generated by `gen_placement_cfg.py` from the
frozen two-arm DEF. A fourteen-line proc and 512 calls to it:

    arma_fix {u_puf.u_core.g_ro_bank\[9\].u_ro.u_nand} 281520 111520 R0

Name as the DEF spells it, a backslash before each bracket, braced so
Tcl leaves it alone. Coordinates in database units, nothing multiplied.

Orientation as OpenDB names it: the Tcl binding for `dbOrientType`
(`swig/tcl/dbenums.i`, the `typemap(in)` at lines 36 to 57) takes the
eight OpenDB names and raises "Unknown orientation" on anything else,
so a LEF `N` in this file would kill the build at step 21 rather than
place anything.

The proc refuses a name it cannot find and a cell that is already
fixed, and the file ends by refusing any count but 512.

FIRM at step 21 has neither problem. The rows were cut three steps
earlier, so ODB-0386 has nothing to refuse. And nothing later moves a
fixed standard cell: global placement treats it as an obstacle, the way
it already treats the 419 taps, and detailed placement never touches
one. A decoder that global placement leaves in the box is now the cell
that gets legalized somewhere else.

`MANUAL_GLOBAL_PLACEMENTS` is gone from `config.json`, 514 lines of it.
It had to go: `placers.py` sets PLACED unconditionally at step 33, so
leaving it in would have demoted all 512 cells back to PLACED after the
hook had fixed them, and the step skips itself when the key is absent
(`odb.py` line 1030).

The soft box stays, on purpose, one change at a time: with Arm A fixed it only
keeps global placement's cells out of the gaps between the rings. Whether it
should stay is an open question and not a decision.

## What holds it

`gen_placement_cfg.py` renders the hook alongside `placement.cfg`, and
three of its checks changed or arrived.

P13 used to hold `config.json`'s block equal to the rendering. Now it
holds `config.json` clear: no `MANUAL_GLOBAL_PLACEMENTS`, no
`MACRO_PLACEMENT_CFG`, mirroring off, `PDN_CFG` pointing at the wrapper.
Four planted faults, one each.

P15 reads the hook file off disk with its own parser, not the renderer,
and compares it to the DEF: every Arm A cell once, DEF spelling, DEF
coordinate, DEF orientation under its OpenDB name, nothing else placed,
FIRM in the proc, 512 in the guard. Four faults: a coordinate one site
off, a name with the netlist's single leading backslash instead of the
DEF's per-bracket ones, the proc set to PLACED, a LEF orientation.

P16 holds the wrapper to exactly its two live lines in that order. Three
faults: the hook line commented out, the recipe line dropped, a PDN
directive added to the wrapper instead of the recipe.

Sixteen checks, 25 faults, each tripping exactly one. The gate gains
`diff /tmp/pl/arma_place.tcl dualarm/src/arma_place.tcl`, 123 commands,
and `diff -r src dualarm/src` covers the other copy.

`placement_fidelity.py` reads its intent from the hook now instead of
from `config.json`, unescaping the names and mapping the orientations
back, and its selftest reads a three-line fixture hook and refuses a
line with a LEF orientation. The frozen DEF still passes 512 of 512
through the new reader.

With FIRM the honest expectation on the next build is 512 of 512, and a moved
cell now means the flow overrode a fixed placement, which is a louder finding
than a legalizer doing its job.

The hook ran under Tcl 8.6 against a mock block that records every call:
512 names, 512 distinct, backslashes intact, R0 and MX and nothing else,
FIRM 512 times, the guard firing on a planted missing name, and the
wrapper's relative source working from an unrelated directory.

What it did not run against is OpenROAD, which is not on this machine. The four
ODB calls are the four `placers.py` makes from Python, and the two Tcl
typemaps that turn strings into enums were read rather than exercised.

A second parser over the DEF, sharing no code with the generator, agrees
with the hook on all 512 names, coordinates and orientations, finds each
cell on its row's site grid with its orientation matching the row's, and
re-derives the box as 247.48, 70.72, 307.74, 171.36.

## What it costs, and what it does not settle

FIRM stops the placer and not the resizer. That is unchanged from run
73's reading of `Resizer.cc`. An upsized Arm A cell has no room to grow
into, so it would overlap a fixed neighbour, and `check_placement`
refuses that: the build dies at step 32 and the failure reporter names
the cell. Loud is right.

F06 is for the quiet case, a cell retyped in
place with room to spare, and `RSZ_DONT_TOUCH_RX` stays the lever if
either happens. Neither has yet.

The placement now rides on the PDN file, and a reader of `config.json`
alone cannot see it. `PLACEMENT_CFG.json` records the mechanism, the
wrapper's two lines and the step, and P13 and P16 are the two ends of
the wire. It still belongs in the paper's methods as a sentence, not a
footnote.

The same hook is how a hand-placed Arm C would go in, one file and one
proc, without a soft box of its own. That does not decide Arm C; H1 to
H6 are still unscored against the hand-placed option.

Not yet run. The next push is the first build with the hook, and the
ring walk over the three-arm netlist and F06 are on the same run. Run
78, the ring walk commit pushed the same evening as this one, died in
the gate on the workflow file that had not reached the clone, so
neither has an answer yet.
