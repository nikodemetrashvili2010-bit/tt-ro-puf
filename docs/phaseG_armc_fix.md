# Arm C gets its placement

16 September. `chip/gen_armc_fix.py`, `chip/ARMC_FIX.json`,
`src/armc_fix.tcl`, and a third line in `src/pdn_hook.tcl`. Nothing has
built with any of it yet.

## Where it stood this morning

Run 80 on the 12th held all 512 Arm A cells FIRM from the PDN hook, and
the same day `armc_template.py` scored the hand-placed Arm C and drew
the sixteen regions it would go in.

Odd state for an arm to be in. A scored template, a chosen layout, and
no file the flow reads.

`chip/armc_place.tcl` exists, but it is the August file for the region
approach, 512 `place_cell` lines that no step will ever source, and the
gate still regenerates it as a record. `src/pdn_hook.tcl` sourced the
PDN recipe and Arm A, two lines.

So a build started this morning would have synthesised the sixteen Arm
C rings, found nothing that placed them, and handed them to the placer.
Arm A under a second name. That is the one outcome P11 in
`gen_placement_cfg.py` was written to refuse back in August, and P11
would not have fired, because it only watches the Arm A hook.

## What the file is

One proc, `armc_fix`, the same four calls as `arma_fix`: find the
instance, set orientation, set location, set FIRM, count it. Then 512
calls, and a guard that errors unless the count is 512.

Step 21, like Arm A. After the rows are cut and the taps are in, before
anything is placed. The 11th and run 80 already settled that FIRM at 17
breaks row cutting and PLACED at 33 gets moved, so there was nothing to
decide there.

The coordinates come out of `chip/ARMC_TEMPLATE.json`. The chosen
layout gives sixteen region origins, three x positions at 253.46,
279.22 and 304.98 um in the strip beside Arm A, eight regions in the
rows from 27.2 to 59.84 and eight in the rows from 174.08 to 206.72.
The template gives the grid inside each one: four rows, eight cells a
row, three sites each, sites 12 to 35 of the 56, with sites 11 and 39
left to the well taps. Region i takes ring i.

Every region's first row is FS, so the rows go FS, N, FS, N, and the
hook writes MX and R0, the OpenDB names, because the Tcl binding
refuses the LEF ones. Same as Arm A.

Why `armc_fix.tcl` and not `armc_place.tcl`: that name is taken. Two
files with one name, one live and one an August record, is how the
wrong one gets read.

## The one decision

The template left the order of the 32 cells inside the grid as a
default, a serpentine with the output buffer at the very end, after
inverter 29 on the bottom row. Run 80's writeup called that the reason
the build estimate was four days and not three. Today it got looked at.

Arm A is the yardstick. The placer put those sixteen rings down with
no help, so wherever it put the buffer is what an unconstrained layout
does with a buffer, and Arm C is supposed to differ from Arm A in
placement freedom and nothing else. From the frozen DEF:

    buffer to the inverter it taps   1.8 to 4.6 um, median 3.0
    feedback, inverter 30 to the NAND    1.4 to 7.0 um, median 3.1
    chain neighbours                 1.4 to 7.4 um, median 2.3
    footprint, median                18.6 by 16.3 um, 4 to 8 rows

Three orders against that, all on the same 8 by 4 grid:

    row-major, buffer last     buffer 5.4   feedback 11.6   worst step 10.0
    serpentine, buffer last    buffer 5.4   feedback  8.3   worst step  2.7
    serpentine, buffer by tap  buffer 2.7   feedback  8.2   worst step  3.1

Row-major is out on its own numbers, a feedback wire crossing the whole
template.

The two serpentines differ in one thing, where the buffer sits. At the
end of the walk it is two rows from the inverter it taps, 5.4 um,
further than any of Arm A's sixteen. Moved to the slot right after
inverter 14 it is one row up, 2.7 um, inside Arm A's range and near its
median. That costs one chain step of 3.05 um where the walk skips over
the buffer's slot, still under Arm A's worst neighbour gap of 7.4.

