# Phase A topology: the rings, found without reading a name

Task A.4, 20 August 2026. `ring_topology.py` recovers the ring oscillators from
each published gate-level netlist using the public cell library and nothing
else, and only then compares what it found against the author's own names. 7
library checks and 22 per target, all green, and the hand check the SPEF
writeup was resting on is now code.

## What was actually missing

A.1's ring census already found combinational cycles and already reported 256
rings on the first target and 64 on the second. Today does not discover them
again. What it does is settle three things A.1 asserted or skipped.

A.1 decided which pin of a cell is an output from a table of nine pin names it
wrote by hand, and which cells hold state from six substrings of a cell name.
Both were plausible and neither was checked against the library they describe.

A.1 never asked whether a cycle oscillates. A combinational loop with an even
number of inversions is a latch. Counting loops and calling them rings works
here because these loops happen to be odd, and "happen to be" is the part that
needed removing.

A.1 treated every strongly connected component as one ring. A region where two
loops share a gate is also strongly connected, and would have been counted as
a single large ring with a plausible-looking cell count.

## Where the answers come from now

Each `sky130_fd_sc_hd` cell has a published functional view: a module, its port
directions, and a handful of Verilog gate primitives. 43 of them cover every
master either design instantiates. The script reads the port directions off the
module and derives the rest by evaluating the cell's own truth table over its
own inputs, at most 32 rows since the widest cell here has five, and
classifies
each input-to-output pair as inverting, non-inverting, non-monotone, or absent.

That turns a netlist into a signed graph on nets. A ring oscillator is a
feedback loop in it with an odd number of inversions around the loop.

Nothing in that paragraph reads a name. Nets and instances are opaque keys, and
the only thing the script knows about a cell is what its published model says.
The supply pin names are not hardcoded either: they are the union of the
`supply0` and `supply1` declarations across the library, which comes out as
VPWR, VGND, VPB, VNB.

All three attacker tiers in the plan grant the public PDK and cell library, so
this is an input rather than something recovered. The 43 views are pinned by
URL and SHA-256 in `extraction/library_sources.json`, every URL on a 40-
character commit, and each file is hashed before it is parsed. They are pinned
in their own file rather than added to `INPUT_MANIFEST.json`, because that
manifest records target selection on 16 August and reopening it four days later
to add inputs would make it a worse record of exactly the thing it exists to
record.

## What came back

|  | `litneet64` | `tt_um_PUF` |
|---|---:|---:|
| instances | 6549 | 2000 |
| with a functional view | 6520 | 1280 |
| with a signal pin | 4226 | 351 |
| feedback loops | 256 | 64 |
| feedback regions that are not one loop | 0 | 0 |
| loops with odd inversion count | 256 | 64 |
| nets on a loop | 9 | 2 or 3 |
| nets reaching a loop from outside | 1 | 1 |
| author-path nets on each loop | 8 | 1 |

The first target is 256 loops of nine nets, every one of them seven `inv_2`, a
`clkbuf_1` the flow inserted, and the `and2_1` that gates it. The second is 62
loops of two nets, an `and2b_1` and a `clkbuf_1`, with the inversion coming
from the gate's own inverted input. 2 loops of three, where the flow used a
plain `and2_1` and an `inv_2` instead. Every loop on both designs is odd, so
every loop oscillates. Every loop is reached by exactly one net from outside,
which is its enable, and drives exactly one net out, which is where it is
counted.

The 4226 and 351 are worth a line. Both the GDS census and the SPEF census
record those two numbers for their logic cells, and they only agree if a logic
cell is defined as one with any signal pin rather than one with an input. The
tie cell has two outputs and no inputs; there are 16 of them in each design,
and the first definition I wrote came out 16 short on both.

## The check that replaces the hand check

Yesterday's census matched 256 owners of eight net names against 256 rings, and
64 owners of one against 64 rings, and said plainly that a count matching a
count is not a net being on a ring. I checked the 64 by reading the netlist and
wrote that the writeup was resting on a hand check A.4 should replace.

It is replaced.

The loops above were recovered before a name was looked at. Then, as a
separate step, every escaped RTL path in the netlist is grouped by
parent path, and the families are placed against the loops:

- 280 families on the first target, of which 256 lie entirely inside one loop,
  one family to a loop, no family straddling two, and 24 touching no loop at
  all. Eight of the nine nets on each loop carry a name; the ninth is the gate
  output, which the author never named because the flow created it.
- 66 families on the second, of which 64 lie inside one loop each. The other
  2 are the counters and touch none. One net of each loop carries a name.

So the correspondence is one to one in both directions on both designs, and it
was not arranged: the loops were fixed before the names were read.

Two numbers fall out that agree with yesterday from a different file. The
netlist carries 2352 and 82 escaped path names, matching the SPEF's net-name
counts exactly, and the family split matches the SPEF's 256-of-8 and 64-of-1.
Yesterday those came from the parasitics file; these come from the netlist.

## A number A.1 got wrong

A.1's sequential-cell test is whether a cell name contains one of `__df`,
`__sdf`, `__edf`, `__dl`, `__sedf` or `__sdl`. `sky130_fd_sc_hd__dlygate4sd3_1`
contains `__dl`. It is a delay gate, two buffers in series, and it holds no
state.

It is instantiated 186 times on the first target.

`RING_CENSUS.json` records 6038 combinational and 482 sequential cells for
that design. The true split is 6224 and 296, and 482 is 296 flip-flops plus
the 186 delay gates. The second target has no delay gates and its 1264/16 is
right.

Nothing downstream moves. No ring on either design runs through a delay gate,
so treating them as sequential removed arcs that were not on a loop, and both
ring counts stand. I am leaving `RING_CENSUS.json` as A.1 wrote it and
recording the correction here and in the plan, rather than editing an archive
to make an old number look like it was always right.

