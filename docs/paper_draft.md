# Deterministic Layout Bias in a Ring-Oscillator PUF: A Pre-Silicon Study on the Open SKY130 Flow

**Nikoloz Demetrashvili** · Independent researcher · Georgia

Draft, 2026-07-22

---

## Abstract

Ring-oscillator physical unclonable functions (RO-PUFs) rely on manufacturing
variation to distinguish nominally identical oscillators. Their physical
implementation can also introduce a deterministic frequency pattern. This
work isolates that implementation contribution in layouts produced by the
OpenLane/OpenROAD flow with the open SKY130 process design kit. Routed
netlists and extracted capacitances are simulated at the nominal device
corner; no fabricated devices have been measured.

In an archived dual-arm physical snapshot, the 16 automatically placed
oscillators have a 5.4% peak-to-peak nominal post-layout frequency spread.
Frequency and total
extracted ring capacitance are strongly anticorrelated (Pearson
*r* = -0.999). An earlier automatically placed 32-oscillator layout showed an
8.8% spread and *r* = -0.997. These results show a sizeable deterministic
layout component in these particular routed designs. They do not establish
how that component compares with device mismatch across fabricated dies.

The comparison arm uses 16 instances of one hardened oscillator macro with a
common internal layout. One extraction and one nominal post-layout simulation
of that macro produce a 569.5 MHz reference result. Repeating that value for
the 16 instances in a plot represents their common internal geometry; it is
not 16 independent simulations or measurements. The matched construction is
intended to suppress internal-layout differences, while top-level routing,
process variation, voltage, temperature, ageing, and measurement noise remain
to be evaluated.

The immediate contribution is a repository-traceable pre-fabrication
diagnostic for
separating nominal layout bias from the intended source of RO-PUF variation.
Whether the observed layout pattern repeats across dies, affects uniqueness,
or creates a practical prediction attack remains a registered hypothesis for
silicon testing.

## 1. Introduction

An RO-PUF compares the frequencies of nominally identical ring oscillators
and converts one or more comparisons into response bits [1]. Ideally, the
useful chip-to-chip differences arise from manufacturing variation. In
practice, placement and routing can give instances different parasitic loads,
adding a deterministic component to the response.

That distinction matters. A fixed layout pattern is not, by itself, evidence
of a security failure: random mismatch may be larger, comparisons may cancel
common structure, and response processing may reduce bias. But a
layout component that is stable across chips could reduce uniqueness or make
some comparisons easier to predict. Establishing either outcome requires
measurements from multiple fabricated devices under controlled conditions.

This paper reports the pre-silicon part of that investigation. It asks a
narrow question: how much nominal frequency variation is introduced by the
physical implementation of one open-source RO-PUF design, with transistor
parameters held fixed? The study contributes:

- nominal post-layout results for an automatically placed oscillator array,
  including an earlier 32-oscillator layout and the 16-oscillator Arm A in an
  archived dual-arm build;
- a capacitance-based explanation for the observed spread in those layouts;
- a matched-macro Arm B that gives every instance the same internal geometry;
- scripts and checks that allow the same diagnostic to be run before
  fabrication; and
- explicit hypotheses and measurement requirements for the later silicon
  study.

The findings are deliberately limited to the routed layouts and simulation
model described here. They are predictions about nominal implementation
effects, not measurements of fabricated PUF entropy, reliability, uniqueness,
or attack success.

## 2. Background and related work

Suh and Devadas introduced the widely used RO-PUF construction [1]. Maiti and
Schaumont examined improved ring-oscillator PUF designs and compensation for
systematic effects [2], while later FPGA studies mapped spatial variation and
studied placement-dependent behaviour [3, 5]. Other work has proposed
statistical bias reduction, configurable structures, and placement-aware
designs [5-8]. Katzenbeisser et al. evaluated several PUF constructions,
including ring oscillators, across 96 ASICs [12].

Prior literature does not support the simple rule that any spatial or
systematic structure makes an RO-PUF predictable. In particular, Wilde,
Hiller, and Pehl found that adjacent-oscillator comparisons reduced exploitable
spatial structure in their data and that estimated covariance was too small
for their proposed predictor to outperform the relevant baseline [4]. That is
important counterevidence: layout bias must be evaluated together with the
comparison scheme, mismatch distribution, sampling plan, and attacker model.

