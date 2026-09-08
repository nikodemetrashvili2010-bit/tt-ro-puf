# Run 74: the row that would not cut

8 September, commit `72fd62f`, the one carrying the three sweeps. `gds`
failed at 2m54 in the same step as 72 and 73. This time the annotation
carried what the step did before it stopped:

    + repair_design -verbose -max_wire_length 0 -slew_margin 20 -cap_margin 20
    [INFO RSZ-0038] Inserted 69 buffers in 20 nets.
    [INFO RSZ-0042] Inserted 10 tie sky130_fd_sc_hd__conb_1 instances.
    [WARNING RSZ-0020] found 2 floating nets.
    [...]
    [INFO DPL-0020] Mirrored 476 instances
    [WARNING DPL-0005] Overlap check failed (3).
      u_rob12 (ro_macro_hard) overlaps PHY_EDGE_ROW_61_Left_49 (decap_3)
      u_rob4  (ro_macro_hard) overlaps PHY_EDGE_ROW_38_Left_26 (decap_3)
      u_rob8  (ro_macro_hard) overlaps PHY_EDGE_ROW_56_Left_44 (decap_3)
    [ERROR DPL-0033] detailed placement checks failed.

## Wrong twice, and the second one was mine this morning

Step 7 blamed tap insertion. Run 73 killed that: steps 18 and 19 finished.

Then `phaseG_run73.md` built a chain from the resizer, every link read out
of the pinned OpenROAD, and offered `RSZ_DONT_TOUCH_RX` as the fix. Run 74
says the resizer inserted 69 buffers and resized nothing. There is no
"Resized N instances" line because there were none. The chain was sound
and the thing at the end of it did not happen. Had that config line gone
in yesterday it would have changed nothing, and the next run would have
been read as "the resize fix did not work" instead of as what it is.

The pinned Arm A cells are not in the report. Three Arm B macros overlap
three endcap cells. That is the fact, and it is not one either of the
previous two days would have guessed.

## What the three names say

`PHY_EDGE_ROW_38_Left_26` is an endcap on a row named `ROW_38`. In the
frozen two-arm DEF the same row's endcaps are `PHY_EDGE_ROW_38_5_Left_15`
and `_Right_112`, on a row named `ROW_38_5`: the fifth fragment after
`cut_rows` cut the original around the four macros, at x 245640 and
330740, either end of the piece to the right of the macro block. Tapcell
names an endcap after the row it sits on, so a name with no fragment
suffix is a row that was never cut. Row 38 ran whole in run 74, from the
core edge at 2760 through u_rob4 at 3220, and its Left endcap, 1380 dbu of
decap_3, went in at 2760 and overlapped the macro by 920.

Which macros, and which rows, is the tell. Each leftmost macro spans about
fifteen rows; the pinned Arm A cells sit in rows 25 to 61:

    u_rob0   rows  6..21   shares no row with Arm A    no overlap
    u_rob4   rows 24..38   shares 25..38               overlap in row 38
    u_rob8   rows 41..56   shares 41..56               overlap in row 56
    u_rob12  rows 59..73   shares 59..61               overlap in row 61

The one macro that shares no row with Arm A is clean. The reported row is
the top shared row in each band, which is `check_placement` naming one
partner per failing cell and the last one it found. Every uncut row
through a leftmost macro has an endcap in it; three cells are reported
because three macros are involved.

## The line, at the revision the flow builds

LibreLane 3.0.5 pins OpenROAD at `dcf36133`, 17 February 2026.
`odb::cutRows`, `src/odb/src/zutil/util.cpp` line 181. Before it cuts
anything it walks every instance and, for each one that is fixed and is a
core cell rather than a block, records the row that contains it. Then:

    if (placed_row_insts.find(row) != placed_row_insts.end()) {
      logger->warn(utl::ODB, 386,
                   "{} contains {} placed instances and will not be cut.",
                   row->getName(), placed_row_insts[row]);
    } else {
      cutRow(block, row, row_blockages, min_row_width, halo_x, halo_y);
    }

