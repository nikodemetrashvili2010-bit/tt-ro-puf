# Pre-tapeout hardware work

This is my ordered list of the hardware and physical-design work I still owe
before I order silicon. None of it is solved yet. Every item changes the RTL or
the flow, so nothing here counts as done until a fresh coherent build and its
checks exist.

## 1. The RO-to-counter gate (fix this first)

This is the one that worries me most. The core picks one oscillator,
`sel_ro = ro_out[active_sel]`, and today the counter clock is a plain
combinational gate, roughly `gated_ro = sel_ro & en_window`. The catch:
`en_window` comes from the reference-clock domain and can fall at any phase of a
570 MHz ring. If it drops just after a rising edge, the last high pulse into the
first ripple flop gets chopped into a runt, and a runt can miss the flop's
minimum pulse width. Behavioral cocotb never sees this, because the models are
ideal. The unit-delay gate sim does not carry real high-speed timing either. So
the sim is green and the hardware is still a question.

The fix is a real redesign, not a patch. `tff_clk[0] = sel_ro` is not a safe
swap: when the ring is disabled it settles through a last transition, and that
changes what the window even counts. Two options I am weighing.

Gate the enable, not the output. Run the window by enabling and disabling the
selected ring through its NAND, and clock the counter straight from the raw RO
output. RO edges are full-swing, so no runt. The only ambiguity is one edge at
each boundary, about one count in twenty thousand. Cost: I have to define and
characterize how the ring settles when it is switched off.

Or use a real clock-gating cell. A sky130 transparent-low latch gate with the RO
as the clock lets the enable change only while the RO is low, which kills the
runt. But then the window enable has to cross into the RO domain first, and that
transfer is itself high-speed and needs validating.

Either way the acceptance evidence is the same. Sweep the gate closing across
every RO phase in extracted-timing simulation, show the first flop always sees a
legal pulse, no edge is dropped or ambiguously captured, and the ripple settles.
Then re-verify against a real gate model, then gate-level with back-annotated
timing, then re-harden.

## 2. The 32-to-1 selection path

`ro_out[active_sel]` picks one of 32 outputs through a synthesized mux. Constant
delay is fine, a fixed delay does not change a frequency. What I have not shown
is that every path passes every RO edge without narrowing or dropping pulses at
the fast corner. That matters scientifically, not just electrically. If RO4's
selector path loses the odd pulse, RO4 reads slow, and now the count depends on
routing rather than on the oscillator. The shared counter removed one
instrumentation variable; it did not remove this one. The whole chain, RO buffer
to top route to mux to gate to first flop, should be validated as one
high-speed path at the fast corner.

## 3. Arm A / Arm B boundary symmetry

Hardening put input and output `clkdlybuf4s25_1` buffers on the Arm B macro
boundary. Arm A has no such buffers. The output one is the problem: it changes
drive and slew into the shared mux, so "Arm B is more reliable" could just mean
"Arm B has a cleaner output stage." I need to either stop those buffers from
being inserted while keeping a clean macro, or give Arm A the same boundary.
Change the flow to produce the architecture I want and re-run the whole signoff.
No hand-editing cells out of the GDS. If I cannot remove the difference, I
characterize it and stop calling the arms layout-only, which the paper now does.

## 4. Floorplan confound

Arm B is a 4x4 grid parked on one side of the tile, columns near x = 3, 63, 123,
183 um. Arm A and the control logic take the rest. So part of what I am
comparing is one region of the die against another, and my whole hypothesis is
about spatial pattern. That is a bad thing to leave confounded. I want to try an
interleaved or at least less one-sided floorplan on a branch, run the full flow,
and compare congestion, parasitics, signoff, and where Arm A lands. The PDN
pitch is 60 um, so moving macro columns on that pitch is geometrically legal.
Whether it routes is another matter. Assume nothing.

## 5. Power and decap confound

Same theme, different axis. Arm B carries its own decap, filler, and power
straps; Arm A sits in the normal cell fabric on met1 rails. That is one more way
the arms differ beyond internal routing. One warning to myself: do not use the
OpenROAD flow power number to wave away IR drop. A free-running ring is not
modeled as normal switching, so that number is meaningless here. Instead model
RO frequency versus VDD and confirm a plausible local IR-drop difference is far
below the Arm A spread, then revisit it with measured supply on silicon.

## 6. PVT corners

The go/no-go is nominal TT at 1.8 V. That is not enough to set operating bounds.
I need RO simulations at real corners, slow 100C/1.6 V and fast -40C/1.95 V: the
fastest and slowest plausible frequency, whether it starts reliably, whether the
measurement chain passes those frequencies, and whether the 16-bit counter can
wrap at the fast corner. A silent wrap is nasty. It returns a believable lower
count, not an error, so it corrupts the ranking quietly. A proven frequency
bound, or an overflow flag, is part of acceptance.

## 7. Distributed-RC validation

The current deck lumps each ring net's total SPEF capacitance to ground and
drops distributed resistance and coupling. Fine as a diagnostic, weaker than it
sounds. Take the fastest, slowest, and a middle Arm A oscillator, plus the Arm B
macro, and re-simulate with as much of the real distributed extraction as I can.
Then check whether the ordering, the spread, and the heavy-load outlier all
survive. If the lumped and distributed results agree, the model earns a lot of
credibility.

## 8. Arm B per-instance integration

Arm B today is one macro, simulated once, drawn as a line. Honest about the
internal geometry, silent about integration. The sixteen instances share the
GDS, but each has its own enable route, output route, neighbours, and location,
and the top SPEF does carry per-instance `u_rob` nets even though it cannot see
inside the macro. Plan: keep the one internal macro model for all sixteen,
attach each instance's real external en and out parasitics from the top SPEF,
and simulate the sixteen separately. Maybe integration adds 0.2%. Maybe it adds
a few percent. If it is the second one, that is a confound I want to find before
I pay for silicon. Same ngspice flow as the go/no-go, so it rides along with the
SPICE work above.

## 9. Controlled multi-seed spread

The three builds I have (5.4%, 8.8%, 10.5%) are not replicates. They differ in
source and settings, not just seed, so I will not pool them. The clean version
is 10 to 20 builds from one frozen RTL, floorplan, constraint set, tool version,
and PDK, changing only the place-and-route seed, reported as a distribution
(median and spread of the peak-to-peak, not a single number). Next to a fab run
this costs nothing, and it turns "three different percentages" into a real
result.

## 10. Optional observability

`ui[7]` and `uio[1:7]` are free. On a one-shot tapeout, observability is worth a
lot. Candidates: a selectable window on `ui[7]` to test count linearity, a
measurement-active or overflow flag, an internal divided-counter bit. Hard rule:
no raw 600 MHz RO to a pad. And I weigh every addition against destabilizing the
clean build. At most one or two surgical features, each with a full re-verify and
re-harden, or none.

## Order of work

Item 1 first, then 3, then 4. Then run 6, 7, and the item-2 chain check, then 8.
Then 9. Only once the architecture is frozen do I lock the acquisition protocol
(that part is already done in `firmware/`), preregister the analysis, freeze the
reproducibility release, and tape out.
