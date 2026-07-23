# Deterministic Layout Bias in a Ring-Oscillator PUF: A Pre-Silicon Study on the Open SKY130 Flow

**Nikoloz Demetrashvili** · Independent researcher · Georgia

Draft, 2026-07-23

---

## Abstract

A ring-oscillator physical unclonable function (RO-PUF) turns manufacturing
variation between nominally identical oscillators into a device secret. The
physical implementation can add a deterministic frequency pattern of its own
on top of that variation. I isolate this implementation contribution for
layouts produced by the OpenLane/OpenROAD flow with the open SKY130 process
design kit, by simulating routed netlists and extracted capacitances at the
nominal device corner. No fabricated devices have been measured yet.

In an archived dual-arm build, the 16 automatically placed oscillators of
Arm A spread 5.4% peak to peak in nominal post-layout simulation; an earlier
automatically placed 32-oscillator layout spread 8.8%. The two layouts
produced different frequency patterns, which fits placement and routing
setting the bias run by run. Within this lumped-capacitance model the spread
is almost entirely explained by the extracted ring capacitance the model puts
back in as a load (Pearson *r* = -0.999 and -0.997), so the result worth
keeping is the size of the spread and its physical cause, not the coefficient.
The comparison arm, Arm B, uses one hardened oscillator macro sixteen times.
A single extraction of that macro gives a 569.5 MHz reference for the shared
internal layout, which removes internal-layout variation by construction but
does not on its own prove a smaller total spread once the chips are made.

The contribution is a pre-fabrication diagnostic, traceable in the
repository, that separates nominal layout bias from the variation a PUF is
supposed to use. Whether the layout pattern repeats across dies, reduces
uniqueness, or enables a practical prediction attack is left for the silicon
phase, not claimed here.

## 1. Introduction

An RO-PUF compares the frequencies of nominally identical ring oscillators
and converts comparisons into response bits [1]. Ideally the useful
chip-to-chip differences come from manufacturing variation. In practice,
placement and routing give instances different parasitic loads, which adds a
deterministic component to the comparison.

A fixed layout pattern is not automatically a security failure. Random
mismatch may be larger, comparisons may cancel shared structure, and response
processing may absorb bias. But a layout component that repeats across chips
could reduce uniqueness or make some comparisons predictable, and deciding
between those outcomes takes measurements from multiple fabricated devices.

This paper reports the pre-silicon part of that investigation. The question
is narrow: with transistor parameters held fixed, how much frequency
variation does the physical implementation of one open-source RO-PUF design
introduce? I contribute nominal post-layout results for two automatically
placed oscillator arrays, a capacitance-based explanation for the observed
spread, a matched-macro arm that gives every instance the same internal
geometry, the scripts to run the same diagnostic before any fabrication, and
the specific predictions I plan to test once chips come back.

## 2. Background and related work

Suh and Devadas introduced the widely used RO-PUF construction [1]. Maiti and
Schaumont examined improved ring-oscillator PUF designs and compensation for
systematic effects [2], and later FPGA studies mapped spatial variation and
placement-dependent behaviour [3, 5]. Other work proposes statistical bias
reduction, configurable structures, and placement-aware designs [5-8].
Katzenbeisser et al. evaluated several PUF constructions, including ring
oscillators, across 96 ASICs [12].

The literature does not support a simple rule that any systematic structure
makes an RO-PUF predictable. Wilde, Hiller, and Pehl found that
adjacent-oscillator comparisons reduced exploitable spatial structure in
their data, and that the estimated covariance was too small for their
predictor to beat the relevant baseline [4]. That is important
counterevidence: layout bias has to be judged together with the comparison
scheme, the mismatch distribution, and the attacker model.

Open-source ASIC flows allow an experiment that closed flows make awkward:
the designer can read the routed netlist and the parasitic extraction before
fabrication instead of treating the implementation as opaque.
OpenLane/OpenROAD [9] and the open SKY130 PDK [10] provide that setting, and
a TinyTapeout RO-PUF project shows the circuit family works in the same
ecosystem [11]. What I did not find is the measurement this paper makes: the
nominal frequency component tied to instance-dependent routing in one
automated ASIC layout, quantified from the flow's own extraction.

## 3. Design under test

The candidate design, `tt_um_nikodemetrashvili20_ro_puf`, occupies a
TinyTapeout 2x2 tile. It holds two 16-oscillator arms and a shared serial
measurement core that enables one oscillator at a time and counts its edges
over a fixed window.

