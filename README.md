# SILICON: an open ring-oscillator PUF on sky130

A ring-oscillator Physically Unclonable Function (RO-PUF) for the open-source
SkyWater 130 nm process. The project asks one question: does a fully automated
open-source ASIC layout flow inject systematic bias that destroys the
inter-chip uniqueness an RO-PUF depends on? The answer so far is yes, by a
lot, and the repo also contains the fix.

## Status

Pre-silicon work is done. The main results:

- Extracted-parasitic SPICE on the routed design shows the automated flow
  spreads 32 identical oscillators by 8.8% peak-to-peak, and per-oscillator
  routing capacitance explains it at r = -0.997. The pattern is mask-fixed, so
  every die would carry the same one. Fake entropy.
- The fix is a hardened oscillator macro, step-and-repeated 16 times.
  Bit-identical copies mean identical parasitics, so the layout spread is zero
  by construction. The matched oscillator simulates at 569.5 MHz, within 0.4%
  of the auto-placed arm's mean.
- The full two-arm chip (auto-placed arm, matched arm, shared serial
  measurement core) builds green through LibreLane on a TinyTapeout 2x2 tile:
  DRC, LVS, antenna and power-grid connectivity all clean.

Target shuttle: TTSKY26c. Real-silicon measurements come after fabrication.

The paper draft with all numbers lives in `docs/paper_draft.md`. The results
writeup is `docs/gono_results_writeup.md`. Every number can be re-derived from
raw files with `sim/spice/gono/verify.py` and `verify_macro.py`.

## Repository layout

    rtl/      synthesisable RTL and the simulation-only oscillator model
    tb/       self-checking testbenches
    sim/      reference models, SPICE decks, analysis (sim/spice/gono/)
    macro/    the hardened oscillator macro (GDS/LEF + final views)
    array/    16-copy matched array builds and PDN debug artifacts
    dualarm/  the dual-arm TinyTapeout integration kit
    docs/     paper draft, results writeup, related work, build plans

## Simulation

Requires Icarus Verilog (and GTKWave to view waveforms).

    make          # compile and run the testbench
    make waves    # run, then open the waveform
    make clean    # remove build artifacts

Without `make`:

    iverilog -g2012 -o sim_out rtl/ro_behavioural.v rtl/ro_puf_core.v tb/tb_ro_puf_core.v
    vvp sim_out

Expected output: one count per oscillator, decreasing with index, ending in
`RESULT: PASS`.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
