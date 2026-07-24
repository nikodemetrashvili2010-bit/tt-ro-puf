# Quantifying Routing-Induced Frequency Dispersion in an Open-Source SKY130 Ring-Oscillator PUF: A Pre-Silicon Study

**Nikoloz Demetrashvili** · Student researcher · Georgia

Draft, 2026-07-23

---

## Abstract

A ring-oscillator physical unclonable function (RO-PUF) turns manufacturing
variation between nominally identical oscillators into a device secret. The
physical implementation can add a frequency pattern of its own on top of that
variation. This paper quantifies one component of that pattern, the
instance-to-instance routing capacitance assigned by the automated
OpenLane/OpenROAD flow on the open SKY130 process design kit, using a reduced
model: nominal transistor-level models of the verified post-route oscillator
topology, loaded with each ring net's total extracted capacitance from the
final SPEF. No fabricated devices have been measured yet, and distributed
resistance and coupling are not represented.

Under this model, the 16 automatically placed oscillators of Arm A in a
coherent build of the current RTL spread 10.5% peak to peak (population SD
2.36%, mean 551.7 MHz). One oscillator with an unusually heavy routing load
(24.4 fF against a 11.7 to 17.0 fF range for the rest) contributes much of the
extreme range: without it the peak-to-peak figure is 4.6% and the SD 1.25%,
while the capacitance-frequency relation is essentially unchanged. Two earlier
uncontrolled builds showed dispersions of 8.8% and 5.4% with different
per-instance patterns; they are supporting historical observations, not
controlled replicates. A linear capacitance fit trained on the earlier
32-oscillator build predicts the current build's 16 frequencies with a mean
absolute error of 0.14% and rank correlation 0.997, so the capacitive
mechanism transfers across builds even though each pattern is unique to its
routing run.
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

One caveat matters for interpretation: the two arms are not identical apart
from internal-layout matching. Hardening inserts input and output delay
buffers at the Arm B macro boundary that Arm A does not have, the sixteen
Arm B macros occupy a regular block on one side of the tile while Arm A fills
the rest, and the two arms differ in local decap and power-delivery geometry.
The comparison is therefore a matched hardened-macro implementation against
a conventional automated standard-cell implementation, not two circuits that
differ only in internal routing; the ring loops themselves stay logically
equivalent. The main results below come from a coherent build of the current
RTL that passes the physical checks (Magic and KLayout DRC, XOR, LVS, antenna,
detailed route, power grid) with zero violations; two earlier builds, an
archived dual-arm snapshot and a 32-oscillator layout, are reported for
contrast (see SIGNOFF.md in the repository).

## 4. Method

The analysis is four separate operations, each traceable to a checked-in
file. First, the physical flow produces the gate-level netlist, DEF, and
nominal-corner SPEF. Second, a structural verifier
(`verify_ring_topology.py`) parses the final netlist and confirms that every
Arm A oscillator kept exactly one enable NAND, 30 inverters, and one tap
buffer, with no cell inserted into the loop; the deck generation is only valid
if this holds. Third, the generator reconstructs that verified topology from
nominal SKY130 transistor-level cell models and attaches each ring net's SPEF
`*D_NET` total capacitance to the matching node as a grounded lumped
capacitor. It does not simulate the extracted network itself. Fourth, ngspice
transient simulation (1.8 V, 27 C, nominal TT models) measures each
oscillator's frequency, with a parallel control deck carrying no extracted
capacitance. The SPEF declares `PIN_CAP NONE`, so pin capacitance is not part
of the transferred load.

On the chip, one oscillator runs at a time. The combined simulation deck
enables all 16 reconstructed oscillators concurrently, which is equivalent
under this model because they share only an ideal supply and the reduced model
carries no coupling between them. Distributed wire resistance is omitted
entirely; its effect is not quantified here and is one reason the
distributed-RC comparison is required. Each oscillator starts disabled and is released
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
are descriptive statistics for that layout. Standard deviations are
population values across those instances, which are the complete set for a
layout, not a sample from a wider population. The extracted capacitance is also
the only spread-producing input to the model, so a strong frequency-capacitance correlation is expected almost by construction. The coefficient
confirms the model behaves; the spread it produces, and the slope, are the
physically interesting parts.

## 5. Automatically placed arrays

### 5.1 Earlier 32-oscillator layout

The earlier build placed all 32 oscillators automatically. In the
no-parasitic control every deck produced the same nominal frequency,
approximately 633.640 MHz, which checks the generator itself. With extracted
capacitance the mean was 567.6 MHz with a population standard deviation of
10.8 MHz (1.90%).
Frequencies ranged from about 539 to 589 MHz, a 50.2 MHz or 8.8%
peak-to-peak spread.

Extracted ring capacitance ranged from 7.4 to 17.8 fF. Frequency and
capacitance had Pearson *r* = -0.997 with a fitted slope of about
-4.93 MHz/fF (Figure 2a). Correlations with placement coordinates were much
weaker (|*r*| < 0.27; Figure 2b). For this layout the spread behaves like an
instance-specific routing load, not a smooth die-wide gradient.

![Figure 2. Nominal post-layout results for the earlier 32-oscillator layout: frequency versus extracted ring capacitance with the no-parasitic control, and a spatial frequency map.](../sim/spice/gono/ro_gono.png)

### 5.2 Coherent dual-arm build

