# Phase A naming — the SPEF hands over the ring index

Task A.3, first day, 19 August 2026. `spef_census.py` reads the SPEF the
shuttle published for each target and counts how much of the author's own
module hierarchy survives in it. 21 checks per target, both targets green, and
one open question from A.2 closed.

## The question A.2 left

A.2 found the placer's instance name in GDS property 61 on every placement, and
found that for `tt_um_litneet64_ro_puf` 1792 of those names are full RTL paths
— 256 × 7, one per ring inverter — while for `tt_um_PUF` none of 351 are. The
note under the Phase A table said the second target's SPEF might still carry
paths its GDS does not, that this was unmeasured, and that A.3 should measure
it rather than assume it either way.

It does carry them. 82 of `tt_um_PUF`'s 358 nets are named with the author's
own path, and 64 of those 82 are one per ring.

## The design is flat and the names are not

Both files declare `*DIVIDER /` and neither contains a single divider character
in any of its 2370 and 10794 mapped names. In SPEF's own terms these designs
are flat: there is no hierarchy for a reader to walk.

What survives is the path as text. Yosys and OpenLane flatten the hierarchy and
keep the pre-flattening path as one Verilog escaped identifier, so
`genblk1[0].puf_buffer.ro_array_1[0].inter_wire[3]` arrives in the SPEF as a
single name with every dot and bracket backslash-escaped. A reader that splits
on the divider finds nothing. A reader that splits on the escaped dot gets the
author's module tree back.

That is worth separating from the A.2 finding rather than merging with it. The
GDS leak and this one are the same underlying cause — a flow that preserves
names — but they are two different namespaces and they do not agree. A SPEF
carries net names after `*D_NET` and instance names after `*I`, and the census
reports them apart, because only the instance half is comparable with GDS
property 61.

## What it measures

|  | `tt_um_litneet64_ro_puf` | `tt_um_PUF` |
|---|---:|---:|
| nets | 4237 | 358 |
| nets carrying an RTL path | 2352 (55.5%) | 82 (22.9%) |
| instances | 4226 | 351 |
| instances carrying an RTL path | 1792 (42.4%) | 0 (0.0%) |
| GDS property 61 paths, from A.2 | 1792 | 0 |
| distinct owners in the widest family | 256 | 64 |
| nets per owner in that family | 8 | 1 |
| rings, from the A.1 ring census | 256 | 64 |

The last three rows are the point. Group every path name by its parent path and
count how many parents come out at each family size, and the largest family is
256 parents with 8 nets each for the first target and 64 parents with one net
each for the second. Both numbers equal the ring count that
`ring_census.py` derived from the netlist by different code in a different
week.

The grouping is deliberately blind to the design. It splits on the separator
and counts; it never looks for the word `ring` or `osc` or `ro` in a name, and
it has no per-target pattern in it. That is what stops the match from being
something I arranged.

## What the two targets look like from here

For `tt_um_litneet64_ro_puf` both namespaces leak and they agree. The 1792
instance paths sit two levels under 256 parents, the 2352 net paths sit one
level under 280 parents, and the 256 ring parents recovered from the instance
side are a subset of the parents recovered from the net side — the same 256
strings, from two halves of the file written by different stages of the flow.
The other 24 parents are the 16 counters and the 8 arbiters.

For `tt_um_PUF` the instance side gives nothing, exactly as the GDS did, and
the net side gives 64 names of the form `uutN.genblk1[i].f0.A`, plus 18 more
under the two counter instances `uut1.c` and `uut2.c` — eight counter bits and
one other output each. Reading the netlist by hand: each of those 64 is driven
by the `clkbuf_1` inside its ring and loaded by the ring's inverting gate — the
`and2b_1` enable gate on 62 of them, an `inv_2` on the two rings the flow built
differently. So the named net is the oscillating node, and every one of the 64
rings has one.

The census does not check that last paragraph. Establishing that a net sits on
a ring loop is topology recognition and that is A.4's job; today's script
counts names and says so. The hand check is recorded here because it is what
turns a count that matches into a claim about rings, and A.4 should replace it
with code.

## The consequence for the tiers, again

A.1 collapsed Tier 2 into Tier 1 for the first target. A.2 confirmed it in the
layout. This does the same thing to the second target from the other direction:
`tt_um_PUF` was picked as the harder generalisation case *because* its GDS
names gave nothing away, and its SPEF gives away the ring index anyway. So
there is no design on this shuttle, of the two examined, where an attacker
holding the published files has to recover ring identity.

