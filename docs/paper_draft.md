# Automated Layout Manufactures Fake Entropy in Ring-Oscillator PUFs: A Pre-Silicon Study on the Open-Source sky130 Flow

**Nikoloz Demetrashvili** · Independent researcher · Georgia
Draft, 2026-07-09

---

## Abstract

A ring-oscillator PUF is only secure if the frequency differences between its
identical oscillators come from random manufacturing variation. I show that on
the open-source ASIC flow used by low-cost shuttles, a big part of the
difference is not random at all. I took a 32-oscillator RO-PUF through the
OpenLANE/OpenROAD flow on the SkyWater sky130 PDK, extracted the parasitics of
the routed layout, and simulated every oscillator in SPICE. The transistors
were held at nominal, so the only thing that differed between oscillators was
the layout. That alone spread the 32 supposedly identical oscillators over an
**8.8% peak-to-peak frequency range**, and extracted routing capacitance
explains the spread almost completely (Pearson *r* = −0.997). The pattern is
printed by the mask. Every chip gets the same one. An attacker who
characterizes a single device can predict the bits on all the others, which
makes this fake entropy, not real entropy. The fix is old but nobody had
carried it to this flow: harden one oscillator into a fixed macro and step out
bit-identical copies. Layout spread goes to zero by construction and the
operating point survives; the matched oscillator simulates at 569.5 MHz,
within 0.4% of the auto-placed arm's mean. In the submitted two-arm chip the effect and
the fix sit side by side: the auto-placed arm spreads 5.4% while the matched
arm holds one frequency. The whole check runs on open tools, OpenROAD
extraction plus ngspice, so anyone can run it before paying for a one-shot
fabrication slot. Everything here is pre-silicon. Validation on real
chips waits for a TinyTapeout run.

## 1. Introduction

An RO-PUF compares the frequencies of identical ring oscillators and turns
each comparison into one response bit [1]. The appeal is that the secret is
never stored anywhere. It is read out of manufacturing randomness, and that
only works if the randomness is actually random. If part of the frequency
difference is shared across dies, those response bits come out the same on
every chip, and an attacker with one characterized device can predict them on
the rest.

None of this is a new worry. Systematic and spatially correlated process
variation has been on the RO-PUF threat list for years [2, 3, 4], and the FPGA
community built a whole toolbox against it: hard macros, controlled placement,
randomized placement, configurable oscillators, statistical bias removal
[2, 5, 6, 7]. Every one of those tricks is a way of stopping the
implementation tool from giving the oscillators different physical
surroundings. But that literature lives on FPGAs, where the bias comes from
LUTs and switch-box routing on a fixed fabric, and it mostly stops there.

Meanwhile the hardware changed under it. Open PDKs and automated RTL-to-GDSII
flows [9, 10] now let individuals tape out real silicon through shuttles like
TinyTapeout and Efabless ChipIgnite. The bias source on these flows is
different: it is the metal that automated place-and-route wraps around each
standard-cell oscillator. I could not find anyone who had measured whether
that bias is big enough to break a PUF, or shown how to catch it before paying
for a fabrication slot you only get once. This paper does both for the
OpenLANE/sky130 flow.

Three things come out of it:

- a causal measurement: the automated flow spreads identical oscillators by
  8.8% peak-to-peak, deterministically, the same on every die, with the spread
  tracking extracted routing capacitance at *r* = −0.997;
- a fix that works inside the same open flow: a hardened, step-and-repeated
  macro, which removes the spread by construction and lands at 569.5 MHz,
  right at the auto-placed arm's operating point;
- a go/no-go test any shuttle user can run before tapeout, built from nothing
  but OpenROAD extraction and ngspice.

## 2. Background and related work

