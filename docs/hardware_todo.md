# Pre-tapeout hardware work

This is my ordered list of the hardware and physical-design work I owe before I
order silicon. Items 1 and 9 are now done and I have left them in with what
actually happened, because the results changed how I read the rest. Everything
else is still open. Every open item changes the RTL or the flow, so none of them
counts as finished until a fresh coherent build and its checks exist.

## 1. The RO-to-counter gate (done, 2026-07-24)

This was the one that worried me most. The core picks one oscillator,
`sel_ro = ro_out[active_sel]`, and the old counter clock was a plain
combinational gate, `gated_ro = sel_ro & en_window`. The problem is that
`en_window` comes from the reference-clock domain and can fall at any phase of a
570 MHz ring, so the gate could chop the last pulse on the clock net into a
sliver and drive the first ripple flop below its minimum pulse width. Behavioral
cocotb never showed it, because the models are ideal, and the unit-delay gate sim
carries no real high-speed timing either.

I took the enable-gating option. The counter is clocked straight from the raw
ring output and the window is enforced by switching the selected ring on and off
through its own NAND. No gate sits on the clock net any more, so every edge the
flop sees is a full-swing ring transition.

What I got wrong at first was the justification. I assumed the ring would coast
to a stop through full-width edges. It does not. I swept the enable fall across
a ring period in ngspice against the extracted macro, and the final pulse at the
tap turns out to depend on phase, dropping to about 175 ps where the nominal
half-period is 846 ps. That is inherent to stopping any free-running ring, and
the old gated version had the same exposure at both window edges.

Measuring the pulse at the tap was the wrong test anyway. What decides whether
the boundary matters is the flop, so I moved the check there. I wired a real
`sky130_fd_sc_hd__dfrtp_2` as the first ripple stage, clocked it from the
extracted ring, and dropped the enable at 38 phases across a full period. Every
phase settled to a clean rail, 0.000 V or 1.800 V, nothing sitting near
mid-supply in the tail, and the captured count moved by exactly one between
phases. One count out of roughly twenty thousand. The settle handshake in the
core already tolerates that, since it publishes only after three consecutive
equal reads and otherwise leaves `done` low.

The files: `sim/spice/gono/gen_flop_sweep.py` and `analyze_flop_sweep.py` are the
acceptance test, `gen_gate_sweep.py` and `analyze_gate_sweep.py` characterize the
tap. The re-hardened build passes DRC, LVS, antenna, and the XOR with no setup
or hold violations, and the final netlist has one flop clocked by `sel_ro` and no
`gated_ro` net left anywhere.

Still outstanding: the phase sweep ran at the nominal corner only. Repeat it at
the fast and slow corners as part of item 6.

### Repeated through the selector, 2026-08-02

The sweep above clocked the flop straight from the ring tap. The chip does not.
Item 2 put a selector in between and I had checked each half without ever
checking the two together, so I ran the same phase sweep again with the real
selector cells in the path. `gen_boundary_sweep.py` builds those decks. It does
not rebuild the path, it calls item 2's generator and rewrites four lines, the
enable, the transient length, the output name and a comment, and refuses to
write anything if one of the four is not found exactly once. A deck that quietly
kept item 2's always-on enable would leave the ring running and report a clean
pass for a sweep that never swept.

Thirty-eight phases through B15 at the fast corner, thirty-eight through A05,
and then thirteen more through B15 at 5 ps steps to walk the width where the
pulse stops surviving. Eighty-nine phases in total. Every one of them resolved
the flop to exactly 0.000 V or 1.950 V. Not one landed in between.

The interesting number is where the path gives up. On B15 a 97 ps high at the
tap is swallowed and a 102 ps one gets through, arriving at the flop as 144 ps.
The transition is that sharp, five picoseconds wide, and nothing hangs inside it.
That is the answer to the question item 1 was really asking. The selector chain
behaves as a filter. Either it passes a full pulse or it passes none, so the flop
is never handed a marginal clock and never has the chance to sit at mid rail.
The narrowest thing the flop saw across those three sweeps was 144 ps.

A05 is the other bracket, the path that adds the least width, 102 ps against
B15's 182. It survives a 69 ps tap pulse where B15 needs 102, so the shallower
faster chain passes narrower pulses even though it helps them less. Chain depth
matters more than asymmetry, and both facts come from the same response time:
A05 reaches its full 102 ps by the time the pulse is 128 ps wide, while B15 needs
about 380 ps to express its full 182.

What a swallowed pulse costs is one edge, and in every sweep the phases that lost
it were exactly the phases where the count steps up, so the step happens one
phase later rather than a count going missing. The settle handshake tolerates
that already, since the core publishes only after three equal reads.

Two things this does not cover. It is the fast corner only, which is the corner
where the pulse is shortest and so the right one to have, but not the only one.
And B00 sits just outside the bracket on both criteria, a 375 ps rise against
B15's 360 and 166 ps of asymmetry against 182, so B15 is the hardest path I
measured rather than the hardest path there is. Records in
`boundary_validation_B15.csv`, `boundary_validation_A05.csv` and
`boundary_validation_B15_fine.csv`.

### Four more sweeps, and the number that was wrong, 2026-08-04

Two debts were left above. The sweep had run at the fast corner only, and B00 sat
just outside the bracket on both criteria, so B15 was the hardest path I had
measured rather than the hardest one there is. Both are now closed, with four
more sweeps: B00 at ff over 38 phases and then 11 more at 5 ps steps, and B15
repeated at tt and at ss. That makes 252 phases across seven sweeps in total, and
every single one of them resolved the flop to a clean rail. Nothing has ever
landed at mid supply.

B00 is the strict path, as expected. In its own boundary decks it rises in 375 ps
against B15's 360 and carries less asymmetry, 165 ps against 181. Both sit a
picosecond off what item 2's decks measured for the same two paths, 166 and 182,
which is two transients disagreeing at the resolution I read them at rather than
a real difference. B00 swallows a 105 ps pulse at the tap and passes a 128 ps
one, where B15 swallowed 97 and passed 102, and the fine sweep narrows B00's own
edge to 111 swallowed and 116 passed. Five picoseconds wide again, and again
nothing hangs inside it.