Tier 3 is still the only tier that needs the hard part, and it is still a
discipline the attacker imposes rather than a constraint the platform imposes.
What changes is that the discipline now has to cover the SPEF's net names as
well as the GDS's instance names, and that is a stronger restriction than the
plan was written against. Re-price A.3 and A.4 at G1 with this in hand rather
than keeping the three-day and two-day estimates.

It also sharpens what C.1 should say. The cheapest useful attack on a Tiny
Tapeout RO-PUF runs no extraction at all, and the reason is now two published
files deep rather than one: the SPEF gives both the ring identity and the
parasitic capacitance of the node, in the same file, keyed by the author's own
index.

## The checks

Six of the 21 are the parser checking its own assumptions before it counts
anything — the design name, the divider, the pin and bus delimiters, the
capacitance unit, and that no line in the file went unrecognised. A SPEF that
declared a different divider would still parse and every count above would be
wrong in a way nothing else would notice.

Five are the file against itself: name map indices unique, every `*N` reference
resolving, no index used as both a net and an instance, each net total equal to
the sum of its own `*CAP` entries, and no net with an empty `*CONN`. The
arithmetic one has a tolerance and the tolerance is derived: entries print to
six significant digits, the worst relative residual over both files is 6.1e-06,
and the gate sits an order of magnitude above that at 1e-4 rather than on top
of it.

Three are against the netlist: every SPEF net is a net the netlist declares,
every SPEF instance one it instantiates, and the netlist nets the SPEF never
mentions are all ports or supplies — 30 of them for `tt_um_PUF` and 26 for
`tt_um_litneet64_ro_puf`, none unclassified. That last one is the shape A.3's
acceptance condition asks for: not that nothing is missing, but that
everything missing is accounted for.

The remaining seven are the leak itself and the cross-checks that make it mean
something: no name carries the declared divider, no two names collide once
unescaped, the instance and net namespaces name the same owners where both
carry paths, the instance path count equals the GDS census's, the SPEF instance
count equals the GDS census's logic-cell count, the owner count equals the ring
census's ring count, and the ring census read this exact netlist by hash.

Nothing here reads a capacitance value into a result. The selftest has a
control that multiplies every capacitance in the fixture by a thousand and
requires every number in the census to come out the same, so that is a property
of the script and not a promise.

## The selftest

Thirteen planted faults, each declaring the one check it must trip and failing
if it trips a second: a renamed design, a changed divider, femtofarads instead
of picofarads, a repeated index, a dangling reference, one index used for both
a net and a cell, a total that is not its own sum, a net with no connections, a
net the netlist does not declare, a cell the netlist does not have, a netlist
net the SPEF never mentions, two names that unescape alike, and a divider
inside a name.

Three controls that must trip nothing: the clean fixture, the same fixture with
its nets written in reverse order, and the same fixture with every capacitance
scaled. Reordering matters because a census that depended on file order would
have looked fine on these two files and broken on the third.

The one worth arguing about is the injectivity check. Unescaping is what lets a
SPEF name be compared with a netlist identifier at all, and it is lossy —
`a\.b` and `a.b` both come out as `a.b`. Neither shuttle file has a collision,
so the check passes on real inputs without doing anything, which is why the
fixture plants one.

## Archived, and what CI can actually run

`extraction/SPEF_CENSUS.json` holds every number above, both file hashes, and
all 42 checks. `extraction/inputs/` is gitignored and never mirrored, so CI
cannot re-run the census on the real files, the way it cannot for A.1 and A.2
either.

`spef_census.py --verify-archive` is what it can run. It reads
`SPEF_CENSUS.json`, `GDS_CENSUS.json`, `RING_CENSUS.json` and
`INPUT_MANIFEST.json` and re-checks the claims between them arithmetically with
no input file present: every fraction against its own numerator and
denominator, every depth histogram against its own total, the instance path
count against the GDS census, the owner count against the ring census, and both
file hashes against the ones the manifest pinned on 16 August. 26 checks. Four
planted faults in the selftest confirm it catches an edited count, an edited
owner total, a swapped hash and a census that recorded its own failures.

That is not re-derivation from raw inputs and it should not be read as it. It
is the narrower thing that is available: a number in this writeup cannot be
changed without either changing a file the manifest pins or failing in CI.

## Scope

This is a naming census. It says which nets and cells the published files
identify by the author's own name, and nothing about what those nets do, what
they are worth, or what a response would be. No capacitance value from either
foreign SPEF has been read into a result, no ring has been ranked, and nothing
has been predicted about either design.