Suh and Devadas introduced the RO-PUF [1]. Maiti and Schaumont showed that
systematic variation hurts uniqueness and proposed configurable-RO
compensation [2]; later they measured the spatial structure of the variation
at scale [3]. Newer work treats strong spatial correlation as an outright
security threat [4]. On FPGAs, matched hard macros and controlled or
randomized placement raise uniqueness, and uncontrolled placement does worst
[2, 5]. Other papers remove the systematic part statistically [6] or design
constructions that tolerate bias [7]. Someone has already built an RO-PUF on
sky130 through TinyTapeout [11], but as a working implementation. It did not
ask where its entropy came from.

So the matched-layout fix is established on FPGAs. What was missing: anyone
showing the bias on the open ASIC flow, putting a number on it, and giving
people a test to run before fab. The full bibliography is in
`related_work.md`.

## 3. Design under test

The design is a two-arm RO-PUF, `tt_um_nikodemetrashvili20_ro_puf`, sized for
one TinyTapeout tile on sky130. Each arm has sixteen oscillators. A shared
serial core enables one oscillator at a time and counts its edges over a fixed
window, so every oscillator gets measured the exact same way. The oscillator
itself is a 31-stage ring: an enable NAND, thirty inverters, and an isolating
output buffer tapped at the middle of the chain, all sky130 standard cells
(`nand2_1`, `inv_1`, `buf_1`). A pre-layout SPICE check puts the ring at
633 MHz. A sky130 flip-flop counts that comfortably.

In the build studied here both arms are auto-placed by the flow, so the array
shows the automated-layout behaviour. I call that Arm A. Arm B, the matched
version, is built in Section 6.

## 4. Method

**Parasitics from the real layout.** Nothing is re-extracted or approximated.
The OpenLANE build outputs a routed gate-level netlist and OpenROAD RC
extraction (SPEF) at the nominal corner, the same parasitics the flow itself
uses for timing signoff. The netlist keeps all 32 oscillators with their
internal ring nodes, and the SPEF has a capacitance for every net.

**Per-oscillator SPICE.** A small generator reads the netlist and the SPEF and
writes out each oscillator exactly as routed. Each ring net's total extracted
capacitance (ground plus coupling, already summed on the SPEF `*D_NET` record)
hangs on the node as one lumped capacitor. Two decks come out: a control deck
with no parasitics and a parasitic deck with the extracted capacitance.

**Why lumped caps are enough here.** Only one oscillator runs at a time in
this design. While one is measured its neighbours sit still, so their coupling
capacitance acts as a fixed load to ground, which is exactly what the lumped
total models. Series wire resistance on these short nets shifts a stage delay
by under 0.1%, so I dropped it. Holding the transistors at nominal is the
point of the experiment, not a shortcut: it leaves layout parasitics as the
only difference between oscillators. Random device mismatch is a separate
study (Section 7).

**Startup.** Each oscillator is enable-started. The enable sits low, then
releases, which injects one edge and guarantees the fundamental mode, the same
way the chip does it. I learned this the hard way: a naive tie-high-and-kick
start excited higher-order ring modes that read as impossibly high
frequencies. Frequency is measured in ngspice over twenty periods after
enable.

## 5. Results

**Control.** With no parasitics, all 32 oscillators read exactly 633.640 MHz.
One value, zero spread, matching the standalone single-oscillator baseline. So
the instances really are identical, and whatever spread shows up in the
parasitic deck comes from parasitics alone.

**With extracted parasitics.** The 32 identical oscillators fan out:

| Quantity | Value |
|---|---|
| Mean frequency | 567.6 MHz (10.4% below control, from loading) |
| Std. deviation | 10.9 MHz (1.9% of mean) |
| Min / max | 539.1 MHz (RO10) / 589.2 MHz (RO4) |
| Peak-to-peak spread | 50.2 MHz = **8.8% of mean** |
| Extracted ring capacitance | 7.4 – 17.8 fF (mean 11.6) |

This spread is not noise. Frequency tracks extracted ring capacitance with
*r* = −0.997 at −4.93 MHz/fF (Figure 1a). The oscillator the router loaded
heaviest (RO10, 17.8 fF) is the slowest one. The oscillator it loaded lightest
(RO4, 7.4 fF) is the fastest. Everything in between lines up monotonically.
There is no mystery about the cause. The router wired each supposedly
identical oscillator with different metal.