Now the correction, and it is the reason I ran the fine sweep at all. This item
and `SIGNOFF.md` both said the narrowest clock the flop ever saw was 144 ps. That
is wrong. Right at its own threshold B00 hands the flop 80 ps, because at the
edge the chain squeezes the pulse instead of stretching it. Away from the
boundary every path lengthens a high, which is the corrected item 2 result and
still true, but the last clipped pulse is exactly where that stops holding. So
the number is 80 ps, and the one I had been quoting was 80 percent too
generous.

80 ps is narrow enough that I did not want only the simulator's opinion of it,
so `check_pulse_width.py` reads what the PDK itself promises for the first
flop. I get 77.5 ps for `sky130_fd_sc_hd__dfrtp_2` at ff_n40C_1v95, which is
the corner that sweep ran at, so the 80 ps capture clears the library by 2.5
ps. It is characterized, and I am calling it marginal rather than comfortable.
The slower corners are not close: 484 ps against a 169.8 ps promise at tt, and
810 ps against 353.8 ps at ss. The fast corner is the tight one on both sides
at once, since it produces the shortest pulses and the library also promises
the least there.

That script had a bug worth recording, because it reported a failure that was not
real. It picked the first Liberty whose filename contained "ff", which is
ff_100C_1v65 at 109.4 ps, a corner nothing here has ever run at, and told me the
80 ps capture failed. It names the exact file per corner now and refuses to
substitute a near neighbour.

I expected the threshold to be a property of the cells and it turns out to be a
property of the ring. B15 gives up near 100 ps at ff on a 1123 ps period, near
198 ps at tt on 1753 ps, and near 378 ps at ss on 3439 ps. Close to a tenth of
the period every time, nine percent at ff where the fine sweep pins it, and
somewhere between ten and thirteen at tt and ss where the 50 ps step is all the
resolution I have. The asymmetry scales the same way, 181 ps at ff, 314 at tt,
657 at ss.

Fixed time beats fixed fraction at every corner, which settles an argument I had
with myself on 08-02. Fitted on B15's own boundary pulses, the selector adds 176
ps at ff, 310 at tt and 641 at ss, and what it leaves unexplained is between 10
and 40 ps at every corner. A fixed-fraction model fitted to the same pulses
leaves 59 to 220 ps behind, so it is worse everywhere and worst at the slow
corner. The selector adds time. It does not scale what it is given.

### The slow corner passed without testing anything

The first ss run came back clean and it was worthless, and I nearly wrote it up.
The count was 9 at all 38 phases. The default sweep is 38 steps of 50 ps, which
is 1.9 ns, and I had put a comment on that constant saying it was longer than a
ring period at any corner. I had checked tt and ff. The ss period is 3439 ps, so
the enable fall never crossed a ring edge, and all 38 phases were the same easy
case repeated 38 times.

A pass that tested nothing is worse than a failure, because a failure gets
investigated. `analyze_boundary_sweep.py` now rejects any sweep whose count never
changes and says how wide the span was, so the fault reports itself instead of
reading as a clean result. One of the analyzer's existing selftest cases turned
out to contain exactly this fault, sitting there passing, and it is now an
expect-fail case. The real ss run is 76 steps, 3.8 ns, and the count moves from 9
to 10 with four phases losing the final edge.

Records: `boundary_validation_B00.csv`, `boundary_validation_B00_fine.csv`,
`boundary_validation_B15_tt.csv` and `boundary_validation_B15_ss.csv`, alongside
the three from 08-02.

## 2. The 32-to-1 selection path (done 2026-07-31, corrected 2026-08-02)

`ro_out[active_sel]` picks one of 32 outputs through a synthesized mux. A
constant delay is harmless, because a fixed delay does not change a frequency.
What I had never shown is that every path passes every ring edge without
narrowing or dropping a pulse at the fast corner. That matters scientifically and
not only electrically. If RO4's selector path loses the odd pulse, RO4 reads slow,
and the count then depends on routing rather than on the oscillator, which is the
confound this whole chip exists to measure.

The first thing I learned came out of the netlist, before any simulation. The
selector is not a tree. The 32 sources reach `sel_ro` through three to five cells
drawn from six types, a221o_2, a22o_2, a21o_2, a211o_2, mux4_2 and a final
o21a_2, and no two oscillators are wired the same way. Ten paths are three cells.
Eight of the Arm B paths pick up a mux4_2 and run five deep. So checking one path
and generalising would have proved nothing about the other 31.

Each deck carries the real cells of one path, taken from the routed netlist, with
every intermediate net loaded by its own total capacitance from that build's
SPEF. The side inputs of each cell are held at the levels that open that one
path. The stimulus is identical for all 32, the extracted Arm B ring, which at
this corner runs near the 888 MHz the corner sweep found, so the edge shape
driving the selector is a real ring edge and anything that differs between the
results belongs to the path. Each deck ends in the same first ripple stage item 1
used, a real dfrtp_2 wired as a toggle.

Two things I did to stop myself from writing a deck that passes for the wrong
reason. Cell pin order is not written down in the generator at all; it is read
from the PDK's own subckt lines, and the script stops if a cell is missing or if a
pin it needs does not exist. And `--control` writes the same 32 paths with the
last cell deliberately closed. Those have to produce nothing. The side-input
levels are an assumption, and a wrong one would leave a cell stuck at a constant,
which reads as zero edges, so showing that a closed path really does read as zero
is what turns a passing open path into evidence.

The result. All 32 paths carried all 30 judged edges through to the flop, the
flop toggled at half that rate on every one of them, and all 32 blocked controls
were silent. Nothing is dropped and nothing is added.

The delays are more interesting than the pass.

    cells  mux4    n   mean rise   rise range     asymmetry      high at sel_ro
      3     no    10    173.9 ps   157 to 188 ps  110 to 171 ps  646 to 707 ps
      4     no    12    213.5 ps   198 to 226 ps  102 to 163 ps  639 to 699 ps
      5     no     2    252.5 ps   249 to 256 ps  148 to 149 ps  684 to 685 ps
      5    yes     8    367.2 ps   360 to 375 ps  166 to 182 ps  703 to 719 ps

Ignoring the mux4_2 paths, delay tracks cell count at 39.4 ps per cell on a 56 ps
intercept, with a correlation of 0.944. The two five-cell paths that avoid the
mux4_2 measure 252.5 ps and that line predicts 252.8, so the model holds where it
can be tested. The eight paths through the mux4_2 sit at 367.2 ps, which puts the
cost of that one cell at about 114 ps, close to three ordinary cells. The spread
across the whole selector is 218 ps. None of it reaches the measurement, since a
delay that is fixed for a given oscillator cannot change that oscillator's
frequency.