So: serpentine, buffer beside its tap node. The feedback closes over
three rows, 8.2 um, which is above Arm A's worst of 7.0, and there is
no order on a 4-row grid that does better without breaking something
else. It is recorded as one string in the generator and K08 fails if
the rendered file stops matching it.

None of which is a routed result. It is a placement that puts each
wire's endpoints about where the placer put Arm A's. Whether sixteen
copies of it route to sixteen similar loads is the experiment.

## Checks

Twelve on the way in, five on the way out.

K01 to K05 read the frozen DEF and ask whether the sixteen regions are
real places: every one of their 64 rows exists at full width in the
phase the template expects, the taps inside them stand on sites 11 and
39 and nowhere else, no Arm A cell, macro or endcap stands in the cell
sites, and none of the sixteen overlaps the soft box round Arm A. K06
to K08
are about the 512 cells: the names are the ones `ro_armc.v` produces,
32 a ring and each once, none of them an Arm A name; every cell is on
its row's site grid inside its region and no site is used twice; the
order is the declared one in all sixteen rings.

K09 reads the hook back through its own parser rather than trusting the
renderer, and holds it to the 512 coordinates, the FIRM, and the guard.
K10 reads the wrapper and wants exactly three live lines in order. K11
is the regions against each other and against the recorded bounding
box.

K12 renders twice from shuffled input and wants the same bytes.

`gen_placement_cfg.py` reads the wrapper too. Its P16 wanted two lines;
it wants three now, with Arm A before Arm C, and two new faults in its
selftest cover a dropped third line and the arms the wrong way round.
P11 keeps refusing an Arm C line in the Arm A hook and its name says
where Arm C lives instead.

Then the other direction. `--verify-def` takes the DEF a build wrote
and asks, per cell, whether it is present, at its coordinate to the
dbu, in its orientation, not UNPLACED, and still the master the RTL
asked for. K13 to K17, the same five questions `placement_fidelity.py`
asks about Arm A, and the gds job runs it after the Arm A step and puts
the answer in an annotation. It never fails the job.

First time it says anything real is the next build.

Selftest: a fixture the size of the real thing in counts, sixteen
regions, 512 Arm A cells, sixteen macros, 46 rows of 1100 sites with
taps every 56 in alternating phase. Eleven planted faults on the way
in, each tripping exactly one check, and five planted in a built DEF
for the way out.

## Two mistakes today

The fixture started at two regions and 64 cells, and the clean run
tripped K01, K04 and K06 at once, because those three carry the real
chip's numbers, sixteen and 512, and the fixture did not. Either the
checks loosen to whatever the fixture has or the fixture grows.
Loosening a check to make a test pass is the wrong way round, so the
fixture grew.

Second, the generator's docstring first said the default order put the
buffer about 11 um from its tap. That was the feedback distance of the
row-major walk, not the buffer distance of anything. Re-derived from
the grid: 5.4. The table above is from the re-derivation, not the
draft.

## What moved

The wrapper, three lines and a comment that now names both hooks.
`ARMC_TEMPLATE.json`, whose comment still said neither layout was
chosen four days after one was, and whose order string now says what
was decided and where. `PLACEMENT_CFG.json`, which also picked up a
stale hash of `pdn_cfg.tcl` that would have held the gate red on the
next push regardless.

Also the runbook's placement step, which now pins both arms and stops
on either, and `info.md`, which was still describing the
region-constrained Arm C that never existed, and that page becomes the
datasheet. The manifest last, with `ARMC_FIX.json` as the nineteenth
produced artefact.

Four more commands in the gate, 130. All 130 pass here.

## Open

The next build, which is the only thing that says whether 512 of 512
held and whether the rows outside Arm A's 37 have their taps where the
two-arm DEF has them. The soft box, still kept for one more run so the
change it makes can be seen on its own. Pages. TTSKY26d, unchanged.