Frequency barely correlates with where the oscillators sit (|*r*| < 0.27
against *x*, *y*, and distance from center; Figure 1b). So the bias is a
per-instance routing fingerprint rather than a smooth gradient across the die,
which is what you would expect from a global placer scattering each
oscillator's cells. That does not make it less dangerous. It is fixed by the
mask and it repeats on every fabricated die.

## 6. The fix

If the problem is that identical oscillators got different layouts, the cure
is to give them the same layout. I hardened one oscillator into a fixed
60 × 40 µm macro with LibreLane on sky130. The macro passes DRC, LVS
("circuits match uniquely") and antenna checks with the ring intact: thirty
inverters, the enable NAND, the buffer. Sixteen bit-identical copies then go
down on a uniform grid, and the full array passes DRC, LVS, antenna and
power-grid connectivity. The complete two-arm chip, both arms plus the
measurement core on a TinyTapeout 2×2 tile, builds through the same flow and
passes the same checks.

Every copy is the same GDS. The internal ring nets therefore carry identical
parasitics, and the oscillator-to-oscillator layout spread is zero by
construction, against 8.8% on the auto-placed arm (Figure 2). The only wiring
that differs per copy is enable and output. Those sit outside the oscillation
loop and do not set the frequency. The control result in Section 5 already
proved the logic: identical parasitics gave identical frequency. What is left
on a matched array is transistor mismatch, the real per-chip randomness a PUF
is supposed to run on.

**The matched frequency.** The macro's own routed build has its own extracted
parasitics (nom-corner SPEF), and since every copy is the same GDS, simulating
the macro once is simulating every Arm B oscillator. I used the same deck flow
as Section 4. Same models, same startup, same 20-period measurement. The
matched oscillator runs at **569.5 MHz**, 10.1% below its no-parasitic control
of 633.15 MHz, and that control reproduces the Section 5 control within 0.08%.
Two more checks say the number is solid. The macro's 11.0 fF of ring
capacitance lands mid-range of Arm A's 7.4 to 17.8 fF, and Arm A's own
capacitance fit predicts 570.2 MHz for that load; the simulation came in 0.12%
under it. Two different builds, one model, same answer. In short, the matched
design behaves like a typical Arm A routing (within 0.35% of the Arm A mean),
except all sixteen copies share it. The operating point stays. The 8.8% spread
goes to zero (Figure 2). Absolute numbers carry about 0.2% numerical timestep
uncertainty, forty times smaller than the effect being measured.

**Both arms in one chip.** The submitted two-arm build lets me run the whole
experiment on a single layout. Its extraction makes the matching argument by
itself: the top-level SPEF contains all 496 ring nets of the auto-placed arm,
and not one net from inside the sixteen macro copies, because they are one
sealed block. The auto-placed arm's sixteen oscillators spread 29.7 MHz, 5.4%
peak-to-peak, with frequency tracking ring capacitance at r = -0.999 inside
this build alone (Figure 3). The matched arm sits at 569.5 MHz, sixteen
copies, one value. Two details are worth stopping on. First, the original
build's capacitance regression predicts this build's mean within 0.10%, so
the model now holds across three separate builds. Second, this build's Arm A
pattern differs from the first build's (5.4% versus 8.8%, mean 551.7 versus
567.6). The bias is not a property of the circuit. Every run of the tool
mints a new fingerprint, and each fingerprint is then frozen into every chip
made from that mask.

## 7. What this means for PUF entropy