### The correction, 2026-08-02

The first version of this section said levels shorten on the way through, by 9.8%
at best and 25.0% at worst, and warned that a short boundary pulse would arrive
at the flop badly eroded. That was wrong, and wrong in a way worth recording
because every check I had passed it.

The analyzer took the narrowest level at the tap and the narrowest level at
sel_ro and reported the difference as erosion. Those are not the same level. A
rise and a fall cross a path at different speeds, and the difference moves each
trailing edge without moving the leading one, so one polarity grows by exactly as
much as the other shrinks. On B15 the tap runs 537 ps high and 585 ps low while
sel_ro runs 719 ps high and 403 ps low, and the period is 1122 ps at both nodes to
the picosecond. So the narrowest level at the tap is a high, the narrowest at
sel_ro is a low, and the old figure compared one against the other. The 25.0%
described no shortening of anything.

Those four numbers were 539, 583, 721 and 401 until 2026-08-07, and the
correction is the same one this section already makes further down about the
asymmetry. I had quoted B15 from the boundary decks in a paragraph about the mux
decks. The boundary decks give 539 and 583 at the tap and 721 and 401 at sel_ro;
the mux decks give 537, 585, 719 and 403. Two transients disagreeing by two
picoseconds, not a real difference, and both give the same 1122 ps period and
the same conclusion. Quoting the mux decks here is simply the right file to read
from. I found it by rerunning all 32 decks to archive their logs, and every one
of the 256 values in `mux_validation.csv` came back identical, so the CSV was
right and only the prose was wrong.

Re-running all 32 decks with highs and lows kept apart says the same thing
everywhere. Every path has its fall arriving after its rise, by 102 ps on A05 up
to 182 ps on B15, so every path lengthens its high level and shortens its low.
Nothing shortens a high. The rise delays reproduce the earlier run to the
picosecond, which is the useful part: nothing about the circuit changed, only
what I thought it was doing.

The reason I found it is worth keeping too. It was not review. The boundary
sweep reused the same comparison and reported a pulse arriving 182 ps wider than
it left, and a selector cannot widen a pulse, so the impossible number was the
only thing that sent me to look at the waveform.

What survives untouched is the pass. It rested on every edge arriving, and a
period preserved to the picosecond at both nodes is a stronger version of that
claim than the edge matching was. What does not survive is the alarm this section
raised about item 1. The counter's first stage is a rising-edge flop, and every
selector path hands it a longer high than the tap did. Item 1 now carries the
sweep that settles it.

### Archived and re-derivable, 2026-08-07

The sweep was rerun from scratch to archive it, and all 256 values in
`mux_validation.csv` came back identical. Every rise, fall, asymmetry, level
width, edge count and flop-rise count on all 32 paths, with all 32 blocked
controls silent again. The CSV was right.

Getting it into the repository took a decision. The 64 decks produce 180 MB of
waveform, 4.08 MB each over 42020 timepoints, and that does not belong in git.
Almost all of it is flat rail that the analysis never looks at: what
`analyze_mux_sweep.py` does is find where each signal crosses half the supply
and interpolate between the two samples either side, so the samples in the
middle of a level change nothing. `reduce_raw.py` keeps those bracketing pairs
and drops the rest, which is 2.08 percent of the rows and 4.5 MB for the whole
folder including the decks and the console logs.

Calling that lossless is a claim and not an argument, so it is checked rather
than asserted. `reduce_raw.py --verify` runs the real analyzer over the full and
the reduced copy of every deck and compares every field it returns, and CI
regenerates the CSV from the archived folder and diffs it against the committed
one. Both come back identical.

Three things had to survive or every number would move, and the second is the
one I would have missed. The bracketing samples themselves. The largest sample
of the tap and of sel_ro, because the analyzer sets its threshold at
`0.5 * max(max(tap), max(sel))` rather than at a fixed voltage, so losing a peak
moves the threshold and with it every crossing in the file. And the last
timepoint, because `match_edges` uses it to tell an edge that was lost from one
that was still in flight when the transient ended. Kept rows are copied as their
original bytes, so no reformatting can round anything.

Derived record in `sim/spice/gono/mux_validation.csv`, one row per oscillator with
its cell chain, and the run itself in `sim/spice/gono/mux/`. Tools:
`gen_mux_sweep.py --corner ff --control`, `analyze_mux_sweep.py`,
`reduce_raw.py --verify` and `verify_mux_archive.py`. Both were checked against synthetic waveforms before being
pointed at real ones, because an analysis that has never failed has not been
tested. A clean path passes, a swallowed cycle is caught at the time it happened,
a pulse clipped to a sliver that still clocks is caught by the width rule, and a
silent path counts as silent. The first version of the analyzer did fail, on A00,
and it was wrong: it counted totals over a fixed window, so the last ring edge had
no time to cross the selector before the transient ended and was reported as lost.
That is the same mistake item 6 records, a pass condition that quietly assumed the
window lined up with the period. It matches edges to their partners now.

The synthetic checks were the problem the second time. All four of them passed
while the polarity mistake sat in the middle of the analysis, because none of
them ever built a path where a high and a low behaved differently. There are
three more now, and the first of them plants exactly that: a path that lengthens
its high, which must not be reported as erosion.

## 3. Arm A / Arm B boundary symmetry (investigated 2026-07-25, not removable)

Hardening put input and output `clkdlybuf4s25_1` buffers on the Arm B macro
boundary. Arm A has no such buffers. The output one worried me: it changes drive
and slew into the shared mux, so "Arm B is more reliable" could just mean "Arm B
has a cleaner output stage."

I found the cause. My macro config never set `DESIGN_REPAIR_BUFFER_INPUT_PORTS`
or `DESIGN_REPAIR_BUFFER_OUTPUT_PORTS`, so both defaulted on and the flow
buffered the ports. Setting them false and re-hardening does remove them, and
that build passes DRC, LVS and antenna cleanly. I am not shipping it, because it
trades a cosmetic gain for a real regression.

What matters is which cells sit inside the oscillator loop. The loop is the
enable NAND plus thirty inverters with feedback from `n[30]`. The tap buffer
hangs off `n[15]`, so its input capacitance is a load inside the loop and its
cell type does move the frequency. Everything after the tap buffer is outside the
loop and cannot.

    Arm A          n[15] -> buf_1    -> route -> mux
    shipped Arm B  n[15] -> buf_1    -> clkdlybuf4s25_1 -> pin -> route -> mux
    rebuilt Arm B  n[15] -> clkbuf_1 -> clkbuf_4        -> pin -> route -> mux

