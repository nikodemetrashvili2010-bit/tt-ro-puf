# Run 75: the chip builds, and three things it said

Evening of 8 September, commit `345380a`, the step-33 fallback. For the
first time the three-arm design went all the way through:

    archived-evidence   green    55s
    gds                 green   6m 6s
    precheck            green   2m 11s
    gl_test             red       58s
    viewer              red        9s
    test / test         red       19s

A GDS exists, and it has DRC, LVS, antenna and TinyTapeout's own precheck
behind it. Everything functional said about this chip before that evening
was said about the two-arm build.

Then the three red ones, which are three different stories.

## Arm A: 64 of 512 in place

`placement_fidelity.py`'s first real annotation:

    Arm A: 64 of 512 in place
    moved   g_inv[10]  276000,106080 -> 278760,106080  (2.760 um)
    moved   g_inv[13]  269560,106080 -> 273240,106080  (3.680 um)
    moved   g_inv[14]  268180,106080 -> 269100,103360  (2.720 um)
    rotated g_inv[14]  N -> FS
    ... and 572 more

448 cells moved, up to 3.68 um, and a good number went into the row above
or below: a y that changes by 2720 with an N to FS flip is a row change,
not a mirror. So step 34 resolved each overlap by moving the Arm A cell,
not the cell global placement had already put there. PLACED at step 33 is
not a pinning mechanism in this design either, and with FIRM at step 17
ruled out by run 74, both of the flow's placement mechanisms had now been
tried on the same 512 cells.

## Why they moved, and the thing that stops it

At step 28 the Arm A cells are not yet where they belong; global placement
puts them, and everything else, wherever the wirelength says. The sites
Arm A will need at step 33 are free real estate to it, and it fills them.
Step 33 then drops Arm A on top, and step 34 has to move something.

What was missing was a way to keep global placement out of a region
without keeping detailed placement out of it. The flow has one, in the
413 variables the step 7 survey listed and I read past twice:

    PL_SOFT_OBSTRUCTIONS
    Soft placement blockages applied at the floorplanning stage. Areas
    that are soft-blocked will not be used by the initial placer, however,
    later phases such as buffer insertion or clock tree synthesis are
    still allowed to place cells in this area.

`floorplan.tcl` line 117 makes each one a `dbBlockage` and calls
`setSoft`. Then, at the OpenROAD revision the flow pins:

- `gpl/src/placerBase.cpp` line 1264 marks every blockage's sites Blocked
  in the density grid, soft or not; it never asks. Global placement stays
  out.
- `dpl/src/infrastructure/Grid.cpp` line 194 and
  `dpl/src/dbToOpendp.cpp` line 163 both skip a blockage that `isSoft()`.
  Legalization does not know it is there.

So: soft-block Arm A's footprint at step 13, global placement keeps every
cell out of it, step 33 puts Arm A onto empty sites, step 34 sees legal
cells on free sites and leaves them alone. Magic ignores DEF blockages by
default (`MAGIC_DEF_NO_BLOCKAGES` is true) and nothing else in the flow
reads them.

The rectangle is derived, not typed: `gen_placement_cfg.py` takes every
pinned cell's footprint from the frozen DEF, widths by abutment through
`tile_budget.recover_widths`, and comes out with

    [247.48, 70.72, 307.74, 171.36]

which is the leftmost cell's left edge, the lowest row's bottom, the
rightmost cell's far edge and the top of row 61, all on the site and row
grid. P14 holds `config.json` to it and fails if a pinned cell is outside
it; the planted faults are a missing box and one that stops a site short.
It is 6161 um2 of a 75600 um2 die, and about 68 percent of it is empty
even with Arm A in it, which global placement now cannot use. At 28
percent standard-cell utilization that costs nothing that matters.

What it does not guarantee: a cell that step 32's own legalizer pushed
into the region under local pressure, or a buffer the resizer inserted
near an Arm A net, is still there when Arm A arrives. The checker counts
those. The expectation is a number near 512, not a promise of it, and the
next run says which.

