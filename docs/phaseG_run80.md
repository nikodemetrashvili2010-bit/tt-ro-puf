# Run 80: Arm A holds, and where Arm C could go

12 September, commit `74b89e0`, pushed by Nikoloz at eight minutes past
midnight. The first build with the hook.

    archived-evidence   green   1m 01s
    gds                 green   4m 26s
    precheck            green   2m 22s
    gl_test             green     48s
    viewer              red       13s
    test / test         green     34s

Runs 78 and 79 never got this far. Both died in the gate inside a minute,
on the one line `diff /tmp/release.json chip/RELEASE_MANIFEST.json`,
because the workflow file in the clone still counted 121 commands while
the manifest said 122 and then 123. The tell is a gds run of about a
minute with everything after the gate skipped.

Run 80 had the workflow file. The gate passed 123 of 123.

`viewer` is still Pages. That is one click in the repository settings and
it is Nikoloz's.

## The annotations

Three, and I quote them as the run page shows them.

    Rings: 32 of 32 intact
    every loop is 1 nand + 30 inv + 1 buf with nothing else on it

That is the ring walk from the 10th, on the three-arm netlist for the
first time. Sixteen Arm A loops and sixteen Arm C loops, each found by
connectivity, each exactly the circuit the RTL describes, no buffer
inserted on any of them.

    Arm A: 512 of 512 at their coordinate, orientation and cell

All of them. Run 75 had 64 in place, runs 76 and 77 had 507, and the
reason for the five was named on the 11th: an enable decoder and a clock
buffer standing on two ring sites, with legalization handing the larger
cell the site.

FIRM at step 21 ends that. The five moves are gone, no cell is rotated,
and no cell was retyped, so F06 passed on its first outing as well.

`gl_test` went green, and one failing testcase turns that job red, so all
eleven passed: the seven from run 77 plus the four pin-function tests the
10th added.

The third annotation is the box report, which is longer.

## The box, with Arm A fixed

    box 247480,70720 to 307740,171360 holds 74 taps, 1140 fillers
      and 24 other cells
    fanout45           clkdlybuf4s25_1  SOURCE TIMING  at 256680,70720
    fanout27           clkdlybuf4s25_1  SOURCE TIMING  at 266800,70720
    _676_              dfrtp_2                         at 306820,76160
    _301_              and3_2                          at 306360,84320
    _449_              a22o_2                          at 306360,92480
    _305_              and3_2                          at 303600,100640
    fanout42           clkdlybuf4s25_1  SOURCE TIMING  at 304980,103360
    _334_              and3_2                          at 304980,114240
    _456_              a22o_2                          at 306820,125120
    clkbuf_4_11_0_clk  clkbuf_8         SOURCE TIMING  at 284740,130560
    clkload1           clkbuf_4         SOURCE TIMING  at 285200,136000
    _321_              and3_2                          at 307280,138720
    ... and 12 more in the box

Twenty-four, against eleven on run 77 and 93 in the two-arm build. The
filler count went from 1160 to 1140 to make room.

More cells in the box, not fewer. I think the reason is plain.

On run 77 the Arm A cells floated through global placement and were set
down at their coordinates afterwards, so nothing was attached to those
sites while the placer worked. Now they are fixed before global
placement starts. Every enable decoder has one wire into a ring NAND
that is already at its final site, and every output mux has one wire
out of a ring buffer that is too.

The soft box is a density penalty. A short wire to a fixed cell beats
it, so more of the decode logic settles against the rings than before.

Where it settled matters. Ten of the twelve named stand on the box's
right edge, x from 303600 to 307280 against an edge at 307740, or on its
bottom row at y 70720.

None of the 24 overlaps an Arm A cell. If one did the build would have
died at step 32 with the cell named. So whatever sites they took were
sites Arm A had left free in those rows.

The other two are clock tree cells in the middle of the box,
`clkbuf_4_11_0_clk` and `clkload1` at x 284740 and 285200 on rows 130560
and 136000. That is between rings.