Each oscillator is a 31-stage ring of SKY130 standard cells: an enable NAND,
30 inverters, and an isolating output buffer tapped near the middle of the
chain. A nominal pre-layout SPICE control sits near 633 MHz. Arm A lets the
flow place and route each oscillator with the surrounding logic. Arm B
places 16 copies of one hardened oscillator macro on a regular grid. The
logical circuit is identical in both arms; the physical implementation
method is the experimental variable. Figure 1 summarizes the design.

![Figure 1. Block diagram of the two-arm design. Arm A lets the flow place and route each oscillator separately; Arm B repeats one hardened macro with a common internal layout.](figures/chip_block.png)

Two caveats on the comparison itself. Arm B has a macro boundary and
different top-level connectivity, so the arms are not perfect experimental
twins. And the dual-arm physical results below come from an archived build
of an earlier RTL revision; the current source adds synchronized controls,
selector latching, and a stopped-counter stability handshake, and will go
through a fresh flow run before the shuttle order (see SIGNOFF.md in the
repository).

## 4. Method

The analysis starts from the routed gate-level netlist and the OpenROAD SPEF
at the nominal corner. A generator identifies each oscillator, takes the
total extracted capacitance from each ring net's SPEF `*D_NET` record, and
places it as a grounded lumped load. It emits two ngspice decks per
automatically placed oscillator: a control deck without parasitics and a
post-layout deck with them. Device models stay at the nominal corner, which
isolates the layout contribution instead of simulating a population of
fabricated parts.

Only one oscillator runs at a time in a real measurement, so coupling to
inactive neighbours is treated as a fixed grounded load, and distributed
wire resistance is omitted; a separate estimate put its stage-delay effect
below 0.1% for these nets. Each oscillator starts disabled and is released
by an enable pulse, which avoids a simulation artefact where an artificial
initial condition excited an unintended ring mode. Frequency is measured
over 20 periods after startup.

For the matched arm, the hardened macro is extracted and simulated once.
The 16 instances share one internal GDS, so this single result serves as
the internal-layout reference for all of them.

For each automatically placed array I report mean, standard deviation,
range, peak-to-peak spread relative to the mean, and the Pearson correlation
between frequency and extracted ring capacitance. Instances inside one
routed design are not independent samples from a chip population, so these
are descriptive statistics for that layout. The extracted capacitance is also
the only spread-producing input to the model, so a strong frequency-capacitance correlation is expected almost by construction. The coefficient
confirms the model behaves; the spread it produces, and the slope, are the
physically interesting parts.

## 5. Automatically placed arrays

### 5.1 Earlier 32-oscillator layout

The earlier build placed all 32 oscillators automatically. In the
no-parasitic control every deck produced the same nominal frequency,
approximately 633.640 MHz, which checks the generator itself. With extracted
capacitance the mean was 567.6 MHz with a standard deviation of 10.9 MHz.
Frequencies ranged from about 539 to 589 MHz, a 50.2 MHz or 8.8%
peak-to-peak spread.

Extracted ring capacitance ranged from 7.4 to 17.8 fF. Frequency and
capacitance had Pearson *r* = -0.997 with a fitted slope of about
-4.93 MHz/fF (Figure 2a). Correlations with placement coordinates were much
weaker (|*r*| < 0.27; Figure 2b). For this layout the spread behaves like an
instance-specific routing load, not a smooth die-wide gradient.

![Figure 2. Nominal post-layout results for the earlier 32-oscillator layout: frequency versus extracted ring capacitance with the no-parasitic control, and a spatial frequency map.](../sim/spice/gono/ro_gono.png)

### 5.2 Archived dual-arm Arm A

Arm A of the archived dual-arm layout contains 16 automatically placed
oscillators. Their nominal post-layout frequencies have a mean of 551.7 MHz
and a 29.7 MHz peak-to-peak range, 5.4% of the mean, with *r* = -0.999
against extracted ring capacitance (Figure 4).

The two builds do not share a frequency pattern or a spread. Two layouts are
not a distribution, but a difference this large fits placement and routing
setting the bias for each run. It also means a single layout cannot say what
fraction of the response will be common across dies.
Usefully, the earlier build's capacitance fit predicts the archived Arm A
mean within 0.10%, so the mechanism transfers between builds even though the
pattern does not.

## 6. Matched-macro arm

The matched construction hardens one oscillator as a 60 x 40 micrometre
macro. The macro layout passes the available DRC, LVS, antenna, and
connectivity checks, and Arm B places 16 instances of it on a regular grid.