Open-source ASIC flows make a useful additional experiment possible. The
designer can inspect the routed netlist and parasitic extraction before
fabrication, rather than treating the physical implementation as opaque.
OpenLane/OpenROAD [9] and the open SKY130 PDK [10] provide that setting, and a
separate TinyTapeout RO-PUF project demonstrates the general feasibility of
the circuit family in the same ecosystem [11]. The present work focuses on a
specific missing measurement: the nominal frequency component associated with
instance-dependent routing in one automated layout.

## 3. Design under test

The current candidate, `tt_um_nikodemetrashvili20_ro_puf`, occupies a
TinyTapeout 2x2 tile. It contains two 16-oscillator arms and a shared serial
measurement core. The core enables one oscillator at a time and counts its
edges over a fixed window.

The nominal dual-arm physical results below come from an archived build of an
earlier RTL revision. The current RTL adds synchronized controls, selector
latching, and a stopped-counter stability handshake. Because those changes can
alter placement and routing, the archived render, SPEF, metrics, and 5.4%
result must not be treated as the current candidate's physical signoff.

Each oscillator is a 31-stage ring built from SKY130 standard cells: an enable
NAND, 30 inverters, and an isolating output buffer tapped near the middle of
the chain. A nominal pre-layout SPICE control is approximately 633 MHz. Arm A
allows the normal flow to place and route each oscillator. Arm B instantiates
16 copies of one hardened oscillator macro on a regular grid. The logical
oscillator is the same in both arms; the physical implementation method is the
experimental variable.

Figure 1 summarizes the design. The comparison is not a claim that the two
arms are otherwise perfect experimental twins. Arm B has a macro boundary and
different top-level connectivity, and those differences must be considered
when interpreting both simulation and future measurements.

![Figure 1. Block diagram of the two-arm design. Arm A lets the flow place and route each oscillator separately; Arm B repeats one hardened macro with common internal geometry.](figures/chip_block.png)

## 4. Method

### 4.1 Extraction and deck generation

The flow starts from the routed gate-level netlist and the OpenROAD SPEF at the
nominal corner. A generator identifies each oscillator and adds the total
extracted capacitance from each ring net's SPEF `*D_NET` record as a lumped
load. It produces two ngspice decks per automatically placed oscillator:

1. a control deck without extracted parasitic capacitance; and
2. a post-layout deck with the extracted ring-net capacitances.

The device models remain nominal. This isolates the modelled layout
contribution rather than attempting to simulate the population distribution
of fabricated parts.

For the matched arm, the hardened oscillator macro is extracted and simulated
once. Because the 16 macro instances use the same internal GDS geometry, that
single result is a useful internal-layout reference. It does not include 16
independent mismatch draws, instance-specific top-level parasitics, or 16
separate observations.

### 4.2 Approximation and startup

Only one oscillator is intended to run at a time. The present decks therefore
use total capacitance as a lumped load and omit distributed wire resistance.
This is a modelling choice, not a sign-off guarantee. Coupling activity,
distributed RC, supply-network interaction, package effects, and substrate
effects are not represented in full. The relative nominal results are more
informative than the absolute frequency prediction.

Each oscillator starts disabled and is then enabled, which injects the
transition needed for startup. Frequency is measured over 20 periods after
enable. This procedure avoids a previously observed simulation artefact in
which an artificial initial condition excited an unintended ring mode.

### 4.3 Reported statistics

For each automatically placed array, the analysis reports mean, sample
standard deviation, range, peak-to-peak range divided by the mean, and Pearson
correlation between frequency and extracted ring capacitance. The oscillator
instances within one routed design are not independent samples from a chip
population. Consequently, the reported correlations are descriptive for that
layout; no population confidence interval or across-die inference is claimed.

## 5. Automatically placed arrays

### 5.1 Earlier 32-oscillator layout

The earlier build automatically placed all 32 oscillators. In the no-parasitic
control, the decks produced the same nominal frequency, approximately
633.640 MHz. With extracted capacitance, the mean was 567.6 MHz and the sample
standard deviation was 10.9 MHz. Frequencies ranged from approximately 539 to
589 MHz, a 50.2 MHz or 8.8% peak-to-peak spread relative to the mean.