Arm C's eight strip regions overlap this box. They are not placed today.
When they are, they and this box will have to be reconciled, and that is
one more reason Arm C's placement waits.

## gl_test ran for the first time, and the failure is the test's

The gl_test reporter from 7 September did its job: cocotb 2.0.1, iverilog
13.0, the PDK, the netlist, all present, and five failures in results.xml
all reading

    Arm-B enable was not one-hot/quiet for arm=1, idx=0:
      [(1, 1, 0), (2, 1, 0), (3, 1, 0), (4, 1, 0)]

Those are (elapsed, observed, expected). Observed 1 is `1 << 0`, the right
one-hot value for index 0. Expected 0 is the test's own blind spot.

In `wait_for_result`, `window_high` is set only from `rtl_handles`, which
looks for `u_puf.u_core.en_window`. That path does not exist in a flat
netlist, so in gate-level mode `window_high` stayed False on every sample
and `expected = (1 << idx) if (window_high and arm == 1) else 0` was
always 0. Meanwhile `hard_macro_enable_handles` does find `u_rob0..15.en`,
because the macros survive synthesis, and it was reading the enables the
netlist really drives. RTL passed 7 of 7 because there the handle is real.

The fix is the pin E.2 put on `uio[5]` for exactly this. In gate-level
mode `window_high` now comes from it. The RTL branch already checks, on
every cycle, that the pin equals the internal signal, so the two modes
audit the same thing through different windows.

Checked three ways here before committing. RTL, 7 of 7. RTL again with
`rtl_handles` forced to return nothing, which is the netlist's condition,
7 of 7 through the pin path with the sixteen macro pins observed. And that
same blind run with the expectation deliberately pointed at the neighbour
macro fails with `observed 1, expected 2` on the first four samples, which
is the shape of the CI failure with the sign flipped, and the proof the
check is live rather than vacuous. The netlist itself is not run here,
there is no PDK in the container; the next gl_test is what runs it.

## The test workflow had been red since 4 September

`make check` at the repo root, the "self-checking Verilog tests" step:

    src/ro_puf_core.v:100: error: Unknown module type: ro_armc

The root `Makefile`'s `CORE_RTL` never learned about `src/ro_armc_sim.v`,
which `0b586aa` "install rtl" made necessary. Five pushes since, and the
summariser I read the run list through reports every run as passed, so
nobody saw it. One line fixes the compile.

Behind it, two of the three hand-written testbenches in `tb/` were for a
chip that no longer exists. `tb_ro_puf_core.v` had eight oscillators, a
three-bit selector and four Arm B models; it failed with 1206 errors the
moment it compiled. `tb_tt_um_ro_puf.v` expected a fixed thousand-cycle
window and two arms, which is the wrapper before E.2, and failed with 33.
`tb_ro_puf.v` still passed.

Both are rewritten for the chip as it is. The core testbench drives all 48
slots at the fabricated size, sixteen `ro_macro_hard` models on the Arm B
ports the way the top level hangs the real macros, and insists on the
shape the sim models give the counts: Arm A falling with index, Arm B all
equal, Arm C falling with index and faster than Arm A at the same index,
which is how the two models differ. Every cycle of every run it checks the
`active` output against the window and the Arm B enables against one-hot,
and at the end it selects a slot no oscillator fills and requires done to
rise with zero, which is the tied-low slots doing what the core's comment
says they do. The wrapper testbench drives E.2's pin map: `uio_oe` 0x31,
the version bytes through the count port, all 48 slots on the 256 window,
`uio[5]` against the internal window on every cycle, and then window
select 1, which has to double the count to within the one-count boundary
the settle handshake absorbs. It did: 3413 against twice 1706.

Each was pointed at the wrong macro on purpose once and failed by
thousands, then pointed back. `make check` is three passes, and the
firmware's 18 unit tests pass beside it.

## Where that leaves the chip

Builds, prechecks, and the netlist enables the right oscillator. Whether
Arm A holds its coordinates now is the one open question on the chip path
and the next run answers it with a number.
