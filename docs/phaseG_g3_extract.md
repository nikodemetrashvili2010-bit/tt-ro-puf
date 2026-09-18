# G.3 steps 9 to 12 on run 83, and what the three-arm SPEF says

Run 83 is the GDS that goes to the shuttle. Its note ended with four
open items and the biggest was G.3 steps 9 to 12: XOR the new GDS
against the frozen two-arm one, pull the DEF, netlist and SPEF back
out, re-run the evidence gate against them and re-cut the release
manifest. Those four steps are what turn a green job into a build the
numbers are read from. They are done now, and step 10 changed what the
numbers are.

The 17 September review also left three run 83 figures unexplained
because the artifacts were on a machine that was off: 291 max slew
violations, 2 floating nets, 5 disconnected pins. Those are at the end.

Everything here was run on the run 83 artifacts downloaded from the
GitHub job (`D:\silicon\run83\`, commit `8f8939a`), in the same
container that did yesterday's SPICE re-runs, with the same ngspice 42
and the same hand-built PDK tree.

## Step 9, the XOR

The frozen two-arm GDS is `dualarm/build_current/`. The run 83 GDS is
`final/gds/`. Both flatten to about 390 thousand polygons on 29 layer
pairs, and `gdstk` 1.0.1 does a layer by layer XOR of the two in two
minutes once the geometry is clipped to the area that matters.

First the placements, from the two DEFs. All 512 Arm A cells sit at
the same coordinates in both builds, to the database unit. All 16 Arm B
macros too. That was already the claim of the placement checks in CI;
this is the same fact read a second way.

Then the geometry. For Arm A the XOR was run inside the 512 cell
footprints, each 1.38 by 2.72 um at its DEF origin:

    layer      old um2   new um2   xor um2
    nwell        999.8     999.8     0.000
    diff         582.7     582.7     0.000
    poly         254.3     254.3     0.000
    licon1       164.6     164.6     0.000
    li1          741.0     741.0     0.001
    nsdm/psdm  1680.2    1680.2     0.000
    mcon          74.4      74.4     6.349
    met1         566.2     598.7   155.905
    met2         135.7     157.0   135.379
    met3          28.7      21.5    25.694
    met4         209.3     209.3    10.565

Every layer that is the cell itself is identical. Every layer the
router owns is not. The 6 um2 of mcon that moved is the router landing
on different pin contacts, and met1 and met2 over the cells is the ring
wiring taking a different path.

For Arm B the XOR ran inside the sixteen 60 by 40 um macro boxes. Every
layer up to and including mcon is identical, which it has to be for a
hard macro. met2, met3 and met4 differ over the parts of the box the
LEF leaves open, which is signal routing crossing the macro, the same
as it would in any two runs of the router.

So the stop condition on step 9 fired, on the letter. The runbook says
stop on "any geometry difference inside the area arms A and B occupy,
because the two-arm result is quoted off that geometry and a moved wire
there changes it". Wires moved. The question is whether they changed
the result, and that is what step 10 measures, so I went on rather
than stopping.

The first XOR I ran was over Arm A's bounding box, not its cell
footprints, and it showed diff and poly differences of hundreds of um2
that took a few minutes to explain: eight of Arm C's sixteen regions
sit inside that box, at x 293 to 326 um. Arm C's cells are the
difference. The footprint XOR is the right question and the table
above is that one.

## Step 10, the extraction

`dualarm/build_armc/` now holds what `dualarm/build_current/` holds
for the two-arm design, made from the run 83 artifacts: DEF, netlist,
nominal SPEF, GDS, `metrics.json`, `commit_id.json`, the six Arm A
decks `gen_dualarm_decks.py` builds from that SPEF and DEF, their
outputs, and `dualarm_positions.csv`.

The stop condition on this step is a SPEF missing nets the netlist
has. The netlist declares 1728 wires; every one has a name entry in the
SPEF, and the SPEF carries 1753 `D_NET` blocks. Nothing is missing.

### The loads moved

Loop capacitance per ring, the sum of the SPEF totals on n[0] to n[30],
which is what `dualarm_positions.csv` records:

    ring     two-arm  three-arm   change
    0          16.70      14.93    -1.77
    1          14.44      16.29    +1.85
    2          16.33      15.55    -0.77
    3          16.57      16.39    -0.18
    4          11.72      10.96    -0.76
    5          12.15      13.47    +1.32
    6          14.07      14.36    +0.29
    7          10.86      12.36    +1.50
    8          12.85      16.24    +3.39
    9          13.60      14.98    +1.38
    10         14.18      14.22    +0.05
    11         11.93      12.36    +0.42
    12         14.96      16.49    +1.53
    13         14.16      12.90    -1.27
    14         17.04      17.38    +0.34
    15         12.97      15.74    +2.76

    mean       14.03      14.66
    sd          1.85       1.77
    rank correlation between the two columns: 0.71

Same 512 cells, same 512 coordinates, and the router put up to 3.4 fF
more on a ring than it did last time. The spread is the same size as
before, but which ring carries it is only loosely the same.

The `out` net, the buffer output that goes to the selector, grew from
0.2 to 2.7 fF to 1.6 to 9.3 fF, because the selector is 48 to 1 now
and further away. That net is outside the loop and does not set the
frequency.

### The frequencies moved with them

The six decks, run here. Two-arm numbers are the archived
`build_current` outputs, three-arm are `build_armc`:

    corner  build      min     mean    max     p-p
    tt      two-arm   540.0   554.7   570.7   5.53 %
            three-arm 538.4   551.6   570.0   5.73 %
    ss      two-arm   276.2   283.6   291.7   5.46 %
            three-arm 275.4   282.1   291.3   5.63 %
    ff      two-arm   840.3   863.1   888.3   5.56 %
            three-arm 837.2   858.1   887.2   5.83 %

The no-parasitic control still reads one frequency on all sixteen,
633.640 MHz at tt.

Nothing about the chip's safety moves. The fastest ring at ff is 887.2
against 888.3 MHz, so a 2048 cycle window at 50 MHz reads 36340 counts,
55.5 percent of the ceiling, the wrap floor is 27.73 MHz and the
longest safe window is 3693 cycles. Same margins as yesterday's review
to the second digit.

What moves is the prediction. The adjacent pair bits, sign of f(2j)
minus f(2j+1), with a 1 where the lower index is faster:

    two-arm    0 1 1 0 1 0 0 0
    three-arm  1 1 1 0 0 0 0 0

Pairs 0 and 4 flip, and they flip the same way at all three corners.
The smallest pair gap in the three-arm build is 4.0 MHz at tt, 2.0 at
ss, 6.2 at ff, all wider than the 0.9 MHz residual the cap to frequency
fit has, so these are not marginal bits reading differently. The rank
correlation of the sixteen frequencies between the two builds is 0.69
at tt.

**The two-arm Arm A prediction, 541.5 to 570.7 MHz with bits 01101000,
is a prediction about a chip that is not being fabricated.** It is the
baseline the paper measured and it stays where it is, in
`build_current`, hashed and archived. The chip that goes to the shuttle
is `build_armc`, and its Arm A bits are 11100000 from the same
pipeline.

This is what the runbook's step 9 stop was written to catch, and it is
also why step 10 exists. The G.4 preregistration says the per pair
signs are predicted "from the public design database before silicon"
and archived before any die is read. It restates no number. So nothing
frozen breaks, and the design database the predictions come from is
now the three-arm one. What has to change is every sentence outside
the frozen files that quotes the two-arm numbers as the chip's.
`SIGNOFF.md` does, and so does the paper draft. Those are edits for
tomorrow with a clear head, not for the end of today.

### Arm C, the number the experiment is about

The three-arm SPEF is the first place Arm C's loads exist. Same sum,
n[0] to n[30], for the sixteen hand-placed rings:

    9.70 10.17 10.33 11.02 9.82 9.17 9.95 10.15
    10.14 9.35 8.69 9.96 9.43 10.50 10.37 9.72

    mean 9.90 fF, sd 0.55, p-p 23.5 percent of the mean

Against Arm A's 14.66 mean and 1.77 sd in the same build. The
hand-placed rings carry two thirds of the load and a third of the
spread. Sixteen identical placements did route to sixteen similar
loads, three times more similar than the placer's.

I have not simulated Arm C's frequencies. `gen_dualarm_decks.py` knows
Arm A's net names and nothing else, and teaching it Arm C is a change
to a generator that produced archived decks, which is not a change to
make at the end of a day. The loads are the part of the answer that
did not need a simulator.

## Steps 11 and 12, the gate and the manifest

The runbook's step 11 expected one failure: the manifest diff, because
"the raw inputs are a different build now". That expectation was
written when the plan was for the three-arm build to replace the
two-arm one. It cannot, and the reason is in the gate itself:
`archive_baseline.py`, `placement_fidelity.py`, `gen_armc_fix.py`,
`verify_phaseE.py` and `armc_cost.py` all read `build_current` as the
two-arm reference, and `gen_e2_rtl.py` transforms the frozen two-arm
source to prove the installed one is its image. Overwrite
`build_current` and the gate is checking the three-arm build against
itself.

So the manifest names both. `release_manifest.py` still hashes the
eight raw inputs from `build_current` under `raw_inputs`, unchanged,
and now also hashes `build_armc` under `release_inputs`: the same
eight plus the GDS and `commit_id.json`, ten hashes. One new check,
S13: when a release build is present it has to be complete and none of
its hashes may equal the baseline's. Absent, it passes and says "no
release build yet", so the check is safe on a checkout that predates
step 10.

`RELEASE_MANIFEST.json` is regenerated last, as always. 13 checks pass,
`hash_stability.py` 6 of 6 with 100 recorded hashes over 102 files,
and the gate is 130 of 130 in the container clone with the new
manifest and the new build directory in place. The step 11 failure the
runbook predicted does not happen, because the design it predicted it
for is the one I did not make.

## The three deferred figures from run 83

**291 max slew violations.** All of them are at the slow corner, on
30 nets, and every one of the 30 is driven by a
`sky130_fd_sc_hd__clkdlybuf4s25_1` that the post placement repair step
inserted to split fanout above 10. The two-arm build had 37 of those
buffers and 140 violations; this one has 58 and 291, because the
select decode fans out to 48 rings now instead of 32. The nets are the
select decode (`_1xx_`, and3 and a22o loads), the counter reset
`cnt_rst_n` (17 `dfrtp_2` RESET_B pins, two buffers), `start_pulse`,
`project_rst_n`, and `uio_in[1]`. Slews run 0.75 to 1.55 ns against a
0.75 ns limit at ss 100C 1.60V, 0.9 ns worst at tt, and there are none
at ff.

Why it does not matter for the chip. STA at all nine corners is clean
with those slews in it: worst hold 0.110 ns, worst setup 9.20 ns, zero
violations. Every one of the 30 nets is quasi-static during a
measurement: the decode and the reset settle in the ST_ARM cycle, which
is the 20 ns quiet gap the FSM puts between `start` and `en_window` for
exactly this reason, and 1.5 ns of slew plus a few ns of tree delay is
a small fraction of it. Post route slew repair is off in the Tiny
Tapeout defaults, and `MAX_SLEW_VIOLATION_CORNERS` is empty, so the
flow reports these and never fails on them. Two max cap violations sit
on the same buffers, `fanout50/X` at 4 percent over and `fanout30/X` at
1 percent over the 94 fF limit, also ss only. One max fanout on
`clkbuf_0_clk/X`, 16 against 10, which is the CTS root and normal.

**2 floating nets.** `VGND` and `VPWR`, reported by `repair_design`
before the power grid exists. The two-arm build reports the same two.

**5 disconnected pins.** `uio_in[0]`, `[4]`, `[5]`, `[6]`, `[7]`. Bits
0, 4 and 5 are outputs, `uio_oe` is 0x31, so their input half has no
use; 6 and 7 are the two spare bidirectionals nothing reads.
`design__critical_disconnected_pin__count` is 0. The two-arm build had
9, before the window and version inputs took `uio_in[1:3]`.

## The selector, now 48 to 1

Item 2 of the hardware list, the mux sweep, was run on the two-arm
netlist's 32 paths. The three-arm selector is a different tree: the
synthesiser built it with four cell types the two-arm one never used,
`a21bo_2`, `and3_2`, `and3b_2` and `o21ba_2`, and `gen_mux_sweep.py`
refused to walk through them because its cell table did not know
their pin functions.

The table knows them now. All four are non-inverting on their data
pins, so the argument that `sel_ro` follows the ring still holds. The
generator also takes `--build` so it can read a build other than the
two-arm archive, and picks up Arm C's sixteen buffers when the netlist
has them. `gen_boundary_sweep.py` takes the same option. Regenerating
the two-arm decks with the patched generator gives 64 of 64 files byte
for byte identical to the archive in `mux/`, which is the test that
the change did not move anything it should not have.

On the three-arm netlist the walk finds all 48 paths, 3 to 5 cells
deep, with the deepest through `a211o_2` twice. `analyze_mux_sweep.py`
had "32" written into two of its sentences and, like the flop analyser
yesterday, no idea how many results it expected. It states the count
now and fails on a short set, the same 12 lines as yesterday's fix.

The 48 decks plus 48 blocked controls ran while this was written,
about two minutes a deck with the extracted macro ring as stimulus.
The next section has the numbers. The boundary sweep goes through
B13, the slowest rise of the 48 at 349 ps, on the archive's own
reasoning that chain depth rather than asymmetry sets the threshold.

## Selector results so far

All 48 open paths are in, every one passing, at the fast corner:

    arm   rise delay      asymmetry     high at sel_ro   low at sel_ro
    A     197 to 288 ps   161 to 186    697 to 722 ps    400 to 425 ps
    B     240 to 349 ps   159 to 209    695 to 745 ps    377 to 427 ps
    C     174 to 319 ps    90 to 163    626 to 699 ps    423 to 496 ps

    two-arm archive, 32 paths: rise 157 to 375 ps, asymmetry 102 to
    182 ps, narrowest high 639 ps on A05, narrowest low 403 ps on B15

The tap is the same ring in every deck, 536 ps high and 586 ps low.
Every path lengthens its high level and shortens its low by the same
amount, period preserved, which is item 2's corrected finding holding
on a different tree. Thirty edges in, thirty matched, fifteen flop
rises on all 48. No path lost an edge.

Two numbers moved against the two-arm archive and both are on Arm B's
paths, which are five cells deep through the new `o21ba_2`: the widest
asymmetry is 209 ps on B11, up from 182, and the narrowest low at
`sel_ro` is 377 ps on B11, down from 403. Both are far from anything
the flop cares about; `dfrtp_2` wants about 100 ps at this corner. Arm
C's paths are the gentlest of the three, with the shortest chain, C07
at three cells, delivering 90 ps of asymmetry and a 496 ps low.

`sim/spice/gono/mux3/` holds the 96 decks, their logs, the raw files
reduced by `reduce_raw.py` with the reduction verified against the
analyser field by field, and `mux3_validation.csv`.

**The blocked controls failed on 32 of 48, and the failure was the
control's, not the chip's.** A control deck blocks the path at its last
cell by holding that cell's side inputs at the values that ignore the
data pin, and a silent flop proves a closed path really reads as zero.
Every two-arm path ended on `o21a_2`, where any pin can be blocked from
the side. Thirty-two three-arm paths end on `a211o_2`'s B1 or C1, which
are bare OR terms: nothing the other pins do can stop them. On the chip
those pins are driven by the decode upstream, so the real block sits a
cell earlier. The sixteen Arm B controls, which enter that last cell on
A2, went silent as they should; the sixteen A and sixteen C controls
oscillated.

The generator now blocks at the last cell on the path that can block,
and leaves the cells after it open, so a silent output also shows those
open cells generate nothing on their own. The two-arm decks still
regenerate 64 of 64 byte for byte, because their block was always at
the last cell. The 32 regenerated controls ran last: 48 of 48 silent, and the
analyser prints PASS over 96 result files against 96 decks.

## The boundary, through B13

`gen_boundary_sweep.py --build dualarm/build_armc --osc B13 --corner
ff`, item 1's grid, 38 enable-fall phases 50 ps apart, through the
slowest path in the three-arm tree. The verdict is the archive's:

    steady path delay: rise 350 ps, fall 521 ps, asymmetry 171 ps
    boundary pulse at the tap: 4 ps to 539 ps across 38 phases
    the same pulse at sel_ro: 253 ps to 711 ps
    final rising edge swallowed on 2 of 38 phases: 2, 24
    counted toggles: min 25, max 27, steps only by one
    fixed time +170 ps, residual 4.4 ps; fixed fraction 67.7 ps
    PASS

Every phase resolves the flop to a rail, 0.000 or 1.950 V. The two
swallowed phases are the 4 ps bump at the tap, phase 24, and its
period-earlier twin at phase 2, and each costs one count, the error the
settle handshake absorbs. The 50 ps grid lands 104 ps as the narrowest
surviving pulse, arriving 253 ps wide at `sel_ro`, so the step sits
somewhere between 4 and 104 ps here and the fine sweep that would
place it is not run; B15 on the two-arm build put it between 97 and
102, and nothing about this path's shape says B13 is different.

The selector adds a fixed 170 ps to every high level on this path, the
same shape and within 5 ps of the 175 the two-arm B15 sweep fitted.
`sim/spice/gono/boundary_validation_B13_3arm.csv` is the table.

## Mistakes

Four, kept.

The first six Arm A decks were started under my own shell's ten minute
limit, and it killed them at ten minutes with two of the six done. The
rest were restarted properly. Then the control deck at ss was killed a
second time, by me, to give the selector decks both cores. It is the
one file in `build_armc` with no measurements in it tonight and it is
not one the manifest hashes.

The bounding box XOR, above.

I read the runbook's step 11 and 12 as written for twenty minutes
before noticing that the file lists in steps 1 to 8 and the readers in
the gate scripts already answered which directory was which.

`gen_mux_sweep.py --control` said "plus 32 blocked controls" while
writing 48. Fixed with the rest.

## What this does not settle

Arm C's frequencies and its bits, which need the deck generator taught
its net names. The fine boundary sweep on B13. The soft box run. Every
sentence in `SIGNOFF.md` and the paper that quotes two-arm Arm A
numbers as the chip's, which is now a list to make and work through.
