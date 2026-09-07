# Splitting the cell library out, and what that turned up

The split has been queued since 20 August, when `ring_topology.py` came in at
1641 lines and I wrote down that a third of it was a cell library parser with
no business being in a loop finder. Two other scripts had left notes asking
for the same module by name:

    chip/armc_cost.py    "The proper derivation, from the library's own
                          functional views, lives in
                          extraction/ring_topology.py and belongs in
                          extraction/cell_library.py when that module is
                          split out."

    chip/lint_rtl.py     "Every stub port is declared inout, which means the
                          elaboration checks names and arity and deliberately
                          does not check pin direction. Direction belongs to
                          extraction/cell_library.py when that module is
                          split out."

So the shape of the day was written down before it started. What was not
written down is the reason it had stayed queued, and I found that in the
first twenty minutes.

## The library did not cover this project's own chip

`extraction/library_sources.json` pins 43 published functional views. It was
assembled on 20 August for the two Phase A shuttle targets, litneet64 and
tt_um_PUF, and its numbers are quoted in A.3 and A.4.

`dualarm/build_current`'s netlist instantiates 51 distinct sky130 masters.
The 43 views cover 35 of them. Sixteen are missing:

    a2111oi  a2bb2o  a32o  clkdlybuf4s25  diode  mux2  mux4  nand2b
    nor3     o21a    o21ai o22a           o31a   o31ai or3b  or4b

That is why `armc_cost.py` still had a hand-typed table. There was nothing to
derive from. Moving the parser without fixing that would have moved the
problem into a new file and left the note in place.

I did not reopen `library_sources.json`. Its counts are quoted in two
finished tasks and 20 August is a record of what A.4 was allowed to read.
The sixteen went into `extraction/library_sources_design.json` instead, from
the same repository at the same commit `ac7fb61f`, pinned the same way, with
URL, bytes and SHA-256 each. Two manifests, one library, and L07 fails if
they ever declare the same cell.

## The bug the wider library exposed

The first run over all 59 views said `mux2` and `mux4` hold state.

They do not. `evaluate_cell` set `cell.sequential` from one question, "is
this output driven through a UDP", and on the 43 views that question and "is
this output sequential" had the same answer, because the only UDPs in those
views are `udp_dff$P` and `udp_dff$PR`. `mux2` is driven through
`udp_mux_2to1`, which holds nothing at all.

Nothing downstream was wrong. What the loop finder needs is "this evaluator
cannot tell you the arcs through here", and that is true of a mux UDP exactly
as it is of a flip flop, so the arc still gets cut and A.4's rings come out
the same. What was wrong was the name and the sentence the report printed
under it: "sequential outputs carry no combinational arc" was describing a
set that was about to stop meaning what it said.

Two sets now. `opaque` is an output whose arcs this evaluator cannot derive,
and that is what cuts an arc. `sequential` is the subset driven through a
state element. On the 43 views they are the same set, which is the reason
Phase A's numbers do not move, and `--verify-archive` still reads 32 checks
and 0 failed.

Which UDPs hold state is read off the library rather than remembered. Four
distinct UDPs appear across all 59 views, two flip flops and two muxes, and
`is_state_udp` raises on one matching neither rule instead of defaulting.
Defaulting to False in particular would fuse a design's whole clocked side
into a single feedback region, so it is the direction that must not be
guessed.

The check that caught it, once the concepts were separated, is L04, and it is
A.1's own marker table doing the work: `mux2` matches none of `__df`,
`__sdf`, `__edf`, `__dl`, `__sedf`, `__sdl`, so a derivation calling it
sequential contradicts the table and L04 says so.

## The artefact, and why there is one

`extraction/inputs/` is gitignored and never mirrored, so nothing in CI can
read a cell view. But `armc_cost.py` and `lint_rtl.py` both run in the gate
and both need the library. So the module emits `extraction/CELL_LIBRARY.json`
here, 59 cells with their pins, supplies, opaque and sequential outputs and
every arc class, and that file is committed.

Eight checks. `--emit` runs them against the views, `--verify-archive` runs
them against the committed file, and the two differ in exactly one place:

  L01  with the views, every declared view is the declared bytes; without
       them, every archived cell is one a manifest declares

That is the same narrower guarantee `spef_census.py --verify-archive` gives,
and it is worth saying plainly what it is and is not. In CI this is not a
re-derivation from the published bytes. It is the statement that a recorded
number cannot change without the gate going red.

L08 is the one the split was for: the archive has to cover every master this
project's own netlist uses. It reads 51 masters, 0 uncovered. The netlist it
reads is committed and mirrored, unlike the views, so this check does run in
CI, and it is what makes `armc_cost.py` safe. The day a synthesis run picks a
cell nobody fetched, the gate says so instead of the cost model quietly
reading a driver as a sink.

## What the two consumers do now

`armc_cost.py` had ten output pin names in a frozenset. The derivation has
five: HI, LO, Q, X, Y. The four it drops, Q_N, SUM, COUT and COUT_N, belong
to cells this design does not instantiate, so `ARMC_COST.json` is byte
identical after the swap. I checked that rather than reasoning about it, and
C01 and C02 remain what make the whole thing safe: every signal net must have
exactly one driver, and only the top-level inputs may have none. `out` stays
declared by hand, because it is `ro_macro_hard`'s pin and the macro has no
published functional view.

`lint_rtl.py`'s stubs carried `inout` on every port, so the elaboration
checked names and arity and not direction. They carry real directions now, 59
cells' worth, and a pin the library does not know stays `inout`, which means
the supply pins and `ro_macro_hard`'s. Falling back rather than failing is
deliberate: a stub is scaffolding, and what would be wrong is silently
calling a known output an input.

E01 and E02 both pass with directions in place, so the design has no
direction mismatch and the lint is strictly stronger than it was. I would
have preferred it to find something.

## Lengths, honestly

`ring_topology.py` went from 1641 lines to 1243. `cell_library.py` is 1004.

So the total went up by about 600 lines, and `ring_topology.py` is still 24
percent over the thousand-line day yardstick rather than 64 percent over.
Both of those are worth saying rather than quoting the first number on its
own. The 600 are the two-manifest handling, the archive, eight checks and a
fixture with its own faults, none of which existed before; what came out of
`ring_topology.py` is the part that was never about loop finding. What is
still over in that file is the loop finder and its reporting, and splitting
those further would be splitting for the number rather than for a reason.

The gate is 119 commands now, up from 117.