Extracted ring capacitance ranged from 7.4 to 17.8 fF. Frequency and
capacitance had Pearson *r* = -0.997, with a fitted slope of approximately
-4.93 MHz/fF (Figure 2a). Correlations with simple placement coordinates were
smaller in magnitude (|*r*| < 0.27; Figure 2b). For this layout and model, the
result is consistent with instance-specific routing load rather than a simple
die-wide spatial gradient.

![Figure 2. Nominal post-layout results for the earlier 32-oscillator automatically placed layout: frequency versus extracted ring capacitance, with the no-parasitic control, and a spatial frequency map.](../sim/spice/gono/ro_gono.png)

### 5.2 Archived dual-arm Arm A

The archived dual-arm layout contains 16 automatically placed oscillators in
Arm A. Its nominal post-layout frequencies have a mean of 551.7 MHz and a
29.7 MHz peak-to-peak range, or 5.4% of the mean. Frequency and extracted
ring capacitance have Pearson *r* = -0.999 (Figure 4).

The earlier and archived dual-arm layouts do not have the same frequency pattern or
spread. That difference supports the narrower conclusion that routing choices
can materially affect the nominal pattern. It does not show what proportion
of the response will be common across fabricated dies from either mask.

## 6. Matched-macro arm

The matched construction hardens one oscillator as a 60 x 40 micrometre
macro. The macro-level layout passes the available DRC, LVS, antenna, and
connectivity checks, and the 16 instances are placed on a regular grid in Arm
B. These checks establish consistency with the implemented design rules and
netlist; they do not validate PUF quality or silicon behaviour.

The extracted macro has approximately 11.0 fF of total ring capacitance. One
nominal post-layout simulation gives 569.5 MHz, compared with a no-parasitic
control of approximately 633.15 MHz. The earlier Arm A capacitance fit predicts
about 570.2 MHz at that load. This agreement is a useful cross-check on the
nominal model, but it is not an independent silicon validation.

![Figure 3. The earlier automatically placed array beside the 569.5 MHz nominal macro reference repeated at 16 Arm B positions. The repeated green points represent common internal geometry and are not independent observations.](../sim/spice/gono/armB_prediction.png)

Figures 3 and 4 repeat the 569.5 MHz macro result across 16 Arm B positions to
show that the internal macro geometry is common. The repeated points must not
be read as 16 simulations, 16 measurements, or evidence of no Arm B spread in
fabricated devices. The construction removes intended differences in the
internal routed ring. Device mismatch, local process gradients, top-level
enable and output routing, supply variation, temperature, ageing, and
measurement noise can still separate the instances.

![Figure 4. Archived dual-arm Arm A nominal post-layout frequencies beside the same single 569.5 MHz macro result repeated at 16 Arm B positions; the Arm B points are not 16 simulations or measurements.](../sim/spice/gono/dualarm_gono.png)

## 7. Security interpretation and planned silicon test

### 7.1 Parametric examples

The analysis repository includes a simple virtual-population model in which
each oscillator frequency is the sum of a shared layout term and an
independent mismatch term. Under one chosen set of assumptions, 200 virtual
chips and eight adjacent comparison bits produced 13.2% inter-chip Hamming
distance for the automatically placed pattern and 49.9% for the matched
pattern; a position-based predictor scored 91.2% and 49.2%, respectively.

Those values are illustrative outputs of the assumed model. They are not
measurements, calibrated forecasts, confidence bounds, or evidence of a
practical attack. Changing the mismatch scale, covariance, comparison pairs,
noise, or attacker information can change the result substantially. The
repository should therefore use these numbers only to explain the proposed
mechanism and motivate the silicon experiment.

### 7.2 Mismatch estimate

A separate 40-run ngspice Monte Carlo exercise used the PDK models' available
global draw and observed a frequency standard deviation of 0.345%. Dividing
by `sqrt(31)` gives 0.062% as a first-order scale estimate for independent
contributions from 31 similar stages. This transformation assumes independence
and equal contribution, neither of which is established by those 40 global
draws. A sampling-only approximation puts the common-draw sigma at 0.283% to
0.443% and the scaled value at 0.051% to 0.080% with about 95% coverage. That
interval does not include uncertainty from the `sqrt(31)` model itself. The
result is not a measured mismatch distribution or an entropy estimate.

Comparisons such as 21.6x by standard deviation or 87x by peak-to-peak depend
on that approximate denominator and mix statistics with different sampling
properties. They may be useful as sensitivity examples, but they should not
be presented as measured ratios between layout variation and manufacturing
variation.

