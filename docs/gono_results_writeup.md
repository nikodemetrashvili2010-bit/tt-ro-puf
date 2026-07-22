# Deterministic layout contribution in an RO-PUF: pre-silicon results

This note records the nominal post-layout simulations used by the SILICON
project. Inputs, generated decks, raw ngspice logs, and analysis scripts are
under `sim/spice/gono/`.

## Summary

An earlier build routed 32 logically identical ring oscillators separately.
With transistors held at the nominal corner, a lumped-capacitance model derived
from the routed SPEF produced an 8.8% peak-to-peak frequency spread. Frequency
was strongly associated with extracted ring capacitance (Pearson *r* =
-0.997). Arm A of an archived dual-arm layout showed the same mechanism at
5.4% peak-to-peak and *r* = -0.999.

These simulations isolate a deterministic layout contribution in two routed
designs. They do not show that complete frequency patterns or response bits
will repeat across fabricated chips. Device mismatch, voltage, temperature,
stress, and measurement noise have not yet been observed. Cross-die
repeatability is the hypothesis the fabricated experiment is meant to test.

Arm B uses sixteen instances of one hardened oscillator macro. Its comparison
point is one nominal simulation of that macro's extracted internal parasitics,
569.5 MHz, shown sixteen times because every instance uses the same internal
GDS. This is a structural prediction about internal layout matching, not
sixteen independent simulations or measurements.

## Design under test

The current top module, `tt_um_nikodemetrashvili20_ro_puf`, contains two
16-oscillator arms and one shared counter. Each oscillator has an enable NAND,
30 inverters, and a buffered tap at the middle of the ring. Arm A is built from
standard cells placed and routed with the surrounding logic. Arm B instantiates
the hardened `ro_macro_hard` block sixteen times.

The earlier baseline build placed all 32 oscillators as standard cells. It is
retained because it provides a second routed layout on which to check whether
the capacitance association was peculiar to one flow run.

## Method

### Routed inputs

The generator reads the nominal-corner routed netlist, SPEF, and DEF emitted by
the flow. The netlist identifies every Arm A ring node, the SPEF gives each
net's total capacitance, and the DEF supplies placement centroids. No new RC
extraction is performed by the analysis scripts.

### SPICE model

For each Arm A oscillator, the generator reproduces the ring topology and
places the SPEF `*D_NET` total capacitance on each ring node as a grounded
lumped load. Two combined decks are generated:

- a control deck with no extracted capacitance; and
- a nominal post-layout deck with the extracted capacitance.

Only one oscillator is enabled during a chip measurement. The model therefore
treats coupling to inactive neighboring logic as a fixed grounded load. Series
wire resistance is omitted; a separate estimate put its stage-delay effect
below 0.1% for these nets. This is an approximation and is one reason the work
should be described as a nominal post-layout model rather than a sign-off or
silicon model.

Transistors are held at nominal values to isolate implementation differences.
Each oscillator starts with enable low and is released with an enable pulse.
Frequency is measured over twenty periods after startup.

## Earlier 32-oscillator build

### Control

All 32 no-parasitic instances read 633.640 MHz in the generated control deck.
This checks that the generator gave them the same topology and stimulus.

### Nominal extracted-capacitance result

The mean frequency is 567.6 MHz. The population standard deviation across the
32 routed instances is 10.9 MHz, or 1.93% of the mean. Frequencies range from
about 539.1 MHz for RO10 to 589.2 MHz for RO4, a 50.2 MHz or 8.8%
peak-to-peak spread. Extracted ring capacitance ranges from 7.4 to 17.8 fF.

Across these 32 routed instances, frequency and ring capacitance have Pearson
*r* = -0.997 with a fitted slope of -4.93 MHz/fF. Correlation with placement
centroid is weak (absolute *r* below 0.27 for the tested coordinates). These
are descriptive statistics for one routed layout, not a random sample of
layouts or chips, so no population confidence interval is claimed.

![frequency association and spatial map](../sim/spice/gono/ro_gono.png)

## Hardened Arm B macro

The `ro_macro_hard` layout passes the checked-in DRC, LVS, and antenna checks.
Its standalone 16-copy array also has clean checked-in DRC, LVS, antenna, and
power-connectivity results. Reusing the macro means that each instance has the
same internal ring geometry. It does not guarantee identical frequencies in
fabricated silicon or remove top-level environmental effects.

### Macro frequency reference

The macro's own nominal SPEF is simulated with the same startup and
lumped-capacitance method. The no-parasitic control reads 633.15 MHz, within
0.08% of the earlier Arm A control. The extracted macro result is 569.5 MHz,
10.1% below its control. Its extracted ring capacitance is 11.01 fF. Applying
the earlier Arm A capacitance fit to that load predicts 570.2 MHz, 0.12% above
the macro simulation.

