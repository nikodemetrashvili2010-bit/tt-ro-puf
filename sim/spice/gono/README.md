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
`compensated_bits.py` runs the two together: it removes each ring's predicted
layout term with the leave-one-out corrector and re-reads the bits from the
residuals, which is what the RO-PUF literature's compensation would amount to
here. The short answer is that entropy rises from 0.46 bits of 8 to 2.91 and a
reader of the same public files still calls 7.19 of the 8, so the correction
returns variation without returning secrecy.
`verify_predictability.py` re-derives all three of those results from the SPEF
and the two frequency tables with its own parser and its own least-squares
solver, hardcodes the figures that appear in the paper, and ends on a scrambled
control so that a check which cannot fail does not sit in the suite pretending
to pass. `numerical_audit.py` goes after the calculation rather than the inputs:
it refits everything with Householder QR instead of the normal equations,
redraws the frequencies inside their stored precision, bounds the simulator's
own numerical floor from the lumped decks, charges the estimate for having
picked the best of six correctors, Holm-corrects the declared family of
correlations, and resamples the eight pairs. Nothing there moves a conclusion,
but the last of them is why the entropy totals are quoted as intervals: the
sample of eight pairs is a wider uncertainty than the mismatch assumption.
Figures come from `make_figures.py`, `make_dualarm_figure.py`,
`make_bits_figure.py` and `make_compensated_figure.py`, and the last two import
the analysis scripts rather than repeating their arithmetic.

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
the width where a pulse stops surviving gets located, and `--corner` moves the
PVT point. The span has to cover a whole ring period or the enable fall never
crosses an edge and the sweep passes without testing anything, which is what the
first slow-corner run did: the 38-step default spans 1.9 ns and the ss period is
3439 ps, so ss needs `--steps 76`. The analyzer rejects a sweep whose count never
changes for exactly that reason. Seven `boundary_validation_*.csv` files are the
records: B15, A05 and B00 at the fast corner, fine 5 ps sweeps around the B15 and
B00 thresholds, and B15 again at tt and at ss.

`check_pulse_width.py` reads what the PDK promises rather than what the simulator
shows. It pulls the minimum clock pulse width for `sky130_fd_sc_hd__dfrtp_2` out
of the Liberty files, handling both spellings vendors use for it, and compares
the narrowest clock the sweeps actually delivered against the corner they ran at.
It names that corner file explicitly and refuses to fall back on a near
neighbour, since the first version matched on the substring "ff", picked a corner
nothing had run at, and reported a failure that was not real.

`gen_instance_decks.py` and `analyze_instance.py` ask whether Arm B's sixteen
instances behave as one number once they are integrated. All sixteen share one
GDS, so the deck gives all sixteen the identical internal macro model and hangs
each instance's own external parasitics on it: the real enable driver, the enable
route, the output route and the selector cell that route ends at, both routes
distributed from the top SPEF. A control with no capacitance and a reference with
the macro's extraction only run in the same file. Structural guards refuse to
write a deck if a cell is missing from the PDK, if a route's capacitance does not
match the SPEF net total, if a node carries capacitance without a resistor, or if
an output net reaches no known selector cell. `verify_instance.py` re-derives the
published numbers from the raw log with its own SPEF parser, netlist parser and
correlation code. Records are `armb_instances_out.txt` and
`instance_parasitics.csv`.

`gen_supply_decks.py` and `analyze_supply.py` bound the supply confound, which is
that Arm B sits on its own met4 straps and decap while Arm A sits on ordinary
met1 rails. Rather than assume one path resistance, the sweep puts a series
resistor in front of each ring across four decades and measures the current, the
supply that arrives at the cells and the frequency at every point, so the verdict
survives the geometry being wrong by a factor of ten. The rings are not new code,
they come from the item 7 and item 8 generators. Two independent things have to
close before the result is read: Ohm's law at every point, and the pushing figure
the sweep implies against the one measured separately by moving an ideal supply.
Worth knowing if you write a deck like this yourself: a `.save` line makes ngspice
keep only the vectors it names, so a current measurement against `vdd#branch`
silently returns nothing useful unless `i(Vdd)` is on that line. The sixteen raw logs are in
`supply/`, so `python3 analyze_supply.py --dir supply` reproduces the verdict
from a clone without ngspice.

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
