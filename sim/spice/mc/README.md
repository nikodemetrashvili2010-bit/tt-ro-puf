# Monte Carlo mismatch study (the real entropy)

The first version of this run taught me something worth keeping: sky130's
mismatch parameters are global .param statements, so ngspice draws ONE value
per run shared by every transistor of a model. My first 16-oscillator deck gave
16 identical frequencies per virtual chip (within-chip sigma exactly 0.000),
and an extreme process draw crashed the loop at run 17 of 30. Both symptoms
are explained and fixed in the current version, and the global-draw fact is confirmed against
the PDK source (the __mismatch.corner.spice files).

## How it works

One matched oscillator (the macro's own layout parasitics), mismatch switch
on, process switch off. Each of the 40 runs shifts all 31 in-loop nfets
together and all 31 pfets together. Variances add for independent devices,
so the true per-ring mismatch sigma is the measured run-to-run sigma divided
by sqrt(31). The analyzer applies that, then builds 1000 virtual chips from
the derived sigma and reports key uniqueness and the fake-to-real ratio
against Arm A's measured layout spread.

## Run it (2-4 minutes)

    cd sim/spice/mc
    ngspice -b mc_matched.spice -o mc_out.txt
    python3 analyze_mc.py mc_out.txt

## Assumptions to state in the paper

- Equal per-stage sensitivities (the ring is 31 near-identical stages), so
  the sqrt(31) scaling is a first-order estimate for the in-loop devices.
- The nand gate counts as one stage of each class; its internal series and
  parallel pairs bend this slightly. Second-order, and stated as such.
- MC_PR_SWITCH stays 0: global process shifts move a whole chip's
  oscillators together and cancel out of pairwise PUF comparisons.

## Knobs

MC_RUNS (40) and SEED (42) at the top of gen_mc_deck.py; regenerate with
`python3 gen_mc_deck.py`. Reproducible for a given seed.
