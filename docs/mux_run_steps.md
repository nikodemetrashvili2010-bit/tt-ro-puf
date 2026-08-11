# The selection-path check and the push

*One of the run notes indexed in [`run_steps.md`](run_steps.md), which says what
they are and what they are not evidence of. Paths are left as they were run.*

Hardware item 2, run 2026-07-31 at the fast corner.

**Corrected 2026-08-02. Do not reuse the level numbers below.** The 9.8% to 25.0%
shortening and the 403 ps narrowest level compared a high level at the tap
against a low level at sel_ro. No path shortens a high. See
`boundary_run_steps.md` and item 2 of `docs/hardware_todo.md`. The delays and the
edge counts on this page are unaffected and were reproduced exactly.

## What was asked

Every oscillator reaches the counter through a synthesized selector. A fixed
delay through it is harmless, because a delay cannot change a frequency. A path
that swallows a pulse is not harmless at all, because that oscillator would read
slow and the difference would belong to the routing rather than to the ring.

## What the selector turned out to be

Not a tree. The 32 sources reach `sel_ro` through three to five cells of six
types, and no two are wired the same way. Ten paths are three cells. Eight of the
Arm B paths pick up a mux4_2 and run five deep. Checking one path would have
proved nothing about the other 31.

## The result

All 32 paths carried all 30 judged edges into the flop, the flop toggled at half
that rate on every one, and all 32 blocked controls were silent.

    cells  mux4    n   mean delay   delay range     narrowest level
      3     no    10     173.9 ps   157 to 188 ps   415 to 476 ps
      4     no    12     213.5 ps   198 to 226 ps   423 to 483 ps
      5     no     2     252.5 ps   249 to 256 ps   437 to 438 ps
      5    yes     8     367.2 ps   360 to 375 ps   403 to 419 ps

Excluding the mux4_2 paths, delay tracks cell count at 39.4 ps per cell on a
56 ps intercept, correlation 0.944. The two five-cell paths without a mux4_2
measure 252.5 ps and the line predicts 252.8. The mux4_2 alone costs about
114 ps. Total spread 218 ps, none of which reaches the measurement.

Levels shorten by 9.8% to 25.0%. The narrowest arriving anywhere is 403 ps
against a 563 ps half period.

## What it opened

Item 1's boundary sweep clocked the flop straight from the ring tap, with no
selector in between, and its shortest pulse was 175 ps. Through the worst path's
25%, that arrives as roughly 131 ps. Each half is checked and the combination is
not. Repeat the item 1 phase sweep through path B15 next. That is the worst one.

## Two mistakes worth keeping

The first version of the generator hardcoded sky130 pin order from memory. Now it
reads every port order from the PDK's own subckt lines and stops if a cell or pin
is missing, so a wrong order cannot build a quiet, wrong deck.

The first version of the analyzer failed on A00 and was wrong to. It compared
totals over a fixed window, so the last ring edge had no time to cross the
selector before the transient ended and got counted as lost. Same lesson as item
6, a pass condition that quietly assumed the window lined up with the period. It
matches each edge to its partner now.

## Push it

### 1. Copy the working tree into the clone

In WSL Ubuntu:

    cd "/mnt/d/silicon/silicon chip" && bash backup_to_repo.sh

It ends with `DONE. Now commit and push in GitHub Desktop.` and lists any file
over 20 MB, which should print nothing.

### 2. Two commits in GitHub Desktop, then one push

Open the `tt-ro-puf` repository. Tick only the listed files for each commit,
write the message, click commit. Push once at the end.

**Commit 1, the check itself**

    sim/spice/gono/gen_mux_sweep.py
    sim/spice/gono/analyze_mux_sweep.py
    sim/spice/gono/mux_validation.csv

Message: `Check every 32-to-1 selector path at the fast corner`

**Commit 2, the writing**

    docs/hardware_todo.md
    SIGNOFF.md
    REPRODUCIBILITY.md
    sim/spice/gono/README.md

Message: `Item 2 passes, and hands the boundary pulse question back to item 1`

### 3. After the push

Green on gds, precheck and test is what matters. `gl_test` and `viewer` do not.

The 64 raw waveform files stay in `/tmp`. They are far too big to commit, which
is why `mux_validation.csv` exists, and REPRODUCIBILITY now carries the commands
that rebuild them.

## Still local, still yours to do

The GitHub About description and the social preview still carry the old
dispersion wording. Only you can edit those.

The top-level `src/` folder in the working tree is a stale older revision that
still has the `gated_ro` gate on the counter clock. It does not ship, because
`backup_to_repo.sh` copies `dualarm/src/` into the repo instead, and the built
netlist confirms the flop is clocked straight from `sel_ro`. Worth deleting so it
cannot confuse you later.