`_334_`, the decoder that sat on ring 9's `g_inv[26]` on run 77, is now
at 304980,114240: twelve microns to the right and one row up, off the
ring, on the edge with the others.

Twelve are not named. The reporter names twelve and stops, a limit I set
on the 9th when the box held eleven. It is 40 for the box list now, the
moved and rotated lists keep their twelve, and the next run names all
of them.

With Arm A fixed the box holds nothing in place any more. What it does is
keep the middle of the box emptier than it would otherwise be, two clock
cells excepted, and the paper has to say the neighbourhood of Arm A was
shaped by it. Whether it stays is settled for the next build and not
beyond it; the last section says why.

## The amendment's question

`chip/G2_AMENDMENT.json`, written on the 7th, chose the hand-placed Arm C
and said the choice hung on one question: does the flow accept 512
standard cells placed FIRM. It expected the answer to come from
`MACRO_PLACEMENT_CFG` at step 17.

Run 74 said no to that route. Run 80 says yes to a different one, the
PDN hook at step 21. The amendment now carries a `resolution` block
dated today that says so and leaves everything above it as written.

It also said the option had to be scored against H1 to H6 before it was
built, because the same sixteen rings of 32 cells were scored on 27
August and an expectation is not a score. That is done, and it is the
first half of what `chip/armc_template.py` does.

    H1  pct_of_free           27.25  <=  75.0   margin 47.75
    H2  tiles_required            4  <=  4      margin 0
    H3  existing_oscillators     32  ==  32
    H4  new_oscillators          16  >=  8      margin 8
    H5  extra_input_pins          1  <=  1      margin 0
    H6  build_days                4  <=  5      margin 1

The area is sixteen template regions of 280.27 um2 plus 221.75 um2 of
added decode, over the 17272.8 um2 of free row area E.1a measured. The
mean-density Arm C scored 27.3 percent on 27 August.

Five of the six fields come out of files already on disk and the script
re-derives them rather than copying them. The sixth does not. The build
days are my estimate, written today, not frozen with the rule, and the
record says so in its own field.

I first wrote three and changed it to four before the day ended. Three
was Arm A's day plus a spare, and Arm A's coordinates came out of a
build that had already routed. Arm C's do not: the order of the 32 cells
inside the template is a default nothing has checked, and a template that
routes badly costs a rebuild. Four is the honest number and it still
clears H6, by a day instead of two.

## The taps

The second half of the script is the part nobody had to think about
before, because nobody was placing Arm C by hand before.

`gen_armc.py` drew sixteen regions on 30 August for a placer that would
put 32 cells inside each one and work round whatever else was there. Its
docstring says so: filler, decap, taps and the control logic are all
re-placed by the rebuild, so they constrain the total area and not the
position of anything. For a region constraint that was right.

A template placed FIRM at step 21 is different. The well taps go in at
step 19, one per row every 56 sites, and they are fixed. A template cell
set down on a tap site is an overlap, and the legalizer refuses it the
way run 73 died, DPL-0033 at step 32.

So the template has to hold its tap sites free. And for one template to
serve sixteen regions, every region has to see its taps at the same
offsets.

The frozen DEF says where the taps are. Pitch 25.76 um, which is 56
sites. Alternate rows staggered by 28. Five rows carry both phases: the
two ends of each band, and the one full-width row in the seam between
the macro rows at y 62560.

And the strip beside the macro block is on a different phase from the
full-width rows above and below it, because its rows start at x 245640
and not at 2760. Modulo 28 sites, a strip tap sits at 2 and a band tap
at 6.

The sixteen recorded regions, read against that grid, show fourteen
different tap patterns. Eight of them overlap Arm A's soft box, which
was known. Two, the ones at x 2.76 um, start on the endcap at the left
end of their rows, which was not. So they cannot be used as they stand,
for a reason that has nothing to do with where they are on the die.