### 7.3 Registered hypotheses and metrics

The central silicon hypothesis is that Arm A will retain more of the nominal
layout pattern across dies than Arm B. A proper test requires multiple chip
IDs, repeated measurements, matched voltage and temperature settings, and a
fixed comparison rule. The firmware records chip and condition labels so the
analysis can keep those groups separate.

The planned descriptive metrics are:

- repeatability within each chip and condition, including timeout and missing
  oscillator rates;
- centered pattern correlation across distinct chips measured under the same
  known condition;
- inter-chip Hamming distance for a predeclared set of adjacent comparison
  pairs; and
- within-chip response changes across voltage and temperature conditions.

Results will be reported only when the grouping and completeness requirements
are met. A single chip, one condition, incomplete oscillator vectors, or
unknown clock/window settings are insufficient for the corresponding
population or reliability claim. Sample size and uncertainty intervals should
be specified before interpreting the security significance of the data.

## 8. Limitations

This study is pre-silicon. It measures neither a fabricated oscillator nor a
PUF response population. Its main limitations are:

- nominal transistor models do not capture random local mismatch;
- lumped capacitance omits parts of distributed RC and dynamic coupling;
- one earlier layout and one archived dual-arm layout do not define a distribution
  over place-and-route seeds, floorplans, flows, or technologies;
- oscillator instances within a layout are related observations, so ordinary
  instance-level confidence intervals would overstate the evidence;
- Pearson correlation establishes association in the modelled layout but does
  not by itself prove a complete causal or security model;
- the Arm B plot repeats one macro result and cannot quantify fabricated Arm B
  variation;
- the 40-run global Monte Carlo exercise does not reproduce independent local
  device mismatch and is too small for a precise tail estimate;
- voltage, temperature, supply noise, ageing, package, and measurement-system
  effects remain uncharacterized; and
- uniqueness, reliability, min-entropy, and attack success require a
  multi-chip data set and a stated threat model.

These limitations do not erase the observed nominal layout component. They
set the boundary on what can be concluded from it.

## 9. Conclusion

Two automatically placed SKY130 RO arrays show a nominal post-layout
frequency pattern that tracks extracted ring capacitance closely. The
archived dual-arm Arm A has a 5.4% peak-to-peak spread and *r* = -0.999; an earlier
32-oscillator layout has an 8.8% spread and *r* = -0.997. A hardened macro
provides a 569.5 MHz common-internal-layout reference for Arm B.

The supported conclusion is that automated physical implementation introduced
a sizeable deterministic component in these routed designs. The stronger
claims remain open: whether the pattern is stable across fabricated dies,
whether it dominates mismatch and environmental noise, whether it reduces
useful PUF uniqueness, and whether an attacker can exploit it. The current
dual-arm candidate and grouped firmware protocol are intended to answer those
questions with silicon data, after a fresh physical flow replaces the stale
dual-arm snapshot.

## References

[1] G. E. Suh and S. Devadas, "Physical Unclonable Functions for Device
Authentication and Secret Key Generation," *Proceedings of the 44th ACM/IEEE
Design Automation Conference (DAC)*, pp. 9-14, 2007.
https://doi.org/10.1145/1278480.1278484

[2] A. Maiti and P. Schaumont, "Improved Ring Oscillator PUF: An FPGA-Friendly
Secure Primitive," *Journal of Cryptology*, vol. 24, pp. 375-397, 2011.
https://doi.org/10.1007/s00145-010-9088-4

[3] A. Maiti, J. Casarona, L. McHale, and P. Schaumont, "A Large Scale
Characterization of RO-PUF," *IEEE International Symposium on
Hardware-Oriented Security and Trust (HOST)*, pp. 66-71, 2010.
https://schaumont.dyn.wpi.edu/schaum/pdf/papers/2010hostm.pdf

[4] F. Wilde, M. Hiller, and M. Pehl, "Statistic-Based Security Analysis of
Ring Oscillator PUFs," *2014 International Symposium on Integrated Circuits
(ISIC)*, pp. 148-151, 2014.
https://doi.org/10.1109/ISICIR.2014.7029528

[5] A. S. Chauhan, V. Sahula, and A. S. Mandal, "Novel Randomized Placement
for FPGA Based Robust ROPUF with Improved Uniqueness," *Journal of Electronic
Testing*, vol. 35, no. 5, pp. 581-601, 2019.
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
