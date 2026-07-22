# First-build inputs

These are the routed outputs of the first (fully auto-placed) build, checked
in so the main experiment runs from a bare clone. The SPEF is OpenROAD's
nominal-corner extraction, the DEF gives the cell placements, and the netlist
is the routed gate-level Verilog. `gen_decks.py` and `verify.py` read from
this folder. The full build directory with every corner and report is too
large for the repo; these three files are the ones the experiment needs.
