# The boundary-through-selector sweep and the push

*One of the run notes indexed in [`run_steps.md`](run_steps.md), which says what
they are and what they are not evidence of. Paths are left as they were run.*

Run 2026-08-02 at the fast corner. This finishes what item 2 opened on 07-31 and
corrects item 2 itself along the way.

## What was asked

Item 1 dropped the enable across a ring period and watched the first counter
flop, clocked straight from the ring tap. Item 2 pushed a steady ring through all
32 selector paths into the same flop, with the enable never falling. Each half
checked, the combination not, and the combination is what the chip does.

## What I got wrong first, and what item 2 got wrong

I started by arguing that item 2's prediction was unsafe. It had multiplied a
175 ps boundary pulse by a 25% shortening to get 131 ps, and I said shortening is
a fixed number of picoseconds rather than a percentage, so the answer should be
175 minus 134, or 41 ps.

Then the first run came back with the pulse 182 ps **wider** after the selector
than before it. A selector cannot widen a pulse. That impossible number is the
only reason I went and looked at the waveform, and the waveform said we were both
wrong for the same reason.

Rise and fall cross a path at different speeds. That difference moves each
trailing edge and leaves the leading edge alone, so one polarity grows by exactly
as much as the other shrinks. On B15 the tap runs 539 ps high and 583 ps low
while sel_ro runs 721 ps high and 401 ps low, period 1122 ps at both nodes to the
picosecond. So the narrowest level at the tap is a high, the narrowest at sel_ro
is a low, and item 2's analyzer had been comparing one against the other. All 32
paths, not just B15. Re-running the 32 decks with the polarities kept apart gives
rise delays identical to the old run and asymmetries of 102 to 182 ps, every one
positive. No path shortens a high level.

The counter's first stage is a rising-edge flop, so every selector path hands it
more margin than the tap did.

## The result

Eighty-nine phases. Thirty-eight through B15, thirty-eight through A05, thirteen
more through B15 at 5 ps steps. Every single one resolved the flop to exactly
0.000 V or 1.950 V.

    path   asymmetry   swallows      passes      arriving   full gain by
    B15      182 ps      97 ps      102 ps        144 ps       380 ps
    A05      102 ps      15 ps       69 ps        160 ps       128 ps

B15 is the deepest and slowest chain, five cells through a mux4_2 at 360 ps rise.
A05 is four cells at 226 ps. A05 adds the least width of any path and still
passes a narrower pulse, so chain depth decides the threshold rather than
asymmetry does. Both facts come from the same response time: the chain that needs
a wider pulse to express its full asymmetry is the chain that loses narrow ones.

The step at 97 to 102 ps is sharp enough that the 5 ps sweep found nothing in
between. That is the real answer. The selector behaves as a filter, so the flop
is either handed a full pulse or handed none, and never gets the chance to sit at
mid rail. In every sweep the phases that lost the pulse were the phases where the
count steps up, so the step lands one phase later rather than a count going
missing.

## What is still open on this

Fast corner only. And B00 is harder than B15 on both counts, 375 ps of rise
against 360 and 166 ps of asymmetry against 182, so B15 is the hardest path I
measured and not the hardest one there is.

## The lesson I want to keep

Item 2's four synthetic checks all passed while the polarity mistake sat in the
middle of the analysis, because not one of them built a path where a high and a
low behaved differently. The checks were the problem, not the analysis. There are
three now and the first plants exactly that case. Both sweep analyzers also run
in CI on `--selftest`, which needs no PDK, so this cannot rot quietly.

## Push it

### 0. Delete the debug copy first

It is a few MB inside `sim/spice/gono/` and `backup_to_repo.sh` copies that whole
tree, so it has to go before the copy, not after.

    rm "/mnt/d/silicon/silicon chip/sim/spice/gono/bnd_00_debug.raw.txt"

### 1. Give the first sweep's csv its proper name

    mv "/mnt/d/silicon/silicon chip/sim/spice/gono/boundary_validation.csv" "/mnt/d/silicon/silicon chip/sim/spice/gono/boundary_validation_B15.csv"

### 2. Copy the working tree into the clone

    cd "/mnt/d/silicon/silicon chip" && bash backup_to_repo.sh

Ends with `DONE. Now commit and push in GitHub Desktop.` and lists nothing over
20 MB.

### 3. Three commits in GitHub Desktop

**Commit 1, the correction.** `sim/spice/gono/analyze_mux_sweep.py` and
`sim/spice/gono/mux_validation.csv`.

    Fix the selector level comparison, which measured a high against a low

**Commit 2, the new check.** `sim/spice/gono/gen_boundary_sweep.py`,
`analyze_boundary_sweep.py`, the three `boundary_validation_*.csv` files, and
`.github/workflows/gds.yaml`.

    Sweep the ring-stop boundary through the selector, on both extremes

**Commit 3, the writing.** `docs/hardware_todo.md`, `SIGNOFF.md`,
`REPRODUCIBILITY.md`, `sim/spice/gono/README.md`.

    Record the boundary result and correct what item 2 claimed

### 4. One push at the end

Then check the gds action goes green. The `archived-evidence` job now runs both
`--selftest` calls, so a red one there is a real failure and not the usual
`gl_test` noise.
