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
drops distributed resistance and coupling. That is a usable diagnostic, but a
reviewer will ask whether the result survives the real RC network. Take the
fastest, slowest, and a middle Arm A oscillator, plus the Arm B macro, and re-simulate with as much of the real distributed extraction as I can.
Then check whether the ordering, the spread, and the heavy-load outlier all
survive. If the lumped and distributed results agree, the model earns a lot of
credibility.

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

Items 1 and 9 are behind me. Next is 3, then 4, since both change the floorplan
and both need a full re-run anyway. After that 6, 7, and the item-2 chain check,
then 8. Item 6 now carries a piece of item 1 with it: the enable-fall phase
sweep has to be repeated at the fast and slow corners, not just nominal. Only
once the architecture is frozen do I lock the acquisition protocol (that part is
already done in `firmware/`), preregister the analysis, freeze the
reproducibility release, and tape out.
