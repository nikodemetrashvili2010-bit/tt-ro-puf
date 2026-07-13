# Related work and where this project fits

Bibliography and positioning for the SILICON project.

## 1. Where RO-PUFs come from

Suh and Devadas introduced the ring-oscillator PUF. It compares the
frequencies of nominally identical ring oscillators and turns each pairwise
comparison into a response bit [1]. The security rests on one assumption: the
frequency differences between identical ROs come from random process
variation, so one chip's responses tell an attacker nothing about another's.
Everything in this project turns on whether that assumption survives an
automated layout flow.

## 2. The known weakness

People have known for over a decade that process variation is not purely
random. Maiti and Schaumont showed that systematic variation degrades RO-PUF
uniqueness, because a deterministic component shared across a die acts like a
fixed bias added to every comparison. Their configurable-RO compensation
recovers up to about 18% of uniqueness [2]. Their large-scale RO-PUF
characterization measured inter- and intra-die Hamming distance across many
devices and made the spatial structure of the variation visible [3]. Later
work treats strong spatial correlation as an outright security threat, since
an adversary who learns the shared pattern can predict across chips [4]. That
is exactly the failure mode this project targets. The difference is the
source: here the shared component is injected by the layout tool, not the
wafer.

## 3. How FPGAs fixed it

On FPGAs the big avoidable bias source is asymmetric routing and non-identical
logic resources, and the community's answer was to take placement and routing
out of the tool's hands. Hard macros that replicate one matched RO layout,
controlled placement, and randomized-but-fixed placement all raise uniqueness
substantially. Uncontrolled placement does worst; matched or controlled
placement does best [2, 5]. Other papers attack the same bias statistically
instead of physically: principal-component removal of the systematic part [6],
bias-agnostic strong PUF constructions [7], and configurable ROs whose
modeling resistance has been studied directly [8]. The recurring lesson is
that making the instances physically identical is the clean structural fix.
The recurring limitation is that nearly all of this lives on FPGAs, where
"matched layout" means a hard macro over a fixed fabric.

## 4. Open ASIC flows change the picture

Open PDKs and automated RTL-to-GDSII flows made custom silicon accessible. The
SkyWater sky130 open PDK [10] and the OpenLANE/OpenROAD flow [9] underpin
low-cost multi-project shuttles like TinyTapeout and Efabless ChipIgnite,
which is how a solo or student designer can tape out a chip at all. Someone
has already implemented an RO-PUF on sky130 through TinyTapeout [11], but as a
working CRP implementation offered for community characterization. It did not
ask whether the automated flow itself compromises the entropy.

## 5. The gap

Two things look underexplored here. First, the matched-layout fix is
established for FPGAs, but I have not found it demonstrated, with numbers,
on the automated open-source ASIC place-and-route flow, where the bias
mechanism is routing parasitics on a standard-cell fabric rather than LUTs
and switch boxes. Second, I am not aware of a lightweight pre-fabrication
test that tells a shuttle user, before they spend a fabrication slot they
only get once, whether their automatically laid-out PUF will ship a shared,
deterministic layout bias.

This project covers both, with open tools only:

1. The injected bias, quantified. From the routed array I take OpenROAD's own
   extracted parasitics (SPEF) and show in SPICE that the automated flow gives
   32 logically identical oscillators an 8.8% peak-to-peak frequency spread,
   almost entirely explained by per-oscillator routing capacitance (Pearson
   r = -0.997). Transistors are held nominal, so this isolates the layout
   contribution cleanly, and the spread is fixed by the mask, so every die
   gets the same one.

2. A structural fix inside the same flow. I harden one oscillator into a fixed
   macro and step-and-repeat bit-identical copies. Inter-oscillator parasitic
   spread goes to zero by construction. This carries the FPGA matched-layout
   idea onto the open ASIC flow.

3. A pre-silicon go/no-go: the extraction-plus-SPICE procedure is a
   reproducible test any shuttle user can run before committing to fab.

The matched-layout principle is not new and I do not claim it is. The
contribution is demonstrating it on the open ASIC flow, tying the bias
causally to extracted parasitics, and packaging the whole thing as a test you
run before paying for silicon.

## References

[1] G. E. Suh and S. Devadas, "Physical Unclonable Functions for Device
Authentication and Secret Key Generation," Proc. 44th Design Automation Conf.
(DAC), 2007, pp. 9-14. https://people.csail.mit.edu/devadas/pubs/puf-dac07.pdf

[2] A. Maiti and P. Schaumont, "Improved Ring Oscillator PUF: An FPGA-friendly
Secure Primitive," Journal of Cryptology, vol. 24, pp. 375-397, 2011.
https://link.springer.com/article/10.1007/s00145-010-9088-4

[3] A. Maiti, J. Casarona, L. McHale, and P. Schaumont, "A Large Scale
Characterization of RO-PUF," IEEE Int. Symp. Hardware-Oriented Security and
Trust (HOST), 2010.

[4] F. Wilde, M. Hiller, and M. Pehl, "Statistic-Based Security Analysis of
Ring Oscillator PUFs," Int. Symp. on Integrated Circuits (ISIC), 2014,
doi:10.1109/ISICIR.2014.7029528; also arXiv:1910.07068 (2019 re-posting). https://arxiv.org/abs/1910.07068

[5] A. S. Chauhan, V. Sahula, and A. S. Mandal, "Novel Randomized Placement
for FPGA Based Robust ROPUF with Improved Uniqueness," Journal of Electronic
Testing, vol. 35, pp. 581-601, 2019; arXiv:2006.09290.
https://link.springer.com/article/10.1007/s10836-019-05829-5

[6] K. A. Asha, L. E. Hsu, A. Patyal, and H.-M. Chen, "Improving the Quality
of FPGA RO-PUF by Principal Component Analysis (PCA)," ACM Journal on
Emerging Technologies in Computing Systems, 2021. doi:10.1145/3442444

[7] W.-C. Wang, Z. Li, J. Skudlarek, M. Larouche, M. Chen, and P. Gupta,
"UNBIAS PUF: A Physical Implementation Bias Agnostic Strong PUF,"
arXiv:1703.10725, 2017.

[8] J. Miskelly, C. Gu, Q. Ma, Y. Cui, W. Liu, and M. O'Neill, "Modelling
Attack Analysis of Configurable Ring Oscillator (CRO) PUF Designs," IEEE
Int. Conf. on Digital Signal Processing (DSP), 2018.
https://ieeexplore.ieee.org/document/8631638

[9] M. Shalan and T. Edwards, "Building OpenLANE: A 130nm OpenROAD-based
Tapeout-Proven Flow," IEEE/ACM Int. Conf. on Computer Aided Design (ICCAD),
2020. doi:10.1145/3400302.3415735 (note: the related WOSET 2020 paper
"OpenLANE: The Open-Source Digital ASIC Implementation Flow" is by A. Ghazy
and M. Shalan)

[10] SkyWater Technology and Google, "SkyWater Open Source PDK (sky130)."
https://github.com/google/skywater-pdk

[11] litneet64, "RO-based Physically Unclonable Function in sky130 (TinyTapeout
tt07)." https://github.com/litneet64/tt07-RO-based-PUF
