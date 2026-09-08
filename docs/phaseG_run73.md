# Run 73, and what the build finally said

7 September, commit `a1db066`. `archived-evidence` 45s green, `gds` failed at
2m33, the other three skipped. Same shape as run 72 and that was the point:
`4362fd5` changed nothing the build reads, so run 73 is run 72 with a voice.

It worked. The annotation, which is one of the three things a signed-out
reader can see on a run page:

    LibreLane stopped in 32-openroad-repairdesignpostgpl
    flow: DESIGN_NAME tt_um_nikodemetrashvili20_ro_puf, PDK sky130A
    31 of 32 entered, last entered 32-openroad-repairdesignpostgpl
    error.log: [DPL-0033] detailed placement checks failed.
    32-openroad-repairdesignpostgpl/openroad-repairdesignpostgpl.log:
      [ERROR DPL-0033] detailed placement checks failed.
    Error: repair_design.tcl, 68 DPL-0033

## What that kills

Step 7 put the risk on `CutRows` at 18 and `TapEndcapInsertion` at 19, on
the grounds that taps would have to go in around 512 cells that were already
FIRM. On 7 September I called that a strong candidate with no evidence
behind it. It is wrong. Thirty-one steps finished, so 17, 18 and 19 are
three of them. Tap insertion worked around the pinned cells without
complaint.

The frozen build agrees, in hindsight. Its 419 tap cells sit on a strict
grid, 12880 dbu apart with a skip to 25760 where a macro is in the way, and
the first tap in a row is at one of only four x values. Re-running that on
the same rows puts the taps back where they were, and the pinned cells came
out of a DEF in which they were already placed around them.

So the failure is 13 steps later than the day's hypothesis, and I would not
have got there by reading more Tcl.

## Where DPL-0033 comes from

`repair_design.tcl` is 77 lines. Line 68 is not the repair, it is

    source $::env(SCRIPTS_DIR)/openroad/common/dpl.tcl

and `dpl.tcl` is 24 lines: `remove_fillers`, `detailed_placement`,
`optimize_mirroring`, and then, as the last line of the file,
`check_placement -verbose`.

That matters. DPL-0033 is not detailed placement failing to place something.
It is the check afterwards saying the result is not legal. `check_placement`
has six of these - placed, in-rows, overlap, site, power line, placement -
and it names which one before it errors. That line is what the annotation
did not carry.

## The pinned set is not the problem

Before blaming the flow I checked our own file against the DEF it was
generated from. `src/placement.cfg`, 528 entries: 16 `u_rob*` macros and 512
Arm A standard cells.

    512 of 512 found in the frozen DEF
      0 coordinate mismatches
      0 orientation mismatches
      0 off-row
      0 off-site
      0 outside the core
      0 power-line parity failures

The last one is the one I expected to catch something. Rows alternate N and
FS from y=2720 upward on a 2720 pitch, and a single-height cell has to match
its row's parity or its rails are upside down. All 512 match. So
`gen_placement_cfg.py` is right and the geometry it emits is legal on its
own terms.

## What is the problem: there is no room

I got the first measurement wrong and it is worth keeping. What I asked to
begin with was how many of the pinned cells sit flush against the next cell
in their row, and the answer came back 512 of 512, which felt like a finding
for about a minute. It is not one. The final DEF is filled, so every cell in
it is flush against its neighbour, all 6477 of them, and Arm A has nothing to
do with it. The question only means anything once the fillers are gone, which
is the state `dpl.tcl` puts the design in on its first line.

Widths next, because the number matters and I nearly got that wrong too. The
DEF is tiled to the last site, fillers going down to `fill_1` at one site
wide, so the distance from a cell to the next instance in its row is exactly
that cell's width rather than an upper bound on it. The 512 are 480 `inv_1`,
16 `buf_1` and 16 `nand2_1`, all three 1380 dbu, three sites. `buf_1` agrees
with the liberty, 3.7536 um2 over a 2.72 um row. So does `inv_2`, also 1380,
which is worth writing down because I had expected 1840 and would have
carried that mistake.

