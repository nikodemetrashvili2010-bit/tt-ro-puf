# SILICON: deterministic layout bias in a ring-oscillator PUF

A ring-oscillator PUF is supposed to get its secret from manufacturing
randomness. This repository asks how much frequency variation the automated
open-source layout flow adds on its own, before a single chip is made. The
design is a TinyTapeout 2x2 tile in the SkyWater 130 nm process, and
everything here is pre-silicon: routed layouts, extracted parasitics, and
nominal SPICE.

I am a self-taught student and built the project with open tools on a home
PC. The raw logs, the analysis code, and scripts that recompute every headline
number from those logs are all in the repo.

## The experiment

![chip block diagram](docs/figures/chip_block.png)

Both arms hold the same 31-stage oscillator circuit. Arm A lets the flow
place and route each of its 16 oscillators separately. Arm B places 16 copies
of one hardened macro on a regular grid, so every instance has the same
internal layout. If Arm A carries a frequency pattern that repeats from chip
to chip and Arm B does not, the automated flow is building a shared bias into
a circuit whose whole job is to be unpredictable.

## What the post-layout model predicts

The current design has a coherent build: one flow run from the current RTL
that passes Magic DRC, KLayout DRC, XOR, LVS, antenna, and power grid with
zero violations, and whose extracted parasitics drive the go/no-go below. In
that build Arm A spreads 10.5% peak to peak in nominal post-layout simulation.
Two earlier builds show the same effect at different sizes: an archived
dual-arm snapshot at 5.4% and a 32-oscillator layout at 8.8%. The three builds
produced different frequency patterns, which fits placement and routing
setting the bias run by run rather than the circuit carrying one fixed
signature.

The model takes each ring net's extracted capacitance from the SPEF and puts
it back into the SPICE deck as a load, so the tight frequency-versus-capacitance fit (r near -0.999) is mostly the model doing what a
capacitance-loaded oscillator has to do. The point is not the coefficient. It
is that the spread is large and is driven by routing capacitance that the mask
freezes in place. Usefully, the earliest build's capacitance fit predicts the
coherent build's mean to 0.04%, so the mechanism carries across builds even
though the pattern does not.

The hardened macro simulates at 569.5 MHz. Its 16 Arm B copies are the same
GDS, so the matched arm removes internal-layout variation by construction.
That is why the figure draws Arm B as one reference line, not sixteen points.
It does not yet show that Arm B's total spread on real chips is lower than
Arm A's: top-level routing, supply, temperature, and device mismatch still act
on each copy, and only silicon can settle that:

![post-layout prediction for both arms](sim/spice/gono/dualarm_gono.png)

These are nominal simulations of specific routed layouts. Whether the pattern
survives on fabricated dies, and how it compares with real device mismatch,
is exactly what the chip is built to measure. [SIGNOFF.md](SIGNOFF.md) lists
what each build shows and where the gaps are.

A render of the dual-arm layout: the matched 4x4 macro grid on the left, the
auto-placed standard-cell sea on the right.

![chip render](dualarm/build_debug/gds_render.png)

## Status

The current two-arm design has a clean coherent build from its own RTL (all
sign-off checks zero; see [SIGNOFF.md](SIGNOFF.md)) and is ready for the
TTSKY26c shuttle. After fabrication the plan is to measure both arms across
chips, voltage, and temperature with the scripts in `firmware/`. What I expect
on silicon: Arm A shows more cross-chip pattern correlation than Arm B. The
data can also prove me wrong.

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
