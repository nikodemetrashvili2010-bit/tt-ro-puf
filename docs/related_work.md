# Related work and where this project fits

This note gives the bibliography and the narrower research claim behind the
SILICON project.

## 1. Ring-oscillator PUFs

Suh and Devadas introduced the ring-oscillator PUF as a circuit that compares
the frequencies of nominally identical ring oscillators [1]. A response is
useful only if it is sufficiently device-specific and stable. For this
project, the relevant question is how much of the frequency ordering is due to
random manufacturing variation and how much is a deterministic consequence of
physical implementation.

## 2. Systematic variation and placement bias

Systematic variation in RO-PUFs is well established. Maiti and Schaumont
showed that it can reduce uniqueness and reported that configurable-RO
compensation improved uniqueness by as much as about 18% in their experiments
[2]. Their larger characterization study measured reliability and uniqueness
over 125 FPGAs and examined spatial structure in oscillator frequency [3].

The security consequences require care. Wilde, Hiller, and Pehl studied
spatial frequency patterns as a possible source of prediction [4]. They also
reported important counterevidence: for adjacent-oscillator comparisons, the
measured covariance was too small for their statistical estimator to recover
the response bits. Their result does not say that spatial bias is harmless or
that it is always exploitable. It shows that the pairing rule, the strength of
the shared component, and device-specific variation all matter.

RO-PUFs have also been evaluated in fabricated ASICs. Katzenbeisser et al.
characterized five PUF types, including ring oscillators, across 96 ASICs in a
commercial 65 nm process [12]. That work evaluates finished devices rather
than isolating the contribution of an open place-and-route flow.

## 3. Mitigation work on FPGAs

Feiten and colleagues measured 38 identical Altera FPGAs and traced
non-device-specific systemic RO frequency biases to internal LUT routing, RO
location, and payload activity [19]; that is the closest FPGA analogue of the
question asked here. On the ASIC side, SCALLER showed in fabricated 65 nm
silicon that deliberate local layout effects (well proximity) deterministically
shift standard-cell RO frequencies by design [17], which is direct physical
evidence that mask-level layout detail moves RO frequency in silicon.

FPGA implementations have used matched hard macros, controlled placement,
placement selection, configurable oscillators, and statistical correction to
reduce implementation bias [2, 5, 6]. Other work proposes constructions that
are less sensitive to physical implementation bias [7] or studies modelling
attacks on configurable RO designs [8].

These results motivate a matched-layout arm, but they do not justify a claim
that matching removes all frequency variation. Reusing one macro makes its
internal geometry and extracted internal parasitics common to every instance.
Fabrication mismatch, supply distribution, temperature, stress, and other
top-level effects remain and must be measured.

## 4. Open ASIC flows

The OpenLANE/OpenROAD flow [9] and the open SkyWater SKY130 PDK [10] make it
possible to inspect placement, routing, and extracted parasitics before a
low-cost shuttle run. A previous TinyTapeout project implemented an RO-PUF in
SKY130 for community characterization [11]. The present project asks a
different, narrower question: what deterministic frequency component appears
in nominal post-layout simulation, and does a repeated hard macro reduce it?

## 5. Scope of this project

The current evidence supports three limited claims. Separately routed
standard-cell oscillators show a nominal post-layout frequency spread that
tracks their extracted ring capacitance: 5.53% peak-to-peak in Arm A of the
candidate build, and a median of 5.75% across nine builds that differ only in
placement density. Arm B reuses one hardened oscillator GDS sixteen times, and
appears in the comparison figures as a reference line at 569.5 MHz for that
shared internal layout. Two later runs stand behind that line: the macro
re-extracted from its full RC network at 566.05 MHz, and all sixteen instances
extracted individually with their own top-level routes, spreading 0.0025% peak
to peak at nominal and less at both other corners. And extraction followed by
nominal SPICE is a practical pre-fabrication check for deterministic layout
sensitivity.

Uniqueness, reliability, and entropy have standard definitions in the PUF
literature [20], and cross-die repeatability, uniqueness, and any attack are
predictions I will test on the fabricated chips rather than claims here. What I
did not find is the exact combination this project targets. Prior mitigation
work matches layout on FPGAs [2, 5, 6], large ASIC studies characterize RO-PUFs
across many dies [3, 12], and temperature-aware designs tackle RO reliability
[15]. To the best of my literature search (IEEE Xplore, arXiv, and the references
of the papers above, through July 2026), no prior work compares a controlled
open-source RTL-to-GDS array against a matched hardened macro, quantified from
the flow's own extraction before fabrication and then checked on the same
dies. Feiten et al. establish the systemic-bias phenomenon on FPGAs [19] and
SCALLER establishes deliberate layout-driven frequency control in ASIC silicon
[17]; neither quantifies what an automated open ASIC flow does to a PUF array
by accident, pre-fabrication, with the artifacts open. That gap, together with a
diagnostic anyone can rerun, is the contribution. The matched-layout principle
itself is old.

## References

Numbering follows `paper_draft.md`, which is the authoritative list. The
two diverged from [13] onwards until 2026-08-11, so a reader following a
citation out of one and into the other landed on the wrong paper. This file
was the one renumbered: the paper's numbers are embedded in its prose all
the way through and moving them was the riskier of the two edits. The gaps
below at [13], [14], [16] and [18] are references the paper carries and this
note has no need of.

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

[12] S. Katzenbeisser, U. Kocabas, V. Rožić, A.-R. Sadeghi, I. Verbauwhede,
and C. Wachsmann, "PUFs: Myth, Fact or Busted? A Security Evaluation of
Physically Unclonable Functions (PUFs) Cast in Silicon," *Cryptographic
Hardware and Embedded Systems (CHES 2012)*, LNCS 7428, pp. 283-301, 2012.
https://doi.org/10.1007/978-3-642-33027-8_17

[15] C.-E. Yin and G. Qu, "Temperature-Aware Cooperative Ring Oscillator PUF,"
*2009 IEEE International Workshop on Hardware-Oriented Security and Trust
(HOST)*, pp. 36-42, 2009. https://doi.org/10.1109/HST.2009.5225055

[17] M. J. Aljafar, Z. U. Abideen, A. Peetermans, B. Gierlichs, and
S. Pagliarini, "SCALLER: Standard Cell Assembled and Local Layout Effect-Based
Ring Oscillators," *IEEE Embedded Systems Letters*, vol. 16, no. 4,
pp. 493-496, 2024. https://arxiv.org/abs/2406.01258

[19] L. Feiten, J. Oesterle, T. Martin, M. Sauer, and B. Becker, "Systemic
Frequency Biases in Ring Oscillator PUFs on FPGAs," *IEEE Transactions on
Multi-Scale Computing Systems*, vol. 2, no. 3, pp. 174-185, 2016.
https://ieeexplore.ieee.org/document/7539304

[20] C. Herder, M.-D. Yu, F. Koushanfar, and S. Devadas, "Physical Unclonable
Functions and Applications: A Tutorial," *Proceedings of the IEEE*, vol. 102,
no. 8, pp. 1126-1141, 2014. https://doi.org/10.1109/JPROC.2014.2320516