A region is exactly one tap pitch wide. That was a coincidence of the
density arithmetic and it turns out to be the useful fact: any 56-site
window on a single-phase row holds exactly one tap, and a window that
starts on the right residue holds it at a known offset.

The template holds sites 11 and 39 of its 56 free in every row, which
covers both phases and the boundary rows, and packs the eight cells a
row needs into sites 12 to 35 between them.

Eleven is not arbitrary. Three templates fit side by side in the strip's
182 usable sites only if the first starts within its first fifteen. The
tap phase fixes where a template may start modulo 28. Together those
put the reserved offset between 11 and 25, and the smallest wins.

I had worked that range out by hand as 12 to 25 before the script said
11. The hand count was one site short at the far end of the row. The
script was right.

Rows alternate N and FS, and a template that starts on an N row is the
mirror of one that starts on FS. Every candidate starts on an FS row,
the row Arm A's bottom cells sit on.

## Two layouts

With those rules the strip beside Arm A holds 33 templates, twelve of
them inside Arm A's box between its rings and 21 outside it. The bands
hold twelve each. Two layouts are recorded, and the last section of this
writeup says which one the build is to use.

Column. All sixteen in the strip, nearest Arm A's centroid first, none
inside its box: eight below it in the rows from 27.2 to 59.84 um and
eight above in the rows from 174.08 to 206.72, three abreast at x
253.46, 279.22 and 304.98.

The sixteen span 77 by 180 um, which is 23 percent of the die's width
and 80 percent of its height. Their centroid is 15.7 um right of Arm A's
and 2.6 um above it. The farthest is 89 um away.

Three-part. The eight nearest from the same pool, four in the bottom
band and four in the top, spread across the width the way `gen_armc.py`
spread them, re-sited to the template's phase. Span 320 by 212 um, 96
and 94 percent of the die. Centroid 49 um left of Arm A's and 9 um
below; the farthest region is 270 um away.

What the choice turns on is on record twice, and the two records
disagree.

`gen_armc.py` argued for the split: Arm A is pinned in the strip, so
putting all of Arm C somewhere else aliases the treatment with die
position, and splitting Arm C puts that contrast inside one arm where it
can be measured.

The design audit of the 8th, finding 2, argued the other way. M4 is Arm
C's spread over Arm A's. A gradient sampled across the whole die by one
arm and across one block by the other inflates that ratio, and a ratio
not below one reports a null.

Both are right about something. The column removes the width confound
and most of the height one, not all of it, since Arm A spans 100 um of
height and the column spans 180.

## What was checked, and what was not

Fifteen checks, fourteen planted faults, each tripping exactly one.

T09, that a chosen region sees its taps only on the reserved sites, has
no fault of its own. A tap anywhere else in a 56-site window is a tap
off its row's phase, and T05 catches that first, so T09 can only fail
after T05 has.

Getting there took four tries and each one was a fixture fault rather
than a check fault. The first fixture put its two rings at site 600 in
rows that end at site 306, so the clean run passed while holding nothing
it claimed. The planted tap for T06 was appended after `END COMPONENTS`
and the parser never saw it, so the fault tripped nothing. Then it
tripped T12 instead, because a tap at the same x as an inverter gave the
inverter a packed width of zero.

And T09 first required a tap in every row of a region. The recorded
regions showed that is false at a row's edge, where the first tap can
be 56 sites in.

T14, added last, first asked whether the chosen layout found all sixteen
and fired alongside T07 on the same fixture, because the chosen layout is
the column and T07 already owns the column's count. It asks only whether
the name resolves to a layout now. That is the rule about a new check
reaching into what an old one owns, and it has been broken once before,
by P15 yesterday.

The numbers above were re-derived with throwaway code that imports
nothing from the script: a byte array per row instead of sets, its own
group walk, its own packing. Phases 2 and 6, 33 templates and 21 outside
the box, the column's six row groups and three x positions, 64 template
rows each seeing one tap at 11 or 39, fourteen patterns and eight
overlaps, 27.25 percent. All agree.