The shipped macro already matches Arm A on the one cell that touches the loop.
With port buffering off, the resizer swapped that tap buffer to `clkbuf_1` and
added a `clkbuf_4` to drive the pin, so the rebuilt version puts a different
capacitance on `n[15]` and makes the two arms less comparable in frequency, not
more. The only thing removing the input buffer bought me is symmetry on the
enable path, and `en` is held static for the whole measurement window while the
ring is driven through `n[30]`, so buffering there cannot affect frequency or
output edge quality. Cosmetic.

There is also a bigger asymmetry underneath this that I had not measured. Taking
each arm's ring-output net capacitance from the top SPEF: Arm A spans 0.24 to
2.71 fF with a mean of 0.84, while Arm B spans 2.89 to 29.46 fF with a mean of
14.46. Arm B drives roughly seventeen times the load. That is why the flow keeps
putting a driver on the macro output, and `OUTPUT_CAP_LOAD` defaults to 33.4 fF,
close to Arm B's real worst case, so the buffer is justified rather than
gratuitous. The cause is the floorplan: the macros sit at fixed positions across
the tile while Arm A's rings get placed near the mux. So this is item 4's
problem, and no amount of macro-boundary tweaking fixes it.

Where that leaves the claim. Both the extra buffer and the heavier output route
are outside the ring loop, so neither biases the measured frequency, which is the
result the chip exists to produce. What they can bias is edge quality arriving at
the counter, so any reliability comparison between the arms has to account for
them. The paper says the arms are a matched hardened macro against a conventional
standard-cell implementation, not two circuits differing only in internal
routing, and that stays the honest framing. Revisit properly as part of item 4.

Rejected config is recorded in `macro/config.json`. While I was there I fixed a
stale `FP_PDN_MULTILAYER: true` in that file, which could not have built the
shipped macro at all: the core is 16.32 um tall and met5 straps do not fit.

### The edge quality, measured 2026-08-04

This section left a debt and item 8 has now paid part of it. What I said was that
the extra buffer and the heavier output route cannot bias frequency, both sitting
outside the loop, but that they can bias the edge arriving at the counter, so any
reliability comparison between the arms has to account for them. The per-instance
run measures that edge inside Arm B. It spans 62.6 to 318.2 ps across the sixteen
instances, a factor of 5.08, and it tracks output route capacitance at r = +0.999,
which is about as clean as a correlation gets.

So the sixteen copies agree on frequency to 0.0025 percent and disagree on edge
quality by a factor of five. Frequency does not care, and that is item 8's whole
result. Anything downstream that depends on slew would care, and the selector
delays in item 2 are exactly that kind of thing. The debt is not closed, since
this measures the spread within Arm B rather than the difference between the
arms, but it is now a measured number instead of a worry.

## 4. Floorplan confound (two trials run 2026-07-25, both rejected)

Arm B is a 4x4 grid parked on one side of the tile, columns near x = 3, 63, 123,
183 um. Arm A and the control logic take the rest. Measured, that means all
sixteen Arm A oscillators sit inside a box about 44 by 78 um while Arm B spans
roughly 300 by 184. I am comparing one region of the die against another, and my
whole hypothesis is about spatial pattern, so this needed testing rather than
assuming.

I tried the obvious fix twice and it failed twice. Skipping the middle power-grid
column puts a 60 um standard-cell channel down the centre of the macro field, so
Arm A spreads out instead of hiding on one edge. Both variants hardened and passed
DRC, LVS, antenna and the power grid with no setup or hold violations, so signoff
was never the issue. Placement quality was. In each build the placer stretched one
whole oscillator into a thin line, RO9 at 126 by 3 um in the first and RO4 at 106
by 19 um in the second, and that ring's loop then routes back and forth across the
span. Its capacitance roughly doubles against the field: spread went from 6.18 fF
(44% of mean) in the shipped block to 26.68 fF (199%) and 20.11 fF (135%).

My hypothesis for the first failure was the 8 um gap between macro rows, which
leaves a single 2.72 um cell row after halos, so I raised the row pitch to 52 for
two rows per band. Wrong. The outlier moved to a different oscillator and the
spread among the remaining fifteen got worse, 74% to 84%. Two trials, two
different victims: the cause is fragmented space, not band height.

What interleaving did buy: Arm A's x-span nearly tripled, 43.5 to 123.9 um, and
Arm B's output loads tightened from 2.89-29.46 fF to 7.28-18.30. Real gains, but
not worth a layout whose headline number depends on one stretched ring. That is
the fragility I deliberately removed when I stopped quoting a single build.

The reason this cannot be tuned away is geometric. Four macro rows is the maximum
that fits, since at pitch 48 the top row already ends at 204 um against a 223.04
core limit. Sixteen macros in four rows need four columns, and only five column
positions exist because each must sit on the 60 um grid for the met4 stripes to
reach the macro power pins. So the only choice is which four of five columns, and
the shipped grouping is the one that leaves Arm A a contiguous 92 um strip. Every
alternative leaves a 60 um channel plus a 29 um remnant.

So the confound follows from die size, macro footprint and grid pitch. Removing it
needs more area, a larger tile, or fewer or smaller macros, and each of those
changes the experiment or the budget. For this tapeout the block floorplan ships
and the region difference is stated as a limitation in the paper. Item 3's output
load gap stays open for the same reason.

Evidence and both configs: `dualarm/floorplan_trials/`.

## 5. Power and decap confound (done 2026-08-05)

Same theme as item 3, different axis. Arm B carries its own decap, filler and
met4 power straps, while Arm A sits in the ordinary cell fabric on met1 rails.
One more way the arms differ beyond internal routing, and not a small one. The
supply pushing figure I measured on 2026-07-29 is 105.9 percent per volt, so
ten millivolts of difference between the arms would be a whole percent of
frequency, against an Arm A dispersion of 5.84 percent. An argument was never
going to settle that.

One warning to myself, kept from when this item was still a plan: do not use the
flow's own power number to wave this away. A free-running ring is not modelled as
normal switching, so that number means nothing here.

