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
tracks their extracted ring capacitance: 8.8% peak-to-peak in an earlier
32-oscillator build and 5.4% in Arm A of the archived dual-arm layout. Arm B
reuses one hardened oscillator GDS sixteen times, and its single extracted
simulation, 569.5 MHz, appears in the comparison figures as a reference line
for that shared internal layout. And extraction followed by nominal SPICE is
a practical pre-fabrication check for deterministic layout sensitivity.

Cross-die repeatability, uniqueness, attack success, and entropy are
predictions I will test on the fabricated chips. The matched-layout principle
itself is not new; the intended contribution is an open ASIC case study and a
pre-silicon diagnostic that others can rerun.

## References

[1] G. E. Suh and S. Devadas, “Physical Unclonable Functions for Device
Authentication and Secret Key Generation,” *Proceedings of the 44th Design
Automation Conference (DAC)*, pp. 9–14, 2007.
https://doi.org/10.1145/1278480.1278484

[2] A. Maiti and P. Schaumont, “Improved Ring Oscillator PUF: An FPGA-friendly
Secure Primitive,” *Journal of Cryptology*, vol. 24, no. 2, pp. 375–397,
2011. https://doi.org/10.1007/s00145-010-9088-4

[3] A. Maiti, J. Casarona, L. McHale, and P. Schaumont, “A Large Scale
Characterization of RO-PUF,” *IEEE International Symposium on
Hardware-Oriented Security and Trust (HOST)*, pp. 66–71, 2010.
https://schaumont.dyn.wpi.edu/schaum/pdf/papers/2010hostm.pdf

[4] F. Wilde, M. Hiller, and M. Pehl, “Statistic-Based Security Analysis of
Ring Oscillator PUFs,” *2014 International Symposium on Integrated Circuits
(ISIC)*, pp. 148–151, 2014.
https://doi.org/10.1109/ISICIR.2014.7029528

[5] A. S. Chauhan, V. Sahula, and A. S. Mandal, “Novel Randomized Placement
for FPGA Based Robust ROPUF with Improved Uniqueness,” *Journal of Electronic
Testing*, vol. 35, no. 5, pp. 581–601, 2019.
https://doi.org/10.1007/s10836-019-05829-5

[6] K. A. Asha, L. E. Hsu, A. Patyal, and H.-M. Chen, “Improving the Quality
of FPGA RO-PUF by Principal Component Analysis (PCA),” *ACM Journal on
Emerging Technologies in Computing Systems*, vol. 17, no. 3, article 34,
2021. https://doi.org/10.1145/3442444

[7] W.-C. Wang, Z. Li, J. Skudlarek, M. Larouche, M. Chen, and P. Gupta,
“UNBIAS PUF: A Physical Implementation Bias Agnostic Strong PUF,”
arXiv:1703.10725, 2017. https://arxiv.org/abs/1703.10725

[8] J. Miskelly, C. Gu, Q. Ma, Y. Cui, W. Liu, and M. O’Neill, “Modelling
Attack Analysis of Configurable Ring Oscillator (CRO) PUF Designs,” *2018
IEEE 23rd International Conference on Digital Signal Processing (DSP)*,
pp. 1–5, 2018. https://doi.org/10.1109/ICDSP.2018.8631638

[9] M. Shalan and T. Edwards, “Building OpenLANE: A 130nm OpenROAD-based
Tapeout-Proven Flow,” *2020 IEEE/ACM International Conference on Computer
Aided Design (ICCAD)*, article 110, pp. 1–6, 2020.
https://doi.org/10.1145/3400302.3415735

[10] SkyWater Technology and Google, “SkyWater Open Source PDK (SKY130).”
https://github.com/google/skywater-pdk

[11] litneet64, “RO-based Physically Unclonable Function in sky130
(TinyTapeout tt07).” https://github.com/litneet64/tt07-RO-based-PUF

[12] S. Katzenbeisser, U. Kocabas, V. Rožić, A.-R. Sadeghi, I. Verbauwhede,
and C. Wachsmann, “PUFs: Myth, Fact or Busted? A Security Evaluation of
Physically Unclonable Functions (PUFs) Cast in Silicon,” *Cryptographic
Hardware and Embedded Systems (CHES 2012)*, LNCS 7428, pp. 283–301, 2012.
https://doi.org/10.1007/978-3-642-33027-8_17
