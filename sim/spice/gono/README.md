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
correction up against ones built from the SPEF's capacitance and resistance.
`predictable_bits.py` turns the same frequencies into the eight adjacent-pair
response bits and reports how much across-die entropy each one still carries.
`verify_predictability.py` re-derives both of those results from the SPEF and
the two frequency tables with its own parser and its own least-squares solver,
hardcodes the figures that appear in the paper, and ends on a scrambled control
so that a check which cannot fail does not sit in the suite pretending to pass.
Figures come from `make_figures.py`, `make_dualarm_figure.py` and
`make_bits_figure.py`, and the last of those imports `predictable_bits.py`
rather than repeating its arithmetic.

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
arithmetic against planted answers without needing ngspice, and `verify_noise.py`
re-derives every published figure from the twelve logs with code that imports
neither script. The four
`tprobe_*.spice` decks are a one-off check that the SKY130 corner library really
does let a temperature request through.

`gen_mux_sweep.py` and `analyze_mux_sweep.py` ask whether every oscillator's
edges actually reach the counter. One oscillator at a time is selected through a
synthesized 32-to-1 path, and that path is not a tree: the sources reach `sel_ro`
through three to five cells of six types, and eight of them go through a mux4_2.
The generator lifts the real cells of one path out of the routed netlist, loads
each intermediate net with its own SPEF total, holds the side inputs at the
levels that open that path, drives all 32 from the same extracted ring so that
any difference belongs to the path, and ends in a real dfrtp_2 wired as a toggle.
Cell pin order comes from the PDK's own subckt lines rather than from anything
written down here, and the script stops if a cell or a pin is missing. Passing
`--control` writes the same paths deliberately closed, which have to fall silent;
without that the open runs would rest on an assumption about the side inputs
rather than on evidence. The analysis matches each ring edge to the selector edge
it produced instead of comparing totals over a window, because the selector
delays every edge and a total count reports the last one as lost. Results land in
`mux_validation.csv`, one row per oscillator with its cell chain.

`gen_boundary_sweep.py` and `analyze_boundary_sweep.py` ask item 1's question
through item 2's path. The generator does not rebuild the selector, it calls
`gen_mux_sweep.build` and rewrites the enable, the transient length and the
output name, refusing to write a deck if any of them is not found exactly once.
So the selector half of every boundary deck is the same code item 2 was checked
with. `--base-ns`, `--step-ps` and `--steps` move the phase grid, which is how
the width where a pulse stops surviving gets located. Results land in
`boundary_validation_B15.csv`, `boundary_validation_A05.csv` and
`boundary_validation_B15_fine.csv`.

Both sweep analyzers take `--selftest`, which plants the faults they claim to
catch and needs neither the PDK nor ngspice. It is worth running before a long
simulation rather than after. `analyze_mux_sweep.py` grew its checks on
2026-08-02 after a polarity mistake passed every one of the old ones: it had
been comparing the narrowest level at the tap against the narrowest at `sel_ro`
without noticing those are opposite polarities on every path.

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