The honest test does not pick one resistance. I do not know the real supply path
resistance to better than a factor of a few, and if the answer rested on my
estimate then it would only ever be as good as the estimate. So the sweep runs
the series resistance across four decades, from essentially ideal to a kilohm,
and measures three things at each point: the current the ring draws, the supply
that actually arrives at the cells, and the frequency. Neither ring is new code.
Arm A comes from item 7's distributed RC generator and Arm B from item 8's macro
builder, both of which already produce numbers this project quotes. The only
things this adds are the resistor and two measurements.

    ohm      Arm A uA   Arm A V   Arm A MHz    Arm B uA   Arm B V   Arm B MHz
    ideal       118.7    1.8000     536.865       134.8    1.8000     570.616
       10       118.5    1.7988     536.203       134.6    1.7987     569.830
      100       116.5    1.7884     530.303       132.0    1.7868     562.758
     1000        99.5    1.7005     478.447       110.3    1.6897     501.774

The deck was wrong twice before it was right, and the reason is worth writing
down because I misdiagnosed it the same way both times. The current column came
back as exactly zero, and I assumed ngspice wanted a different spelling for a
voltage source's branch current, so I wrote a second spelling next to the first.
Spelling was not the problem. A deck carrying a `.save` line keeps only the
vectors that line names, and neither of mine named a current, so `vdd#branch` was
never in the plot for any spelling to find. Adding `i(Vdd)` to the save lines
fixed it in one line. The reader now rejects a zero current outright instead of
averaging it into a verdict, because a ring that is oscillating draws tens of
microamps, and a zero there means the measurement did not happen rather than that
the answer is small.

I make the sweep prove it is real three ways before reading anything off it.
The supply at the cells falls as the resistance rises, so the resistor is in
the circuit and I am not reading a flat line. Ohm's law closes at every point
in both arms, with the worst disagreement anywhere rounding to zero at four
decimal places, and that one matters because the current and the voltage are
separate measurements that did not have to agree. And the pushing figure the
sweep implies, 108.3 percent per volt in Arm A and 105.7 in Arm B, reproduces
the 105.9 I measured on 2026-07-29 by moving an ideal supply. Different
mechanism, same number, and that is the agreement I actually trust.

Then the question itself. The resistances are set by the layout and not by me, so
they come out of the shipped DEF and the PDK's sheet resistances. Arm A: half a
met4 stripe pitch of 0.48 um met1 rail at 0.125 ohm per square, 7.81 ohm. Arm B:
the full 220.8 um of 2.4 um met4 stripe at 0.047, 4.32 ohm. Read off the sweep,
that is 0.1055 percent of frequency for Arm A and 0.0707 for Arm B, so the two
arms differ by 0.0348 percent.

That is 168 times under Arm A's dispersion, and under the 0.062 percent
transistor mismatch scale as well. If my geometry is wrong by a factor of ten in
the bad direction it becomes 0.3417 percent, still seventeen times under. Being
able to say that last part is the whole reason for sweeping four decades instead
of computing one number.

What I will not claim is that the effect is invisible. 0.0348 percent is about
eight counts of the counter, and the counter resolves one, so the chip can see
it. What makes it harmless is that it is an offset between the arms rather than a
spread inside either one. Every Arm B ring sits on the same strap geometry.
Inside Arm A the rail resistance runs from nearly nothing, for a cell sitting
under a stripe, up to the 7.81 ohm worst case, and even charging that entire
range to per-oscillator variation gives 0.1055 percent, which is 55 times under
the dispersion Arm A actually shows. Supply is not what makes Arm A spread.

Ideal in every deck: a fixed source behind one resistor, no decoupling, no
package inductance, no neighbours switching. So this bounds the static IR-drop
confound and says nothing about dynamic droop. That one needs a probe on a real
supply pin, and it goes on the silicon list.

Tools are `gen_supply_decks.py` and `analyze_supply.py`, the latter with
`--selftest`, which plants nine faults including a log whose current measurement
never happened.

## 6. PVT corners, Arm A (done 2026-07-25; the Arm B half is still open)

The go/no-go was nominal TT at 1.8 V, which sets no operating bounds. I re-ran the
whole Arm A deck at slow (ss, 100 C, 1.60 V) and fast (ff, -40 C, 1.95 V) against
the same extracted capacitances, and re-ran the boundary flop sweep at the fast
corner.

    corner            min      mean       max    p-p     max count   headroom
    ss 100C 1.60V   276.2     283.6     291.7   5.46%        11667      5.62x
    tt  27C 1.80V   540.0     554.7     570.7   5.53%        22828      2.87x
    ff -40C 1.95V   840.3     863.1     888.3   5.56%        35532      1.84x

All sixteen Arm A oscillators started at every corner, so the ring self-starts at
1.6 V and 100 C, which was the startup worry. The control decks (no parasitics) return a
single identical frequency per corner, 323.140, 633.640 and 987.948 MHz, which is
what validates the corner decks themselves rather than just trusting them.

The counter does not wrap. Worst case is the fast corner at 35532 of 65535, so
1.84x headroom. Two numbers worth writing down because they constrain the
firmware: at 888.3 MHz the lowest safe reference clock is 13.55 MHz, and the
longest safe window at 25 MHz is 1844 cycles against the 1000 the RTL uses. So the
existing 25 MHz choice is sound and the margin is quantified rather than assumed.

Item 1 owed a corner repeat of the enable-fall sweep, and that is now done at ff,
where the ring runs 888 MHz and the boundary pulse is proportionally shorter than
at nominal. All 38 phases settled to a clean rail at 1.95 V with nothing near
mid-supply, and the count steps up strictly one edge at a time as the fall moves
later. One correction came out of this: my original pass condition asked for a
total count spread of at most one, which quietly assumed the sweep spanned exactly
one ring period. At the fast corner the period shrinks to about 1.13 ns while the
sweep still spans 1.9 ns, so crossing a full period legitimately adds an edge and
the old test reported a false failure. The condition now checks what the design
actually relies on, that a later fall adds at most one edge and never loses one.

The most interesting result is that the dispersion barely moves with corner:
5.46%, 5.53% and 5.56% peak to peak, with the frequency-capacitance correlation at
-0.9997 in all three. The absolute slope tracks frequency, -2.478, -4.936 and
-7.783 MHz/fF, but normalised it is nearly constant at -0.873, -0.890 and
-0.902 percent per fF. The routing fingerprint is a relative effect that survives
process, voltage and temperature, which is a much stronger statement than the
nominal result alone and predicts the pattern should reappear on silicon measured
at any temperature.

