# Deterministic layout contribution in an RO-PUF: pre-silicon results

This note records the nominal post-layout simulations behind the SILICON
project's numbers. Inputs, generated decks, raw ngspice logs, and analysis
scripts live under `sim/spice/gono/`. The scientific argument and the
limitations discussion are in the paper; this file keeps the run detail.

## Summary

An earlier build routed 32 logically identical ring oscillators separately.
With transistors held at the nominal corner, a lumped-capacitance model from
the routed SPEF produced an 8.8% peak-to-peak frequency spread, and
frequency tracked extracted ring capacitance with Pearson *r* = -0.997.
Arm A of the archived dual-arm layout shows the same mechanism at 5.4%
peak-to-peak and *r* = -0.999. Arm B's comparison point is one nominal
simulation of the hardened macro's extracted internal parasitics, 569.5 MHz,
drawn as a reference line because all sixteen instances share that internal
GDS.

## Design under test

The top module, `tt_um_nikodemetrashvili20_ro_puf`, contains two
16-oscillator arms and one shared counter. Each oscillator has an enable
NAND, 30 inverters, and a buffered tap at the middle of the ring. Arm A is
built from standard cells placed and routed with the surrounding logic.
Arm B instantiates the hardened `ro_macro_hard` block sixteen times.

The earlier 32-oscillator baseline is retained because it provides a second
routed layout on which to check whether the capacitance association was
peculiar to one flow run. It was not.

## Method

### Routed inputs

The generator reads the nominal-corner routed netlist, SPEF, and DEF emitted
by the flow. The netlist identifies every Arm A ring node, the SPEF gives
each net's total capacitance, and the DEF supplies placement centroids. The
analysis scripts perform no new RC extraction.

### SPICE model

For each Arm A oscillator, the generator reproduces the ring topology and
places the SPEF `*D_NET` total capacitance on each ring node as a grounded
lumped load. Two combined decks come out: a control deck with no extracted
capacitance, and a nominal post-layout deck with it.

On the chip only one oscillator is enabled at a time. In the generated deck
all 16 reconstructed oscillators run concurrently; under this reduced model
that changes nothing, since they share only an ideal 1.8 V source and no
coupling elements are carried over. Series wire resistance is dropped
entirely, and I have not quantified its effect yet, which is one of the jobs
of the planned distributed-RC comparison. Transistors stay at nominal values to isolate
implementation differences. Each oscillator starts with enable low and is
released with an enable pulse, and frequency is measured over twenty periods
after startup.

## Earlier 32-oscillator build

All 32 no-parasitic instances read 633.640 MHz in the generated control
deck, which checks that the generator gave them the same topology and
stimulus.

With extracted capacitance the mean is 567.6 MHz. The population standard
deviation across the 32 routed instances is 10.8 MHz, 1.90% of the mean.
Frequencies run from about 539.1 MHz (RO10) to 589.2 MHz (RO4), a 50.2 MHz
or 8.8% peak-to-peak spread. Extracted ring capacitance runs from 7.4 to
17.8 fF. Frequency and capacitance have Pearson *r* = -0.997 with a fitted
slope of -4.93 MHz/fF. That extracted capacitance is the only thing the model
varies, so a correlation this strong is expected; the slope and the 8.8%
spread are the parts that carry physical meaning. Correlation with placement
centroid is weak (absolute *r* below 0.27 for the tested coordinates), so the
spread behaves like a per-instance routing fingerprint rather than a die-wide
gradient.

![frequency association and spatial map](../sim/spice/gono/ro_gono.png)

## Hardened Arm B macro

The `ro_macro_hard` layout passes the checked-in DRC, LVS, and antenna
checks, and its standalone 16-copy array passes DRC, LVS, antenna, and
power-connectivity checks. Reusing the macro gives each instance the same
internal ring geometry.

The macro's own nominal SPEF is simulated with the same startup and
lumped-capacitance method. The no-parasitic control reads 633.15 MHz, within
0.08% of the earlier control. The extracted result is 569.5 MHz, 10.1% below
its control, with 11.01 fF of extracted ring capacitance. Applying the
earlier Arm A capacitance fit to that load predicts 570.2 MHz, 0.12% above
the macro simulation, and the macro lands within 0.35% of the earlier Arm A
mean. A 5 ps versus 1 ps timestep comparison moves the result by about 0.2%,
which bounds the numerical error well below the layout effect. The matched arm
removes the internal-layout term by construction. It does not show that Arm B
has a smaller total spread than Arm A; that comparison needs fabricated
chips.