A row holding any fixed standard cell is never cut, whatever crosses it.
It warns ODB-0386 and moves on, so step 18 completes and the reporter,
which quotes the step that stopped, never saw the warning. `Tapcell::
findBlockages` (tapcell.cpp line 314) takes only blocks, which is what the
7 September note read and reported; it is a different loop from the one
that decides whether a row is cut at all.

Step 17 pins Arm A FIRM. Step 18 then finds 37 rows with a fixed standard
cell in them and a macro across them, and leaves all 37 whole.
`getBoundaryAreas` (tapcell.cpp line 410) builds the placeable area from
the rows, so those 37 rows contribute area that runs straight through the
macro block, and endcaps go on the edges of it.

Run 71 built the same RTL with the same macros and passed, because it
placed the macros through `MACROS` and pinned no standard cell before
step 18. Runs 72, 73 and 74 differ from it by the cfg file alone.

## So FIRM is not available

Not to a standard cell that shares a row with a macro, and Arm A shares 37
of them by the coordinates the whole comparison rests on. That is a
property of the flow, not of the config, and there is nothing in
LibreLane's 413 variables that reaches it.

The fallback declared on 6 September is now the mechanism:

- `MACRO_PLACEMENT_CFG` comes out of `config.json`, so the sixteen macros
  go back through `MACROS`, exactly as run 71.
- `MANUAL_GLOBAL_PLACEMENTS` goes in, the 512 Arm A cells with their
  frozen coordinates and orientations, read at step 33 by
  `Odb.ManualGlobalPlacement`. It takes a dict and not a file, so the
  block lives in `config.json` itself, 512 lines of it.
  `gen_placement_cfg.py`'s new P13 holds that block equal to the
  generator's own rendering, keeps the cfg file from being wired back in,
  and requires mirroring to be off.
- `PL_OPTIMIZE_MIRRORING` is set false. `dpl.tcl` line 22 otherwise runs
  `optimize_mirroring`, which flipped 476 instances in run 74, and an Arm
  A cell mirrored N to FN has the same origin, different pin positions and
  different routing, and stops matching the DEF the extraction was done
  against.

Step 33 sets PLACED. Step 32 has already legalized by then, so the 512
cells land on sites global placement may have given to something else,
and step 34 legalizes again with both parties movable. Which one moves is
opendp's choice. The flow reports the displacement in a log nobody here
can read.

## So the build reports on that too

`chip/placement_fidelity.py`, five checks, run twice in the gate and once
in CI. It reads the DEF a build wrote and compares every Arm A cell to
what `config.json` asked for: found, at its coordinate to the dbu, in its
orientation, placed at all, and the intent itself is sixteen rings of
thirty-two and nothing else. The real-input control is the frozen two-arm
DEF, which the coordinates came out of and which passes 512 of 512; if the
checker and the intent ever disagree on the source, the gate goes red
before a build is spent on it.

In CI it runs after a build that finished and puts the answer in an
annotation: a notice if all 512 stayed, an error naming the movers and
the largest displacement if not. It does not fail the job. A moved cell is
a result about the mechanism, and `gl_test` and `precheck` sit behind this
job and have never once run on the three-arm design.

## A trap that did not fire, kept because the next reader will worry too

`placers.py`'s step 33 code does `int(x * db_units_per_micron)`, no
rounding. Twenty-one of the 512 coordinates would lose a dbu that way,
261.28 landing at 261279. It does not happen: LibreLane parses every
config float as `Decimal` (`config/config.py` line 568, `Instance.location`
is `Tuple[Decimal, Decimal]` at `variable.py` 98 and 218), and
`Decimal("261.28") * 1000` is exactly 261280. The fidelity checker
converts the same way rather than assuming it.

## What is not known

Whether step 34 moves anything. The run answers that, and the answer is
either a green build with a notice, or a green build with a list of names.

Arm C inherits all of this. Five hundred and twelve more cells pinned in
rows the macro block spans would hit ODB-0386 the same way. They go in
through step 33 too, or not at all, and that is a decision about the
experiment and not a generator's.

## Gate

121 commands, from 119: the checker's selftest and its real-input control.
The generator's selftest is 13 checks and 15 faults, each tripping one.