A finer sweep now sits alongside this one. The three corners move device, supply
and temperature together, which bounds the range but cannot say which axis did
what. `gen_noise_decks.py` holds the devices typical and moves supply and
temperature one at a time instead, so the supply pushing figure and the
temperature coefficient come out separately, and it splits each shift into the
part that moves all sixteen rings together and the part that does not. Only the
second kind can flip a bit. That work is written up in the results document
under what a reading can resolve.

Two things are still owed here, and the first one I only noticed on 2026-08-08.

**Everything above is Arm A.** `gen_dualarm_decks.py` says in its own sixth line
that Arm B is not in these decks, and I still wrote the result up as though it
covered the chip, in this file and in `SIGNOFF.md`. What Arm B actually has at
corners is B15 on its own at ss, tt and ff, from the boundary work in item 1.
The rest of Arm B has the sixteen per-instance runs at tt (item 8) and the
distributed-RC macro run at tt (item 7), both nominal. Sixteen copies of one
hardened macro should not spread the way sixteen separately routed rings do, and
item 8 measured 0.0025% peak to peak at tt against Arm A's 5.84%, so I expect the
corner table to be narrow for Arm B. Expecting it is not the same as running it.
Doing it properly needs a generator that Arm B does not have yet, since the
existing one only builds Arm A decks.

**Run on 2026-08-10, and the generator claim above was wrong.** Arm B's decks
never came from `gen_dualarm_decks.py`. They come from `gen_instance_decks.py`,
which has taken a `--corner` argument since I wrote it for item 8 on 08-03, and
`analyze_instance.py` already carried the control frequency for all three
corners. I costed a day and a half against a file that does not build the thing.
It was two ngspice runs.

All sixteen instances now start at ss and ff as well as tt, each carrying its own
real enable and output route. They spread **0.0001% at ss and 0.0009% at ff
against 0.0025% at tt**, so 41675 and 6565 times under Arm A at the same corner,
and every one of the three is far under the 0.01% written down before the runs.
The whole spread is 0.02, 0.57 and 0.30 of one counter count. Logs are
`armb_instances_ss_out.txt` and `armb_instances_ff_out.txt` beside the tt one,
and `verify_instance_corners.py` re-derives all of it from those logs with its
own parser, 36 checks and five planted faults, in CI.

Read the ss digits as an upper bound rather than a measurement. The spread there
is 1.3e-6 of the mean and the log's own two ways of stating a frequency disagree
at 1.6e-7, so there is only eight times of headroom and the third significant
figure depends on which definition you take. tt and ff have 333 and 198 times.
What survives that reading is every claim above, all of which clear it by
several orders.

**The corners pair device models with nominal interconnect.** The fuller job
pairs ss with the max SPEF and ff with the min SPEF. Device spread dominates the
frequency bound, so the bound stands, but the RC pairing would tighten it.

Tools: `gen_dualarm_decks.py --corner {tt,ss,ff}`, `analyze_corners.py`,
`gen_flop_sweep.py --corner ff`.

## 7. Distributed-RC validation (done 2026-07-25, redone 2026-07-30 after a bug, Arm A)

The go/no-go deck hangs each ring net's total SPEF capacitance on one node, which
drops the series resistance, collapses the split between the two ends of a net,
and grounds the coupling as though the neighbour were quiet. I rebuilt all sixteen
Arm A oscillators from the SPEF's actual network instead and simulated both, so the
only difference between the two runs is the parasitic model.

What the SPEF actually holds, per ring: 33 resistors, 65 grounded capacitors, and
between 23 and 39 coupling capacitors whose far end is another node of the same
ring, usually the neighbouring inverter. That last part is the interesting bit.
Neighbouring inverter outputs swing in antiphase, so grounding those couplings
understates them, while a real capacitor between the two moving nodes reproduces
them. The parser accounts for 100% of each net's declared capacitance, which is how
I know nothing is being silently dropped.

The coupling count is also where I got this section wrong the first time, and it
took until 2026-07-30 to catch. A coupling capacitor joins two nets, and IEEE 1481
records it under both of them with the same value, so walking the 31 nets of one
ring reaches every internal coupling twice. I wrote it out both times. Each of
those capacitors was therefore built twice in the deck, which added 0.56 to 2.08 fF
per ring, five to fourteen percent of the ring's extracted load. What hid it was
the sentence above about accounting for 100% of each net's declared capacitance.
That test passes either way, because each net does declare its share of a shared
capacitor. `gen_rc_decks.py` now drops the second sighting, prints how many it
dropped, and stops if a repeated pair ever carries two different values. Everything
below is from the rebuilt decks, and the old figures are in the git history if
anyone wants the comparison.

Results. Every ring runs slower with the real network, from -0.66% on the lightest
to -1.34% on the worst, and the shift tracks ring load at r = -0.429. Because the
heavier rings lose more, the dispersion gets slightly wider rather than narrower:
5.55% lumped becomes 5.84%. So the lumped model I have been quoting is conservative,
by about five percent of the figure. My double-counted version said a third, which
flattered the simplification I was trying to defend.

The per-oscillator fingerprint survives. Rank correlation between the two models is
0.994, and both the fastest and the slowest ring are RO7 and RO14 either way. Under
the double-counted decks the slowest label moved to RO2, so that reordering was an
artefact too.

The response bits survive as well. The design compares neighbouring oscillators and
none of the eight comparisons reverses, including the two closest pairs at 0.28%
and 0.32%. I am still not going to present bits from pairs that close as
predictions, because a third of a percent is inside the range that separates two
plausible parasitic models of the same layout, and `firmware/analyze_counts.py`
already flags them as low margin when it scores real counts. What I can no longer
claim is a pre-silicon list of which pairs will flip, since the two models now
agree everywhere.

My first pass at the acceptance test asked for identical rankings across all
sixteen rings. That was the wrong test: several rings sit within a few tenths of a
percent, so near-ties reorder without telling you anything. The check now reports
spread agreement, rank correlation, the pair-bit reversals with their gaps, and the
load dependence of the shift. It still fails a scrambled control. Worth noting that
none of those checks caught the duplicate capacitors, since they all compare one
model against another rather than either against the component counts. The new
dropped-listing count in the generator output is the check that would have.

One thing remains, and it is a limit of the method rather than a missing run.
"Distributed" here means OpenROAD's own reduced per-net network, which is itself a
reduction of the field problem; coupling to nets outside the oscillator is still
grounded, and that ranges from 4 nets on RO7 to 72 on RO14.