To connect frequency spread to PUF metrics I model a population of chips. An
oscillator's frequency is a shared layout bias plus independent per-chip
mismatch, and each chip's key is a set of pairwise comparisons. With the
auto-placed arm carrying the shared bias and the matched arm carrying none,
the model (200 chips, eight comparison bits) gives inter-chip uniqueness of
13.2% for the auto-placed arm against 49.9% for the matched arm. Ideal is 50%.
An attacker who predicts a new chip's key from oscillator position alone
succeeds 91.2% of the time on the auto-placed arm. On the matched arm he does
no better than a coin flip (49.2%).

I want to be careful about what these numbers are. They use assumed bias and
mismatch magnitudes, so they illustrate the mechanism; they are not silicon
measurements. The silicon-accurate result is the extracted-parasitic spread in
Section 5. But they make the stakes plain. A PUF on the auto-placed array
leaks most of its key to anyone who characterizes a single chip.

**How big is the real entropy?** A Monte Carlo pass over the PDK's own
mismatch models puts a number on it. sky130's mismatch parameters draw once
per ngspice run and shift every device of a class together, so I measured
the matched oscillator's common-draw sigma over 40 runs (0.345%) and scaled
it by sqrt(31) for independent per-device draws, which is first-order exact
for 31 near-identical stages. That gives a per-ring mismatch sigma of
0.062%. Virtual chips built from it reach 50.7% key uniqueness, right at the
ideal. Held against it, the auto-placed arm's measured layout spread is 21.6
times larger by standard deviation and 87 times by peak-to-peak. That is the
problem in two numbers. The fake entropy is more than twenty times the size
of the real entropy it buries, and only the fake part repeats across
chips.

## 8. Limitations

The frequency results use a lumped-capacitance model (argued in Section 4).
Absolute frequencies are good to a few percent; the relative spread and the
*r* = −0.997 mechanism are the solid part. Transistors are nominal at the
nominal corner on purpose, to isolate the layout effect. Min/max corners exist
and can bracket things later. The per-oscillator centroid is a rough stand-in
for "position" when the placer scatters cells. The uniqueness and
predictability numbers in Section 7 are a parametric projection, not a
measurement. And everything here is pre-silicon. It is exactly the kind of
simulation you run before fabrication, which is the point, and it will be
checked on real TinyTapeout chips.

## 9. Conclusion and future work

On the open-source sky130 flow, automated place-and-route stamps a large,
deterministic frequency bias onto identical ring oscillators. It is the same
on every die. Per-oscillator routing capacitance explains almost all of it. A
naive RO-PUF would ship that pattern as its "entropy" on every chip it ever
manufactured. A hardened, step-and-repeated macro removes the bias by
construction, and the test that catches it needs only open tools and the
design's own extracted parasitics, so any shuttle user can run it before a
one-shot fabrication.

Next steps, in order: SPICE-level Monte Carlo with sky130 mismatch models to
get the real-entropy uniqueness distribution; then, once the dual-arm chip
comes back from fab, measuring both arms across dies, voltage and temperature.
The prediction to falsify is specific. The auto-placed arm's pattern should
repeat across chips. The matched arm's should not.

## Figures

- **Figure 1** (`sim/spice/gono/ro_gono.png`): (a) oscillation frequency
  against extracted ring capacitance, with the linear fit (−4.93 MHz/fF,
  *r* = −0.997) and the no-parasitic control line; (b) spatial map of
  oscillator frequency.
- **Figure 2** (`sim/spice/gono/armB_prediction.png`): per-oscillator
  frequency and layout-induced spread, auto-placed arm (8.8%) against matched
  macro (0%, at its measured 569.5 MHz).
- **Figure 3** (`sim/spice/gono/dualarm_gono.png`): both arms measured from
  the one submitted two-arm build. Auto-placed arm 5.4% spread, matched arm
  one frequency.

## References

See `related_work.md` for the annotated bibliography. Key references: Suh &
Devadas, DAC 2007 [1]; Maiti & Schaumont, J. Cryptology 2011 [2]; Maiti et
al., HOST 2010 [3]; OpenLANE, 2020 [9]; SkyWater sky130 PDK [10]; TinyTapeout
sky130 RO-PUF [11].