Arm A of the coherent dual-arm build contains 16 automatically placed
oscillators. Their nominal post-layout frequencies have a mean of 551.7 MHz
and a 58.0 MHz peak-to-peak range, 10.5% of the mean, with *r* = -0.999
against extracted ring capacitance (Figure 4). RO15 carries an unusually
heavy routing load, 24.35 fF where the other fifteen span 11.7 to 16.95 fF,
and sits at 508.5 MHz. Because peak-to-peak is outlier-sensitive, a
leave-one-out check matters: without RO15 the spread is 4.60% peak to peak
and the SD 1.25%, while the capacitance-frequency relation barely moves
(*r* = -0.9987, rank correlation -0.996). The outlier is a real product of
the router, not a measurement fault, so it stays in the primary result; the
sensitivity numbers show exactly how much of the extreme range it carries
(`sensitivity.py` recomputes all of this from the raw logs). This build
passes Magic DRC, KLayout DRC, XOR, LVS, antenna, and power grid with zero
violations, so the dispersion estimate and the candidate GDS come from the
same run.

The three builds do not share a frequency pattern or a spread: 10.5% here,
5.4% in an earlier archived dual-arm snapshot, 8.8% in the 32-oscillator
build. These are historical observations consistent with run-specific routing
assignments; they are not controlled replicates, since the builds differ in
source revision and settings as well as seed. The planned multi-seed study
addresses that properly. A stronger cross-build check than comparing spread
numbers is per-instance prediction: a linear capacitance fit trained only on
the 32-oscillator build (624.6 MHz - 4.93 MHz/fF) predicts this build's 16
frequencies with MAE 0.77 MHz (0.14% of the mean), RMSE 1.18 MHz, and rank
correlation 0.997, with the largest error on the outlier RO15 (-0.80%). The
capacitive mechanism transfers between independent routing runs even though
each pattern is unique.

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
through device mismatch, top-level routing, supply, and temperature. The
simulation establishes only the internal-layout contribution under nominal
device parameters. Total Arm B dispersion requires per-instance integration
parasitics and fabricated-device measurements, and whether Arm B ends up with
a smaller total spread than Arm A is the measurement the chip exists to make.

![Figure 3. The earlier 32-oscillator array beside the matched-macro reference line at 569.5 MHz.](../sim/spice/gono/armB_prediction.png)

![Figure 4. Arm A of the coherent dual-arm build (10.5% peak to peak) beside the matched-macro reference line.](../sim/spice/gono/dualarm_gono.png)

## 7. Planned silicon test

Why could a repeatable mask-defined pattern matter to a PUF at all? A layout
component shared across dies can reduce uniqueness or make some comparisons
predictable, but prior work also shows systematic structure is not
automatically exploitable: Wilde, Hiller, and Pehl found adjacent-oscillator
comparisons suppressed the spatial structure in their data and their
predictor could not beat its baseline [4]. Which way this design falls is a
question for fabricated dies, not for the nominal model. A toy population
model and a first-order mismatch-scale estimate live in the repository's
supplementary material (`sim/montecarlo.py`, `sim/spice/mc/`); their outputs
depend on assumed amplitudes and a sqrt(31) scaling that the PDK's global
mismatch draw does not really support, so no number from them appears here.

The question for silicon is whether Arm A retains more of its nominal
layout pattern across dies than Arm B. The threat model I have in mind is
concrete: an attacker knows the public design and mask and holds measurements
from other dies of the same design, but none from the target die, and asks
whether the shared deterministic layout component lets them predict the target
die's pair ordering above the relevant per-bit baseline. Predictor accuracy is
then judged against that baseline with whole chips held out, not against 50%. Testing it needs multiple chip IDs, repeated
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
model, and running it on the fresh build is the obvious next check. The three
builds reported here are not a controlled replicate set; they differ in source
revision and tool settings as well as seed, so I do not aggregate their spreads
into one distribution. A planned multi-seed study that varies only the
place-and-route seed from one frozen source, config, and toolchain will give a
proper spread distribution at essentially no cost next to fabrication. Instances
within a single layout are also related observations, so instance-level
confidence intervals would overstate the evidence. The Arm B reference is
one simulation of one macro and cannot quantify fabricated Arm B variation.
The 40-run global Monte Carlo cannot reproduce independent local device
mismatch. Voltage, temperature, supply noise, ageing, package, and
measurement-system effects are uncharacterized until chips exist, and
uniqueness, reliability, min-entropy, and attack success all need a
multi-chip data set with a stated threat model. The ripple counter is
clocked by the oscillator itself, and its behaviour at the fastest corner is
checked only in behavioural simulation; the standard-cell flop at the
oscillator-to-counter boundary still needs extracted, across-corner timing
before the fast end of the range can be trusted. None of this erases the
modelled dispersion; it bounds what can be concluded from it.

## 9. Conclusion

Under a reduced lumped-capacitance model of the verified post-route
topology, automated physical implementation gave the 16 oscillators of the
coherent current build a 10.5% peak-to-peak nominal frequency dispersion
(4.6% without the single heavy-routing outlier; SD 2.36% and 1.25%
respectively). Two earlier uncontrolled builds showed 8.8% and 5.4% with
different per-instance patterns, and a capacitance fit trained on one build
predicts another's frequencies to 0.14% mean absolute error. A hardened
macro provides a 569.5 MHz shared-internal-layout reference for Arm B. What
this establishes is that the automated flow assigned substantially different
routing capacitance to logically identical oscillators, and that under
nominal device assumptions this predicts a frequency dispersion much larger
than zero, with a mechanism that transfers across routing runs.

Uniqueness, reliability, min-entropy, and attack success are not evaluated
pre-silicon. Whether the mask-defined pattern survives fabrication, and how
it compares against real device mismatch, will be settled by measuring both
arms of the fabricated chips under the protocol in the firmware.

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