The extracted macro carries about 11.0 fF of total ring capacitance. One
nominal post-layout simulation gives 569.5 MHz against a no-parasitic
control of 633.15 MHz. The earlier Arm A capacitance fit predicts 570.2 MHz
at that load, 0.12% away, a useful cross-check on the model. The macro
result also lands within 0.35% of the earlier Arm A mean, so matching did
not move the operating point.

Figures 3 and 4 draw Arm B as a single horizontal reference line at
569.5 MHz, because the sixteen instances share one internal layout and there
is only one extracted simulation behind it. By construction the internal
layout contributes zero spread; fabricated Arm B instances will still differ
through device mismatch, top-level routing, supply, and temperature. So the
honest pre-silicon claim is narrow. The matched arm removes the internal-layout term, and whether that gives a smaller total spread than Arm A is the
measurement the chip exists to make, not something these simulations show.

![Figure 3. The earlier 32-oscillator array beside the matched-macro reference line at 569.5 MHz.](../sim/spice/gono/armB_prediction.png)

![Figure 4. Arm A of the archived dual-arm build beside the same matched-macro reference line.](../sim/spice/gono/dualarm_gono.png)

## 7. Security interpretation and planned silicon test

### 7.1 Parametric examples

The repository includes a simple virtual-population model in which each
oscillator frequency is a shared layout term plus an independent mismatch
term. Under one set of assumptions, 200 virtual chips and eight adjacent
comparison bits gave 13.2% inter-chip Hamming distance for the automatically
placed pattern and 49.9% for the matched pattern; a position-based predictor
scored 91.2% and 49.2%. These numbers illustrate the proposed mechanism.
They move substantially when the assumed mismatch scale, comparison pairs,
or attacker information change, so I use them to motivate the silicon
experiment rather than to quantify a real attack.

### 7.2 Mismatch scale estimate

A 40-run ngspice Monte Carlo exercise with the PDK's global mismatch draw
gave a frequency standard deviation of 0.345%. Dividing by `sqrt(31)` gives
0.062% as a first-order estimate of the per-ring contribution from 31
similar stages, with a sampling-only interval of roughly 0.051% to 0.080%.
The scaling assumes equal, independent stage sensitivities, which the NAND
stage in particular violates, and 40 global draws are not independent local
mismatch. On this estimate the archived Arm A layout spread is roughly
twenty times the mismatch scale by standard deviation. I treat that ratio as
an argument that the layout term is large enough to be worth measuring, not
as a measured entropy figure; silicon will measure the denominator directly.

### 7.3 What silicon has to show

The main question for silicon is whether Arm A retains more of its nominal
layout pattern across dies than Arm B. Testing it needs multiple chip IDs, repeated
measurements, matched voltage and temperature settings, and a fixed
comparison rule; the firmware records chip and condition labels so groups
stay separate. The planned metrics are repeatability within chip and
condition, centered pattern correlation across chips under the same
condition, inter-chip Hamming distance for a predeclared set of adjacent
comparison pairs, and within-chip response changes across voltage and
temperature. Results count only when the grouping and completeness
requirements are met; a single chip or an incomplete oscillator vector does
not support a population claim.

## 8. Limitations

This study is pre-silicon, and its model is deliberately simple. Nominal
transistor models carry no random local mismatch. Lumped capacitance omits
distributed RC and dynamic coupling; a distributed-RC extraction would test
whether the frequency ordering and the spread survive a fuller electrical
model, and running it on the fresh build is the obvious next check. Two
layouts do not define a
distribution over place-and-route seeds, floorplans, flows, or technologies,
and instances within a layout are related observations, so instance-level
confidence intervals would overstate the evidence. The Arm B reference is
one simulation of one macro and cannot quantify fabricated Arm B variation.
The 40-run global Monte Carlo cannot reproduce independent local device
mismatch. Voltage, temperature, supply noise, ageing, package, and
measurement-system effects are uncharacterized until chips exist, and
uniqueness, reliability, min-entropy, and attack success all need a
multi-chip data set with a stated threat model. The ripple counter is clocked by the oscillator itself, and its behaviour at
the fastest corner is checked only in behavioural simulation; the standard-cell flop at the oscillator-to-counter boundary still needs extracted,
across-corner timing before I trust the fast end of the range. None of this
erases the observed nominal layout component; it bounds what can be concluded
from it.

## 9. Conclusion