So, fillers gone, how much free space does each pinned cell have to its
right:

    0 sites   304 cells
    1 site     57
    2 sites    32
    3 sites    14
    4 sites     7

Three hundred and four of the 512 have none at all. Of those, 262 are butted
against another pinned Arm A cell, 19 against a tap cell, and the rest
against ordinary logic. That is what a ring looks like when the placer has
had its way with it: 32 cells in a solid run, no gaps, because there was no
reason to leave any.

Which means the pinned arm cannot absorb a single site of growth anywhere.

## The mechanism, read at the revision the flow actually builds

`librelane/nix/openroad.nix` at 3.0.5 pins OpenROAD at
`dcf36133a369abc8f3c5e5738cd4d82e4903c0e0`, dated 2026-02-17. Reading that
revision rather than master:

- `Resizer::resizeToTargetSlew`, line 2324, does its work if
  `!dontTouch(inst) && cell && isLogicStdCell(inst)`. There is no test of
  placement status.
- `Resizer::dontTouch(const Instance*)`, line 2914, is three lines and
  returns `db_inst->isDoNotTouch()`. FIRM is not don't-touch.
- `Resizer::replaceCell`, line 2506, swaps the master and leaves the origin
  alone. It calls `opendp_->legalCellPos` only when parasitics come from
  global or detailed routing. Step 32 runs `estimate_parasitics -placement`
  at line 28 of its own script, so it does not call it.
- `Resizer::balanceBin`, line 537, skips an instance when
  `getPlacementStatus().isFixed() || isDoNotTouch()`. So the file knows the
  test exists. It is not on the resize path.

And `RSZ_DONT_TOUCH_RX` is unset in this design, so nothing sets the flag
that would have stopped it.

Put together: `repair_design` is free to upsize a pinned cell, does it by
changing the master under a fixed origin, and nothing legalizes the result.
A cell with zero free space to its right then overlaps its neighbour, and
its neighbour is FIRM too, so `detailed_placement` cannot open a gap.
`check_placement` says so and the flow stops.

## What is still not known, and it is the whole thing

Which check failed, and on which instances. The log has it. The log needs a
signed-in session and the artifact needs a token, so I still cannot read
either. The chain above is sourced at every link but it has not been
observed once.

## So the reporter got the rest of the change

Two sweeps, both build-neutral.

The lead-in: the lines immediately above the first error line. A tool's last
line is where it gives up, not where it says why.

The warning sweep, separately, because `check_placement -verbose` can list
several hundred instances between its verdict and the error and the verdict
would be pushed out of any lead-in worth carrying.

And the change sweep, which is Nikoloz's call and the better half of the
two: the lines where a step says what it changed, a verb and a number on the
same line. `repair_design` writes "Resized 42 instances" and "Inserted 18
buffers in 12 nets" long before anything goes wrong, and those two counts
are what decide whether the resize story above is true or invented. They
were being thrown away.

R08 and R09 are the checks, and both look for the line themselves rather
than asking the selector what it selected. Turned off, both fail on a
fixture whose diagnosis sits two hundred instance lines above its error. The
annotation that fixture produces is 1702 characters of the 3600 available
and reads:

    [INFO RSZ-0030] Inserted 18 buffers in 12 nets.
    [INFO RSZ-0031] Resized 42 instances.
    [...]
    [WARNING DPL-0005] Overlap check failed (12).
    [...]
      <twelve named instances>
    [ERROR DPL-0033] detailed placement checks failed.

That is the run I want next.

## If it is confirmed

`RSZ_DONT_TOUCH_RX` matches instance names as well as net names -
`set_dont_touch_objects` in `common/resizer.tcl` loops over both - so a
regex covering the Arm A ring instances is one config line and no new
mechanism. That is the fix if the category comes back as overlap and the
resize counts are non-zero.

If the counts come back zero the story above is wrong and the fallback
stands: `MANUAL_GLOBAL_PLACEMENTS` at step 33, which gives up FIRM.

Either way, do not build Arm C's placement yet. Nothing here changes that.