The direction matters and the script now checks the one that can cost a ring.
A cell wrongly called sequential only deletes arcs, so it can lose a loop and
never invent one. A cell that holds state and is missed would fuse a design's
whole clocked side into one enormous feedback region. The check is that every
cell the library says holds state is one A.1's markers would have caught; the
other direction is reported as a note, because on this library it is not empty.

## The control the whole thing rests on

Every result above is re-derived a second time from the same netlist with every
net and every instance renamed to a hash of itself. Path names keep their depth
and their family structure so the audit at the end still has something to
group, but no word and no index survives. The canonical topology (loop count,
lengths, parities, cell composition, outside inputs, family sizes) has to hash
to the same value both times, and it does, on both designs.

That control cannot be tripped by any input file, since a file is exactly what
it is invariant to. So the selftest trips it from the other side, by patching
one step to drop arcs whose net name contains a chosen substring, which is the
failure it exists to catch.

## The checks

7 on the library and 22 on each target. Six of the library checks are the
parser refusing to trust itself: a view with an unknown primitive, a view whose
port list disagrees with its declarations, or a cell whose output no input
reaches all raise rather than scoring a result, because a cell model that
quietly lost an instance would report every arc as absent and every ring would
vanish with nothing to say why.

Of the 22 per target, five are the netlist against itself: one driver per net,
every pin a real port of its master, every unmodelled master carrying supply
pins only. Six are the recovery: every region a simple loop, every loop odd, no
loop through a non-monotone input, none through a cell that holds state, the
count and the shapes against A.1. Six are against the other archives. Four are
the name audit. One is the rename control.

Two of them pass for a reason worth stating. No loop runs through a cell that
holds state cannot fail on these designs, because a sequential output carries
no arc at all, so a loop cannot contain one; it would fail on a cell with both
a sequential and a combinational output, which this library does not have and
the fixture does. No loop runs through a non-monotone input is different. The
second target really does have 12 binate arcs, from five `xor2_1` and one
`xnor2_1`, and the check passes because none of them is on a loop. The first
target has none, so on that one it is the vacuous case.

## The selftest

53 checks. 18 planted faults, each naming the one check it must trip and
failing if it trips a second, plus 2 the parser must refuse outright rather
than score.

The faults are the ways this could be wrong: an edited cell view, a cell view
URL off a commit, a cell with an output pin A.1's table never listed, a cell
that holds state under a name A.1's markers would miss, an instance pin its
master does not have, a net driven twice, a physical-only master wired to a
signal, a ring with an even number of inversions, two rings sharing their gates
so the region is not a simple loop, a ring closed through an xor, a ring closed
through a cell that holds state, a ring left open, a ring gated by two enables,
a family of paths spanning two rings, one extra named net on one ring, and an
edited count in each of the three archives.

Controls that must trip nothing: the clean fixture, the same fixture with
longer rings, and the rename invariance already described. The fixture is a
design and not a unit test: five gated rings, some nets named and some not,
and a flop off to one side so a sequential cell is present without being on a
loop.

Isolating the faults took three passes again. The first version had one fault
tripping seven checks, because renaming a family's parent in the fixture also
made two rings share a net name and short them together. The name-audit checks
went from three to one for the same reason: any disturbance of the name map
breaks the correspondence in both directions at once, so three checks there
were three ways of reporting one fact and no fault could be isolated to any of
them.

## Archived, and what CI can run

`extraction/RING_TOPOLOGY.json` holds the recovered topology, the library file
hashes, and every check with its result. The netlists and the cell views are
not committed, so CI cannot re-run the recovery any more than it can for A.1,
A.2 or A.3.

`--verify-archive` is what it can run: 32 checks that re-derive every claim
living between the archived files with no input present. Each loop count
against the ring census, each logic-cell count against both the GDS and the
SPEF census, each netlist hash against the input manifest and the ring census,
each composition against the shapes A.1 recorded, each family placement against
its own loop count, and every library hash against the declaration. Five
planted faults confirm it catches an edited loop count, a swapped view hash, an
edited path-net count, a recorded failure and a URL off a commit, and a
control confirms a clean archive still verifies.

That is not re-derivation from raw bytes and it should not be read as one. It
is the narrower guarantee: no number in this file can change unless a pinned
file changed or CI goes red.

## Scope

This is A.4's ring half and not its comparison half. The plan's row asks for
"RO/mux/counter recognition", and what is here recognises rings, their enables
and their exits. Which challenge selects which pair of rings is not recovered,
and the counters are visible only as families of names that touch no loop. That
is the next piece of A.4 and it is the piece A.6 actually needs.

The recovery is Tier 1 and Tier 2 work: it reads the published netlist, which
this platform publishes for every project. Tier 3, where the attacker refuses
the netlist as well and starts from GDS geometry, still needs the connectivity
extraction A.3 was priced for, and nothing today makes that cheaper.

Two smaller limits. The truth-table method is exact for cells of this width and
would need a different tool past eight inputs, which is checked rather than
assumed. And the loop parity says a loop oscillates, not how fast: no
capacitance, no resistance and no geometry is read anywhere in this script, and
the frequency question is A.5's.

One naming note, because the repository now has two files with topology in the
name and they are unrelated. `sim/spice/gono/verify_ring_topology.py` asserts
that this project's own Arm A rings survived place and route intact. This one
recovers somebody else's rings from their published netlist.

One process note. At 1641 lines this is over the thousand-line day yardstick by
about a third, and the overrun is real rather than accounting: the script
carries a cell-library parser and evaluator that the earlier Phase A scripts
did without because they hardcoded what it derives. Splitting that half into
`extraction/cell_library.py`, which A.5 will want anyway, is the first job
tomorrow.