The Arm B macro used to be the second item in this paragraph, since it has its own
SPEF and had never been through the same treatment. It has now. The run is the
next section down and the lumped-only 569.5 MHz reference is gone.

Tools: `gen_rc_decks.py --ro N`, `analyze_rc.py --dir ... --ro 0..15`.

### The macro half, done 2026-08-07

`gen_macro_rc_deck.py` does for the hardened macro what `gen_rc_decks.py` does
for Arm A, and it imports that script's parser rather than writing a second one,
so the coupling rule cannot drift between them. It writes a lumped deck and a
distributed deck that differ in nothing but the parasitic model. Thirteen offline
checks pass with no PDK and no simulator, and the two ngspice runs are written up
in `macro_rc_run_steps.md`, prediction first.

The extraction accounts for 15.33 fF across all 35 macro nets, of which the ring
n[0..30] carries 11.01. The distributed model builds 37 resistors, 72 grounded
capacitors and 25 real couplings, drops 25 second listings, and grounds nothing
at all for want of a partner, which is the one thing a closed macro gives me that
Arm A never had.

Building it cost a mistake worth recording, because the check that caught it is
not the check I would have written first. The capacitance books came out 1.54 fF
short, ten percent of the extraction. A SPEF writes a top-level port as a bare
name with no instance number and no colon, so `en` and `out` were not being
recognised as nodes, and their capacitance and their series resistance to the
cell they reach were both being dropped. What made this findable is that the two
models have an exact relationship rather than an approximate one: the lumped sum
counts every coupling twice and the distributed deck builds it once, so the gap
between the totals has to be the coupling total to the last digit. A ratio test
with a one percent tolerance would have passed the broken version.

The prediction went into `macro_rc_run_steps.md` before the run. The lumped deck
should reproduce 569.5 MHz to within about two tenths of a percent, and the
distributed one should sit 0.85 to 0.97 percent below it.

**The result. The macro runs at 566.05 MHz distributed against 570.62 lumped, a
shift of -0.801 percent.**

The check I said mattered most passed on a number I had not thought to name. The
lumped rebuild came out at 570.6159 MHz, which is 0.194 percent above
`gen_macro_deck.py`'s 569.5134 and inside the tolerance I set, with the timestep
as the cause I had written down. But 570.6159 is item 5's Arm B ideal-supply
figure, 570.616, to seven significant figures. That deck came through the supply
generator from item 8's macro builder and shares no code path with this one, so
two separately written decks landing on the same digit says more about the
rebuild than agreeing with the coarse-step original does.

The shift itself came in at -0.801 percent against the -0.851 the Arm A fit
predicted. That fit's own residual scatter across the sixteen Arm A rings is
0.159 points, so the macro sits 0.32 sigma off the line, and inside Arm A's own
range of -0.66 to -1.34. The hardened macro loses frequency to the real network
the way an Arm A ring of its weight does, which is not something the fit had to
deliver, since the macro is a compact hardened block and Arm A is placed in open
fabric.

What this changes in the comparison. Arm B distributed at 566.05 MHz now sits
inside Arm A's distributed range of 535.76 to 567.91 rather than above it, and
both arms are quoted from the same parasitic model for the first time. What it
does not change is item 8. All sixteen copies carry the identical internal
model, so this moves all sixteen together and the 0.0025 percent spread between
them is untouched.

Both decks and both logs are archived in `sim/spice/gono/macrorc/`, and
`analyze_macro_rc.py` re-derives the whole result from those logs with no
ngspice and no PDK. Seven selftests, eight checks. Two of the checks are worth
naming: the frequency and the period are separate lines that ngspice wrote
independently, so their product has to be the 20 cycles the deck measures over,
and the shift has to be negative because both model differences load the ring
further.

## 8. Arm B per-instance integration (done 2026-08-04)

Arm B was one macro, simulated once, and drawn in every figure as a single line.
That covers the geometry inside the macro and says nothing about integration. The
sixteen instances share the GDS, so their internal parasitics are identical by
construction, but each one has its own enable route, its own output route, its
own neighbours and its own place on the die. If integration puts a few percent of
spread back into Arm B then the matched arm is not matched in the way I have been
claiming, and I would much rather find that here than after paying for silicon.

The deck keeps the one internal macro model for all sixteen and hangs each
instance's real external parasitics on it: the real enable driver, the enable
route, the output route, and the real selector cell that route ends at, both
routes built distributed from the top SPEF rather than lumped. All sixteen run in
one file alongside a control with no capacitance at all and a reference carrying
the macro's own extraction only. The sixteen internal models are element for
element identical to the reference, all 35 internal capacitors included, so
anything that differs between the results belongs to the routes and to nothing
else.

The prediction went into `instance_run_steps.md` before the run, which is a habit
I want to keep whether or not it makes me look good afterwards. Both boundary
nets sit outside the oscillator loop, so the frequency should hardly move, and I
wrote that I would be surprised by more than 0.01 percent. Arm A's own regression
says 0.01 percent needs 0.011 fF of change on n[15], and the only route from an
output net back to n[15] is Miller feedback through two buffers in series.

I got 0.0025 percent peak to peak across the sixteen, standard deviation
0.0008. Arm A on the same build spreads 5.84 percent, so integration is 2326
times smaller than the effect this chip exists to measure.

The better sentence is the one about the counter. The measurement window holds
22826 Arm B periods, so one count is 0.0044 percent of frequency, and the whole
per-instance spread is 0.57 of a single count. The chip cannot distinguish the
sixteen copies even in principle. That is a stronger claim than "the difference
is small", and I want it in the paper in those words.

A number that small only means something if I can tell it from solver noise,
which is why the discriminator was in the analyzer before the run and not after
it. A real Miller path would make frequency correlate with output route
capacitance, and the correlation would be negative. It is -0.160, which at
fourteen degrees of freedom is t = 0.608 against a critical value of 2.145, so it
cannot be told apart from zero. The sign is at least the one a real Miller path
would need, so nothing is wired backwards. The honest phrasing is that Miller
feedback is bounded above by 0.0025 percent here. Not that it was measured.

The two correlations that ought to be real are real, which is the other half of
trusting the deck. Route delay against route capacitance is +0.910. The edge
arriving at the selector against route capacitance is +0.999, and that one pays a
debt item 3 opened.

