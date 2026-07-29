# Nominal extracted-parasitic go/no-go experiment

This folder holds the main result of the project. Before spending money on
silicon, I wanted to know whether the automated flow biases the oscillators,
and by how much.

The test uses a routed design against itself. It takes each net's total
capacitance from OpenROAD's nominal SPEF, places that value as a lumped
capacitor on the corresponding ring node, and simulates the oscillators in
ngspice with nominal device models. The remaining frequency spread is evidence
of layout-dependent loading in this model. It is a pre-silicon prediction, not
a measurement of fabricated devices or proof that the same ordering survives
process, voltage, temperature, aging, coupling, supply noise, or local mismatch.

The transfer deliberately omits SPEF resistance and coupling topology: only
`*D_NET` total capacitance is used. Results therefore apply to the checked-in
TT/1.8 V nominal lumped-C model. "Layout bias" below means that bounded model,
not a universal or measured silicon property.

Two decks make the argument. `ro_all_ctrl.spice` has no parasitics, so all 32
oscillators are identical and must read one frequency. It is the control and a
self-test of the generator. `ro_all_par.spice` carries the extracted
capacitance, and the spread across its 32 oscillators is the model's predicted
layout-dependent bias.

## The files

`gen_decks.py` writes the two decks from the routed build's SPEF and DEF,
which ship in `first_build/`. Archived-result verification runs from a bare
clone; deck regeneration/execution additionally needs the external SKY130 PDK.
`ctrl2.txt` and `par2.txt` are the raw ngspice frequency logs. `ro_positions.csv`
gives each oscillator its placement centroid and extracted ring capacitance.
`analyze.py` joins these and prints the verdict, and `gono_results.csv` is the
per-oscillator table it produces.

The later runs live here too. `gen_macro_deck.py` and `ro_macro_matched.spice`
predict the matched Arm B nominal internal frequency. `gen_dualarm_decks.py`
and the `dualarm_*` files model Arm A of the coherent current build; the deck
inputs and raw logs sit in `dualarm/build_current/`, and Arm B is represented
separately by the macro run. `verify_ring_topology.py` proves the final
netlist kept every Arm A ring intact before any deck is trusted, and
`sensitivity.py` recomputes the outlier leave-one-out numbers and the
cross-build per-oscillator prediction from raw files. `compensation.py` asks whether the
layout term can be predicted and taken back out, and puts a position-based
correction up against ones built from the SPEF's capacitance and resistance. Figures come from
`make_figures.py` and `make_dualarm_figure.py`.

`gen_noise_decks.py` and `analyze_noise.py` answer a separate question, which is
what a single reading can resolve at all. The decks sweep supply from 1.62 to
1.98 V, temperature from -40 to 125 C, and the four corners where the two
extremes combine, and one deck measures dV/dt at the switching threshold on
every node of three rings so that thermal noise can be turned into a period
jitter. The analysis separates the part of each shift that moves all sixteen
rings together from the part that differs between them, since only the second
kind can flip a bit, and it compares the resulting floor against the mismatch
scale and the compensation residual. It also verifies that the 1.80 V deck
reproduces the archived nominal frequencies and that every log ran at the
temperature its deck asked for. `python3 analyze_noise.py --selftest` checks the
arithmetic against planted answers without needing ngspice. The four
`tprobe_*.spice` decks are a one-off check that the SKY130 corner library really
does let a temperature request through.

## Reproducing and checking

    python3 verify.py

Set `PDK_ROOT` to the parent of the selected PDK directory (normally
`sky130A`), and optionally set `PDK` when it is not `sky130A`. The portable
runner rewrites only the two model paths in a temporary copy; checked-in decks
remain unchanged. The absolute paths retained inside historical decks are
provenance, not a required local directory layout:

    $env:PDK_ROOT = "C:\path\to\pdks"       # PowerShell example
    python ../run_ngspice.py ro_all_ctrl.spice --log ctrl2.txt
    python ../run_ngspice.py ro_all_par.spice  --log par2.txt

On POSIX shells, use `export PDK_ROOT=/path/to/pdks`. Deck generators also use
these variables, so regeneration fails clearly when the model files are absent.

`verify.py`, `verify_macro.py`, and `verify_dualarm.py` re-derive checked
quantities from raw logs without importing the analysis. They now return a
nonzero process status on any failed check, so they can gate CI. Their PASS
status verifies internal consistency of the archived logs; it does not expand
the physical scope of the simulation.