The 569.5 MHz point is within 0.35% of the earlier Arm A mean. A 5 ps versus
1 ps timestep comparison changes it by about 0.2%. Those checks support the
numerical consistency of the macro-level model; they do not quantify model
error against silicon.

![earlier Arm A distribution and one Arm B macro reference](../sim/spice/gono/armB_prediction.png)

## Archived dual-arm layout

The archived design occupies a TinyTapeout 2x2 block. `gen_dualarm_decks.py`
was used to build the Arm A decks from that run's nominal SPEF and DEF. Its
no-parasitic control gives all 16 generated Arm A instances 633.64 MHz. With
extracted capacitance, Arm A ranges from 534.8 to 564.5 MHz: 29.7 MHz or 5.4%
peak-to-peak, with a mean of 551.7 MHz and a population standard deviation of
1.34%. Frequency and ring capacitance have *r* = -0.999 across the 16
instances.

The current RTL is newer than this physical snapshot: it adds synchronized
controls, selector latching, and a stopped-counter stability handshake. The
archived DEF is also a mixed-stage checkpoint and is now rejected by the deck
generator instead of producing missing coordinates. A coherent fresh final
DEF/SPEF is required before regenerating or applying these values to the
current candidate.

The top-level SPEF does not expand the sealed macro internals. Arm B is
therefore represented by the one 569.5 MHz macro result repeated for its
sixteen common internal layouts. The green points in the figure are not
sixteen extracted top-level frequencies.

The earlier build's fitted capacitance relation predicts the archived Arm A
mean within 0.10%, and its fitted slope predicts the peak-to-peak span within
about 3%. The two layouts have different Arm A patterns and spreads. This is
consistent with each place-and-route result fixing its own deterministic
component, but cross-die persistence cannot be inferred from two layout runs.

![archived dual-arm Arm A result and repeated Arm B macro reference](../sim/spice/gono/dualarm_gono.png)

## Preliminary mismatch scale

The separate study under `sim/spice/mc/` runs the matched macro with the PDK's
mismatch switch enabled and process variation disabled. The PDK parameters
used by ngspice are global draws for a device class, so 40 runs measure a
common-draw frequency standard deviation of 0.345%, not independent mismatch
among devices in one ring.

The analysis divides that value by `sqrt(31)` to obtain a first-order 0.062%
per-ring estimate under equal, independent stage sensitivities. The NAND's
series/parallel structure and unequal device sensitivities make the scaling
approximate. Forty draws also leave substantial sampling uncertainty. The
analyzer reports a sampling-only interval of 0.051% to 0.080% for the scaled
value at roughly 95% coverage, while leaving model-form uncertainty
unquantified. The resulting layout-to-mismatch ratios
(about 21.6 by standard deviation and 87 by peak-to-peak) are scale estimates,
not measured entropy or security metrics.

## Limitations and registered silicon test

- The electrical model uses total capacitance as grounded lumped loads and
  omits distributed resistance and active coupling.
- Only nominal device and extraction corners are used for the main comparison.
- The correlation coefficients describe routed instances in one layout each;
  they are not estimates over a population of chips.
- Arm B contributes one internal-macro simulation, repeated in figures to show
  common geometry. Top-level supply, thermal, stress, and fabrication effects
  remain unmodelled.
- The mismatch scale uses a first-order transformation of 40 global PDK draws,
  not direct independent-device Monte Carlo.
- The architectural uniqueness and attack examples in the paper are
  parametric illustrations, not measurements.

The registered hardware prediction is that, under matched measurement
conditions, Arm A will have greater centred-pattern correlation across chips
than Arm B. Multiple chips and repeated voltage/temperature measurements are
needed to test that prediction. A negative or weak result would be informative
and would require revising the interpretation above.

## Reproducibility map

- `gen_decks.py`, `ro_all_*.spice`, `ctrl2.txt`, `par2.txt`, and `verify.py`:
  earlier 32-oscillator build.
- `gen_dualarm_decks.py`, `dualarm_*.spice`, `dualarm_*_out.txt`, and
  `verify_dualarm.py`: Arm A in the archived dual-arm layout.
- `gen_macro_deck.py`, `ro_macro_matched*.spice`, `macro*_out.txt`, and
  `verify_macro.py`: one hardened-macro reference.
- `analyze.py` and the figure scripts: descriptive tables and plots.
- `first_build/` and `dualarm/build_debug/`: routed inputs retained for the
  two Arm A analyses.

The verify scripts recompute selected headline quantities from the archived
logs. They are useful consistency checks, not independent experimental
replications. The portable runner resolves local PDK paths in a temporary deck
without editing the checked-in file. The original tool/PDK revision is still
unknown and should not be invented when reporting a reproduction.
