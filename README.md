# SILICON: deterministic layout bias in a ring-oscillator PUF

A ring-oscillator PUF is supposed to get its secret from manufacturing
randomness. This repository asks how much frequency variation the automated
open-source layout flow adds on its own, before a single chip is made. The
design is a TinyTapeout 2x2 tile in the SkyWater 130 nm process, and
everything here is pre-silicon: routed layouts, extracted parasitics, and
nominal SPICE.

I am a self-taught student and built the project with open tools on a home
PC. The raw logs, analysis code, and a verification script for every headline
number are checked in.

## The experiment

![chip block diagram](docs/figures/chip_block.png)

Both arms hold the same 31-stage oscillator circuit. Arm A lets the flow
place and route each of its 16 oscillators separately. Arm B places 16 copies
of one hardened macro on a regular grid, so every instance has the same
internal layout. If Arm A carries a frequency pattern that repeats from chip
to chip and Arm B does not, the automated flow is building a shared bias into
a circuit whose whole job is to be unpredictable.

## What the post-layout model predicts

In the archived dual-arm build, Arm A's oscillators spread 5.4% peak to peak
in nominal post-layout simulation, and frequency follows extracted ring
capacitance with Pearson r = -0.999. An earlier 32-oscillator build spread
8.8% with r = -0.997 and a different pattern, so each flow run freezes its
own pattern into the mask. The hardened macro simulates at 569.5 MHz with its
extracted internal parasitics. Its 16 Arm B copies share one internal layout,
which is why the figure draws Arm B as a single reference line rather than
sixteen separate points:

![post-layout prediction for both arms](sim/spice/gono/dualarm_gono.png)

These are nominal simulations of specific routed layouts. Whether the pattern
survives on fabricated dies, and how it compares with real device mismatch,
is exactly what the chip is built to measure. [SIGNOFF.md](SIGNOFF.md) lists
what each archived artifact shows and where the gaps are.

An archived render of the dual-arm layout: the matched 4x4 macro grid on the
left, the auto-placed standard-cell sea on the right. A fresh build will
replace it before submission.

![chip render](dualarm/build_debug/gds_render.png)

## Status

The measurement core was improved after the archived build, so the current
source needs one fresh flow run, with KLayout DRC and XOR enabled, before the
shuttle order. Target: TTSKY26c. After fabrication the plan is to measure
both arms across chips, voltage, and temperature with the scripts in
`firmware/`. The registered prediction: Arm A shows cross-chip pattern
correlation, Arm B much less. The data can also prove me wrong.

Operating notes for the chip itself are in [docs/info.md](docs/info.md). The
paper source is [docs/paper_draft.md](docs/paper_draft.md); build it with
`sh docs/build_paper.sh`. Simulation details live in
[docs/gono_results_writeup.md](docs/gono_results_writeup.md).

## Repository layout

    src/      TinyTapeout project sources (RTL, macro views, config)
    test/     TinyTapeout cocotb tests
    rtl/      original RTL and simulation-only oscillator model
    tb/       self-checking Verilog testbenches
    sim/      architectural models, SPICE decks, logs, and analysis
    macro/    hardened oscillator macro and final views
    array/    standalone 16-copy macro-array builds and PDN debug artifacts
    dualarm/  current integration kit plus an older diagnostic build snapshot
    firmware/ measurement and analysis scripts for fabricated devices
    docs/     paper source, methods notes, related work, and figures

## Reproducing the results

`make` runs the RTL testbenches (Icarus Verilog needed). Every headline
number re-derives from the checked-in raw logs with the verify scripts, and
the SPICE runs can be repeated against a local sky130A PDK. Exact commands,
environment variables, and what a rerun does and does not prove are in
[REPRODUCIBILITY.md](REPRODUCIBILITY.md).

## Citation and license

Citation metadata is in [CITATION.cff](CITATION.cff). Apache License 2.0;
see [LICENSE](LICENSE).