`verify_instance.py` re-derives all of it from the raw log with its own SPEF
parser, its own netlist parser and its own correlation code, sharing nothing with
the analyzer except the log file itself. 37 checks, 37 pass.

What this does not cover. The macro's internal parasitics are still net totals
hung on single nodes, so the absolute Arm B frequency remains a lumped number.
Item 7 moved Arm A from 5.55 to 5.84 percent by rebuilding it distributed, and
the macro is owed the same treatment. It cannot touch this comparison, since all
sixteen carry the identical internal model, but it is owed. The run is nominal
corner only. And the enable route sits in the deck without its real job being
tested, because enable is static for the whole measurement window, so what it
actually affects is how the ring starts and stops, and that belongs to item 1.

Tools are `gen_instance_decks.py`, `analyze_instance.py` with `--selftest`, and
`verify_instance.py`. The raw log and the derived record are archived in
`sim/spice/gono/`.

## 9. Controlled multi-build spread (done, 2026-07-24)

The builds I had (5.4%, 8.8%, 10.5%) were not replicates. They differed in
source and settings, not just placement, so pooling them would have been wrong.

I wanted a seed sweep and could not have one. LibreLane 3.0.3 does not expose
OpenROAD's global-placement random seed, and patching the tool would have broken
the point of the experiment, which is that everything except one knob stays
frozen. So I varied target placement density instead, 56% to 64% in 1% steps,
with the RTL, macro locations, floorplan, constraints, tool, and PDK held fixed.
It perturbs standard-cell placement without touching the design. It is a
placement-sensitivity sweep and I label it that way rather than calling it a
seed study.

All nine builds hardened and all nine kept every ring intact. Dispersion came
out at a median of 5.75%, a range of 4.19% to 6.99%, and an SD of 0.80%. The
shipped build at 5.53% sits near the middle. Density explains almost none of the
variation on its own (r = 0.32), which is the expected result for a knob that is
a perturbation rather than a cause.

Two things make me trust the band. The density-60 build reproduces the shipped
config and returned 5.53%, matching to the digit, and I ran the whole sweep
twice and got identical numbers, so the flow is deterministic and this is real
placement sensitivity rather than noise. Against that, the old 10.5% build was a
wide draw, not the normal case, and it owed most of its range to one oscillator
the router loaded with 24.4 fF.

Driver and summary: `dualarm/placement_sweep/`. A real seed sweep is still the
cleaner experiment if a future LibreLane exposes the seed.

## 10. Optional observability

`ui[7]` and `uio[1:7]` are free. On a one-shot tapeout, observability is worth a
lot. Candidates: a selectable window on `ui[7]` to test count linearity, a
measurement-active or overflow flag, an internal divided-counter bit. Hard rule:
no raw 600 MHz RO to a pad. And I weigh every addition against destabilizing the
clean build. At most one or two surgical features, each with a full re-verify and
re-harden, or none.

## 11. Re-run the lumped decks at 1 ps (open, raised 2026-08-12)

`sim/spice/gono/numerical_audit.py` turned this up while auditing the
arithmetic behind Sections 6 and 7 of the paper, and it is small but it should
not sit unrecorded. `gen_dualarm_decks.py` writes `.tran 5p` and
`gen_rc_decks.py` writes `.tran 1p`, so the lumped and full-RC frequency sets
are not simulated at the same numerical resolution. The 0.2 percent timestep
sensitivity found on the macro in item 7 was exactly a 5 ps against 1 ps
comparison.

The size of it is bounded from data already here. The lumped deck varies
nothing but capacitance, so fitting capacitance against it is recovering its own
input, and the 0.0443 percent that survives is a ceiling on per-ring numerical
error. Against that, the compensated residual is 4.1 times clear, the raw layout
spread 39 times, and every pair separation in both models clears the pair
ceiling of 0.0627 percent.

So nothing in the paper turns on it, and the bits are read from the 1 ps set in
any case. The reason to do it: the closest full-RC pair sits at 0.116 percent,
only 1.9 times the pair ceiling, and that is the pair Section 7.1 identifies as
holding most of the surviving entropy. A 1 ps lumped rerun costs machine time
and no thought, and it would let the sign-agreement claim between the two
parasitic models be stated without a footnote. Do it in the idle stretch, not
before a deadline, and do not touch the 1 ps decks that produced the reported
numbers.

## Order of work

Items 1, 2, 5, 7, 8 and 9 are done. Item 6 is done for Arm A and open for Arm B.
Items 3 and 4 are tested and closed as not fixable on this die, with the
reasoning and the measurements recorded above, and both come back only if I move
to a larger tile. Item 10 is a judgement call I
have not made yet, and the honest default is to make no change at all.

What is left is mostly not simulation any more. Item 7's Arm B re-extraction was
open in this paragraph until 2026-08-07 and is now run, so both arms are quoted
from the same parasitic model. Three things are genuinely still open. Item 6's
corner table covers Arm A, and Arm B's corner coverage comes from item D's
per-instance runs rather than from that table. This sentence said Arm B had only
B15 at three corners; item D ran all sixteen at ss and ff on 2026-08-10 and the
line was not updated until the 11th. The boundary
is three corners deep on B15 and three paths deep at ff, and the other 29
selector paths have been swept for edges without being swept for the stopping
boundary; I am treating those as covered by the filter behaviour, which is a
judgement and not a measurement. And three sweeps still have no raw logs in the
repository, named at the top of the README.

The flow's warning classes are triaged, in `docs/warning_triage.md`. None of the
six is a defect. The nine disconnected pins are unused chip inputs, the
max-fanout violation is the clock-tree root that CTS built and the resizer never
touched, the two floating nets are the power and ground rails and are 2 in every
build I have, and the max-slew violations vanish at the fast corner and are
nowhere near the ring nets. Two smaller debts came out of it: the names of the
140 slew-violating pins and of the 461 lint warnings, both of which need the
timing reports and the linter log out of my local run directory. Worth recording
that my first account of the 25 unannotated nets was wrong. I explained the gap
with the sixteen black-boxed macros, and the arithmetic worked on two builds,
until a third build with no macros at all showed the same offset.

Then the freeze: lock the acquisition protocol, which is already written in
`firmware/`, preregister the analysis, cut the reproducibility release, and
submit. TTSKY26c closes on 2026-09-07 and it is the only sky130 shuttle I can
reach with this build, so that date is the real constraint on everything above.