![earlier Arm A distribution and the matched-macro reference line](../sim/spice/gono/armB_prediction.png)

## Coherent dual-arm build

The current design is built in one coherent flow run on a TinyTapeout 2x2
block, and `gen_dualarm_decks.py` reads that run's nominal SPEF and DEF. The
build passes Magic DRC, KLayout DRC, XOR, LVS, antenna, and power grid with
zero violations, so these numbers and the manufacturable GDS come from the
same place. The no-parasitic control gives all 16 instances 633.64 MHz. With
extracted capacitance, Arm A runs from 540.0 to 570.7 MHz: 30.7 MHz or 5.53%
peak-to-peak, mean 554.7 MHz, population standard deviation 1.65%, and
*r* = -0.9997 against ring capacitance with a fitted slope of -4.94 MHz/fF.
Ring loads span 10.9 to 17.0 fF and form a smooth band; the two heaviest
differ by 0.34 fF, so no single instance drives the range here.

The top-level SPEF does not expand the sealed macro internals (the extractor
cannot tell the sixteen copies apart), so Arm B is represented by the single
569.5 MHz macro result as a reference line. That reference sits above the Arm A
mean but not above every instance: RO7 reaches 570.7 MHz on a 10.9 fF load,
about 0.2% past the macro, which is finer than this model resolves.

Two things are worth recording beyond the single build. The 32-oscillator
build's fitted capacitance relation predicts this build's mean to about 0.1%,
so the mechanism carries across independent runs, and this build's own slope of
-4.94 MHz/fF is within a fraction of a percent of that earlier fit. The
peak-to-peak figure is much less stable than the mechanism: across nine builds
that vary only placement density it moves between 4.19% and 6.99%, median 5.75%
(`dualarm/placement_sweep/`). An older build reported 10.5%, above that band,
with most of its range coming from one oscillator loaded at 24.4 fF. The
archived `dualarm/build_debug/` snapshot (5.4%, older RTL, KLayout checks off)
is kept for contrast; this coherent build supersedes it.

![Arm A of the coherent dual-arm build with the matched-macro reference line](../sim/spice/gono/dualarm_gono.png)

## Preliminary mismatch scale

The study under `sim/spice/mc/` runs the matched macro with the PDK's
mismatch switch enabled and process variation disabled. The parameters used
by ngspice are global draws per device class, so 40 runs measure a
common-draw frequency standard deviation of 0.345%, not independent
mismatch inside one ring.

Dividing by `sqrt(31)` gives a first-order 0.062% per-ring estimate under
equal, independent stage sensitivities. The NAND's structure and unequal
device sensitivities make that scaling approximate, and 40 draws leave real
sampling uncertainty: the analyzer reports a sampling-only interval of
0.051% to 0.080% at roughly 95% coverage. The implied layout-to-mismatch
ratios (about 21.6 by standard deviation, 87 by peak-to-peak against the
archived Arm A build) are scale estimates that inherit these assumptions,
which is why the paper quotes them only as motivation for the silicon
measurement.

## The silicon test

The prediction: under matched measurement conditions, Arm A will show greater
centred-pattern correlation across chips than Arm B. Multiple
chips and repeated voltage and temperature measurements are needed to test
it, and a weak or negative result would force a revision of the
interpretation above. The model limitations behind all of these numbers are
collected in the paper's limitations section rather than repeated here.

## Reproducibility map

- `gen_decks.py`, `ro_all_*.spice`, `ctrl2.txt`, `par2.txt`, `verify.py`:
  earlier 32-oscillator build.
- `gen_dualarm_decks.py`, `dualarm_*.spice`, `dualarm_*_out.txt`,
  `verify_dualarm.py`: Arm A in the archived dual-arm layout.
- `gen_macro_deck.py`, `ro_macro_matched*.spice`, `macro*_out.txt`,
  `verify_macro.py`: the hardened-macro reference.
- `analyze.py` plus the figure scripts: descriptive statistics and plots.
- `first_build/` and `dualarm/build_debug/`: routed inputs for the two Arm A
  analyses.

The verify scripts recompute the headline quantities from the archived logs
and exit nonzero on any mismatch. The portable runner resolves local PDK
paths in a temporary deck without editing the checked-in files.
