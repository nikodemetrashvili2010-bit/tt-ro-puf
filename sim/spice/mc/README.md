# Monte Carlo mismatch-sensitivity study

This is a first-order model study, not a silicon entropy characterization.
The first version of this run taught me a fact I did not expect: sky130's
mismatch parameters are global .param statements, so ngspice draws ONE value
per run shared by every transistor of a model. My first 16-oscillator deck gave
16 identical frequencies per virtual chip (within-chip sigma exactly 0.000),
and an extreme process draw crashed the loop at run 17 of 30. Both symptoms
are explained in the current version, and the global-draw fact was checked
against the PDK source (`__mismatch.corner.spice`).

## How it works

One matched oscillator (the macro's own layout parasitics), mismatch switch
on, process switch off. Each of the 40 runs shifts all 31 in-loop nfets
together and all 31 pfets together. Variances add for independent devices,
so a first-order per-ring mismatch estimate is the simulated run-to-run sigma
divided by sqrt(31) under an equal-sensitivity/independent-device
approximation. The analyzer applies that approximation, reports an approximate
95% sampling interval for sigma, then builds seeded virtual chips as a code and
model sanity check. The virtual-chip uniqueness tends to 50% by construction
for symmetric IID draws; it is not empirical PUF validation.

The archived log contains only 40 common-draw runs. The uncertainty interval
addresses finite-run sampling of the standard deviation, not model-form error.
It excludes unequal device sensitivities, NAND topology details, spatially
correlated mismatch, coupling/distributed RC, PVT, aging, voltage noise, bit
reliability, helper-data effects, and attacks. Those require transistor-level
per-device sampling and ultimately multi-die/multi-condition measurements.

## Run it (2-4 minutes)

    cd sim/spice/mc
    # PDK_ROOT must point to the directory containing sky130A
    python3 ../run_ngspice.py mc_matched.spice --log mc_out.txt
    python3 analyze_mc.py mc_out.txt

## Assumptions to state in the paper

- Equal per-stage sensitivities and independent per-device draws are assumed,
  so sqrt(31) is explicitly a first-order propagation estimate.
- The nand gate counts as one stage of each class; its internal series and
  parallel pairs bend this slightly. Second-order, and stated as such.
- `MC_PR_SWITCH` stays 0. This isolates one mismatch-sensitivity question; it
  does not establish that global or spatial process variation cancels in a
  physical array.

## Knobs

MC_RUNS (40) and SEED (42) at the top of gen_mc_deck.py; regenerate with
`python3 gen_mc_deck.py`. The ngspice seed is recorded for repeatability with
the same PDK and simulator, but exact cross-version numerical identity is not
claimed. See the repository `REPRODUCIBILITY.md` for environment requirements.