Two automatically placed SKY130 RO arrays show a nominal post-layout
frequency pattern that tracks extracted ring capacitance closely: 5.4% peak
to peak with *r* = -0.999 in the archived dual-arm Arm A, 8.8% with
*r* = -0.997 in an earlier 32-oscillator build. A hardened macro provides a
569.5 MHz shared-internal-layout reference for Arm B. The supported
conclusion is that the automated physical implementation introduced a
sizeable deterministic component in these routed designs, and that the
mechanism, capacitive routing load, transfers between builds while the
pattern itself does not.

The stronger claims stay open on purpose. Whether the pattern survives
fabrication, dominates mismatch, reduces uniqueness, or supports a real
attack will be settled by measuring both arms of the fabricated chip under
the measurement protocol in the firmware, after a fresh physical flow replaces
the archived
snapshot.

## References

[1] G. E. Suh and S. Devadas, "Physical Unclonable Functions for Device
Authentication and Secret Key Generation," *Proceedings of the 44th ACM/IEEE
Design Automation Conference (DAC)*, pp. 9-14, 2007.
https://doi.org/10.1145/1278480.1278484

[2] A. Maiti and P. Schaumont, "Improved Ring Oscillator PUF: An
FPGA-Friendly Secure Primitive," *Journal of Cryptology*, vol. 24,
pp. 375-397, 2011. https://doi.org/10.1007/s00145-010-9088-4

[3] A. Maiti, J. Casarona, L. McHale, and P. Schaumont, "A Large Scale
Characterization of RO-PUF," *IEEE International Symposium on
Hardware-Oriented Security and Trust (HOST)*, pp. 66-71, 2010.
https://schaumont.dyn.wpi.edu/schaum/pdf/papers/2010hostm.pdf

[4] F. Wilde, M. Hiller, and M. Pehl, "Statistic-Based Security Analysis of
Ring Oscillator PUFs," *2014 International Symposium on Integrated Circuits
(ISIC)*, pp. 148-151, 2014. https://doi.org/10.1109/ISICIR.2014.7029528

[5] A. S. Chauhan, V. Sahula, and A. S. Mandal, "Novel Randomized Placement
for FPGA Based Robust ROPUF with Improved Uniqueness," *Journal of
Electronic Testing*, vol. 35, no. 5, pp. 581-601, 2019.
https://doi.org/10.1007/s10836-019-05829-5

[6] K. A. Asha, L. E. Hsu, A. Patyal, and H.-M. Chen, "Improving the Quality
of FPGA RO-PUF by Principal Component Analysis (PCA)," *ACM Journal on
Emerging Technologies in Computing Systems*, vol. 17, no. 3, article 34,
2021. https://doi.org/10.1145/3442444

[7] W.-C. Wang, Z. Li, J. Skudlarek, M. Larouche, M. Chen, and P. Gupta,
"UNBIAS PUF: A Physical Implementation Bias Agnostic Strong PUF,"
arXiv:1703.10725, 2017. https://arxiv.org/abs/1703.10725

[8] J. Miskelly, C. Gu, Q. Ma, Y. Cui, W. Liu, and M. O'Neill, "Modelling
Attack Analysis of Configurable Ring Oscillator (CRO) PUF Designs," *2018
IEEE 23rd International Conference on Digital Signal Processing (DSP)*,
pp. 1-5, 2018. https://doi.org/10.1109/ICDSP.2018.8631638

[9] M. Shalan and T. Edwards, "Building OpenLANE: A 130nm OpenROAD-based
Tapeout-Proven Flow," *2020 IEEE/ACM International Conference on Computer
Aided Design (ICCAD)*, article 110, pp. 1-6, 2020.
https://doi.org/10.1145/3400302.3415735

[10] SkyWater Technology and Google, "SkyWater Open Source PDK (SKY130)."
https://github.com/google/skywater-pdk

[11] litneet64, "RO-based Physically Unclonable Function in sky130
(TinyTapeout tt07)." https://github.com/litneet64/tt07-RO-based-PUF

[12] S. Katzenbeisser, U. Kocabas, V. Rozic, A.-R. Sadeghi, I. Verbauwhede,
and C. Wachsmann, "PUFs: Myth, Fact or Busted? A Security Evaluation of
Physically Unclonable Functions (PUFs) Cast in Silicon," *Cryptographic
Hardware and Embedded Systems (CHES 2012)*, LNCS 7428, pp. 283-301, 2012.
https://doi.org/10.1007/978-3-642-33027-8_17
