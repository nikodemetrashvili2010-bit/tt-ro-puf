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

## 2. The 32-to-1 selection path (done, 2026-07-31)

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

    cells  mux4    n   mean delay   delay range     narrowest level
      3     no    10     173.9 ps   157 to 188 ps   415 to 476 ps
      4     no    12     213.5 ps   198 to 226 ps   423 to 483 ps
      5     no     2     252.5 ps   249 to 256 ps   437 to 438 ps
      5    yes     8     367.2 ps   360 to 375 ps   403 to 419 ps

Ignoring the mux4_2 paths, delay tracks cell count at 39.4 ps per cell on a 56 ps
intercept, with a correlation of 0.944. The two five-cell paths that avoid the
mux4_2 measure 252.5 ps and that line predicts 252.8, so the model holds where it
can be tested. The eight paths through the mux4_2 sit at 367.2 ps, which puts the
cost of that one cell at about 114 ps, close to three ordinary cells. The spread
across the whole selector is 218 ps. None of it reaches the measurement, since a
delay that is fixed for a given oscillator cannot change that oscillator's
frequency.

What does need writing down is that levels shorten on the way through, by 9.8% at
best and 25.0% at worst. In steady state that is comfortable. The narrowest level
arriving anywhere is 403 ps against a 563 ps half period at this corner, so 72% of
it survives.

The part I am not happy about is what this does to item 1. That sweep clocked the
flop straight from the ring tap with no selector in between, and the shortest
boundary pulse it found was 175 ps. Through the worst path's 25% shortening, a
pulse like that would arrive at the flop as roughly 131 ps. I never simulated
that combination. My expectation is that it costs at most one count, which the
settle handshake already tolerates, but an expectation is not what item 1 claims,
and the honest position is that the boundary case is verified without the
selector and the selector is verified without the boundary case. Repeating the
item 1 phase sweep with the selector in the path is now cheap, because the deck
generator already knows how to build the path, and it is the first thing I should
do next.

Derived record in `sim/spice/gono/mux_validation.csv`, one row per oscillator with
its cell chain. Tools: `gen_mux_sweep.py --corner ff --control` and
`analyze_mux_sweep.py`. Both were checked against synthetic waveforms before being
pointed at real ones, because an analysis that has never failed has not been
tested. A clean path passes, a swallowed cycle is caught at the time it happened,
a pulse clipped to a sliver that still clocks is caught by the width rule, and a
silent path counts as silent. The first version of the analyzer did fail, on A00,
and it was wrong: it counted totals over a fixed window, so the last ring edge had
no time to cross the selector before the transient ended and was reported as lost.
That is the same mistake item 6 records, a pass condition that quietly assumed the
window lined up with the period. It matches edges to their partners now.

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

## 5. Power and decap confound

Same theme, different axis. Arm B carries its own decap, filler, and power
straps; Arm A sits in the normal cell fabric on met1 rails. That is one more way
the arms differ beyond internal routing. One warning to myself: do not use the
OpenROAD flow power number to wave away IR drop. A free-running ring is not
modeled as normal switching, so that number is meaningless here. Instead model
RO frequency versus VDD and confirm a plausible local IR-drop difference is far
below the Arm A spread, then revisit it with measured supply on silicon.

## 6. PVT corners (done 2026-07-25)

The go/no-go was nominal TT at 1.8 V, which sets no operating bounds. I re-ran the
whole Arm A deck at slow (ss, 100 C, 1.60 V) and fast (ff, -40 C, 1.95 V) against
the same extracted capacitances, and re-ran the boundary flop sweep at the fast
corner.

    corner            min      mean       max    p-p     max count   headroom
    ss 100C 1.60V   276.2     283.6     291.7   5.46%        11667      5.62x
    tt  27C 1.80V   540.0     554.7     570.7   5.53%        22828      2.87x
    ff -40C 1.95V   840.3     863.1     888.3   5.56%        35532      1.84x

All sixteen oscillators started at every corner, so the ring self-starts at 1.6 V
and 100 C, which was the startup worry. The control decks (no parasitics) return a
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

Still owed here: these pair device corners with nominal interconnect. The fuller
job pairs ss with the max SPEF and ff with the min SPEF. Device spread dominates
the frequency bound, so the bound stands, but the RC pairing would tighten it.
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

Two things remain. The Arm B macro has its own SPEF and has not been redone this
way, so the 569.5 MHz reference is still lumped-only. And "distributed" here means
OpenROAD's own reduced per-net network, which is itself a reduction of the field
problem; coupling to nets outside the oscillator is still grounded, and that ranges
from 4 nets on RO7 to 72 on RO14.

Tools: `gen_rc_decks.py --ro N`, `analyze_rc.py --dir ... --ro 0..15`.

## 8. Arm B per-instance integration

Arm B today is one macro, simulated once, drawn as a line. That covers the
internal geometry and says nothing about integration. The sixteen instances
share the GDS, but each has its own enable route, output route, neighbours, and location,
and the top SPEF does carry per-instance `u_rob` nets even though it cannot see
inside the macro. Plan: keep the one internal macro model for all sixteen,
attach each instance's real external en and out parasitics from the top SPEF,
and simulate the sixteen separately. Maybe integration adds 0.2%. Maybe it adds
a few percent. If it is the second one, that is a confound I want to find before
I pay for silicon. Same ngspice flow as the go/no-go, so it rides along with the
SPICE work above.

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

## Order of work

Items 1, 2, 6, 7 and 9 are done. Item 6 closed out the corner repeat item 1 owed,
and item 7 leaves only the Arm B macro re-extraction behind. Items 3 and 4 are
tested and closed as not fixable on this die, with the reasoning and measurements
recorded above, and both come back only if I move to a larger tile.

Item 2 passed but did not close the measurement chain, because it showed the
selector shortens a level by up to a quarter and item 1's boundary sweep was run
without the selector in the path. So the next job is small and specific, repeat
the item 1 phase sweep through a selector path, and the worst path is already
known to be B15. After that comes item 8. Only once the architecture is frozen do
I lock the acquisition protocol (that part is already done in `firmware/`),
preregister the analysis, freeze the reproducibility release, and tape out.
