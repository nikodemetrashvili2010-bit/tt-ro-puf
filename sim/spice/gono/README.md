# The go/no-go experiment

This folder holds the main result of the project. Before spending money on
silicon, I wanted to know whether the automated flow biases the oscillators,
and by how much.

The test uses the routed chip against itself. I take the capacitance the
OpenROAD flow extracted from my own layout (the SPEF), put it on every ring
node, and simulate all 32 oscillators in ngspice with the transistors held at
nominal. Nominal transistors carry no device randomness, so any frequency
spread that is left is pure layout. It is fixed by the mask and identical on
every die. That is what I call fake entropy.

Two decks make the argument. `ro_all_ctrl.spice` has no parasitics, so all 32
oscillators are identical and must read one frequency. It is the control and a
self-test of the generator. `ro_all_par.spice` carries the extracted
capacitance, and the spread across its 32 oscillators is the layout bias.

## The files

`gen_decks.py` writes the two decks from the routed netlist and the SPEF.
`ctrl2.txt` and `par2.txt` are the raw ngspice frequency logs. `ro_positions.csv`
gives each oscillator its placement centroid and extracted ring capacitance.
`analyze.py` joins these and prints the verdict, and `gono_results.csv` is the
per-oscillator table it produces.

The later runs live here too. `gen_macro_deck.py` and `ro_macro_matched.spice`
measure the matched Arm B frequency. `gen_dualarm_decks.py` and the `dualarm_*`
files extract both arms from the one submitted chip. Figures come from
`make_figures.py` and `make_dualarm_figure.py`.

## Reproducing and checking

    python3 gen_decks.py
    ngspice -b ro_all_ctrl.spice -o ctrl2.txt
    ngspice -b ro_all_par.spice  -o par2.txt
    python3 verify.py

`verify.py`, `verify_macro.py` and `verify_dualarm.py` re-derive every number
from the raw logs with their own code, without importing the analysis, and
print PASS or FAIL on each check. If a number in the paper is wrong, they fail.