The first version of that code matched no taps at all. Its regex did
not allow for `+ SOURCE DIST` before `+ FIXED`, and it printed zero bad
rows over an empty set. That is the vacuous pass the house rule is
about. It was caught because the phase table printed empty.

Not checked: whether the three-arm build puts its taps where the two-arm
DEF has them outside the 37 rows Arm A stands in. The die, the rows and
the macros are the same, so tapcell runs the same. Run 80 proves it for
those 37 rows, where 74 taps and 512 fixed cells share the box with no
overlap. The other 44 rows are an assumption until a build with Arm C in
it says otherwise.

Not checked either: routing. The template fixes placement and leaves
routing free by design. Whether sixteen identical placements route to
sixteen similar wire loads is the experiment, not a precondition of it.

Nothing in the build reads any of this. `gen_placement_cfg.py` still
emits no Arm C line and P11 still fails if one appears, and that stays
true until a layout is chosen. The gate gains three commands, 126, and
`ARMC_TEMPLATE.json` is regenerated and diffed like the other records.

The script is 1169 lines, 363 of them fixture and selftest. That is a
sixth over the thousand-line yardstick for a day, and it was one
sitting. The rest of the day's diff is 98 lines across seven files.

Those four numbers were 1132, 359, an eighth and 58 an hour ago, written
before the last section of this writeup existed, and they were wrong by
the time it did. Re-derived rather than left, which is the rule, and the
rule caught its own author.

## The choice, made

The section above was written to hand Nikoloz the layout decision with
the argument laid out on both sides, because where an arm sits on the
die is a research-design question and this project's rule is that those
are his. He read it and handed it back: choose the best option yourself.

So, the column, and the reasoning in one paragraph.

M4 is the metric this arm exists to move, Arm C's frequency spread over
Arm A's, and a ratio not below 1 reports a null. Supply drop and
temperature are gradients that repeat on every die. The three-part
layout samples them across 96 percent of the die's width while Arm A
sits in a block spanning 23 percent, and that difference inflates Arm
C's spread on its own, before any treatment effect. It biases the
measurement toward the null. Sixteen rings is not enough sample to spend
on a confound that runs against the hypothesis when the alternative
removes it. The column puts both arms in the same strip, on the same
rows, in the same corner of the power grid, so a gradient moves the two
together.

What that gives up is real and is recorded: `gen_armc.py`'s argument was
that spreading Arm C puts the position contrast inside one arm where it
can be measured, and the column does not measure it. Nothing in
`PREREGISTRATION.json` asks for that measurement, which is why I think
the trade is right, and the column's own 180 um of height is what a
position covariate would have to be estimated from if one is wanted
later.

The soft box stays for the Arm C build. Not because it earns its place:
with Arm A fixed it holds nothing, and dropping it would let the decode
logic back into the gaps, which is closer to the 93 cells the two-arm
build had in that rectangle than run 80's 24, and the two-arm build is
where the frozen coordinates come from. The reason to keep it is
narrower. Removing it in the same run that adds 512 fixed cells means
not being able to say which change caused whatever moves. It gets its
own run or it stays.

All three are in `chip/G2_AMENDMENT.json` under `resolution`, dated
today, attributed to a session deciding under delegation, and marked as
what they are: choices made after the freeze, with the numbers in hand,
carrying none of the weight of the rule that was frozen on 27 August.
The generator names the layout in one constant and a check fails if that
constant stops matching a layout that exists.

## Open

Whether the soft box stays, which wants a run that changes only that.
The order of the 32 cells inside the template, a serpentine default that
nothing has checked against a routed ring, and the reason the build
estimate is four days and not three. Pages. The two floating nets from
the metrics, unchanged since the 9th. TTSKY26d, not checked today.
