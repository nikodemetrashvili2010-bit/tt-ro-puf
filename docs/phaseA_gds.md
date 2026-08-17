# Phase A layout — the four files describe one die

Task A.2, 17 August 2026. `gds_census.py` reads the GDS the shuttle published
for each target and checks it against the LEF, the gate-level netlist and the
flow's own metrics. 31 checks per target, both targets green.

## A.2 was written for a step that does not exist

The plan costs A.2 as an OAS-to-GDS conversion, and its acceptance condition is
that cell counts, the bounding box and the top cell survive that conversion.
Tiny Tapeout publishes GDS directly. There is no conversion, so nothing has to
survive one, and the day could have been spent writing that down and moving on.

I did not, because the conversion check was standing in for something that still
matters. Everything Phase A does later quotes one of four files — GDS, LEF,
netlist, metrics — and quietly assumes the other three would have said the same.
A.5 compares extracted capacitance per ring against the SPEF; A.6 predicts a
response for a ring identified in the netlist and located in the layout. If the
netlist and the layout disagree about which cell is where, every one of those
comparisons is against the wrong thing and nothing downstream would say so.

So A.2 became: prove they agree, one instance at a time.

## What it checks

The reader is stdlib. It walks GDSII records itself — structures, elements,
transforms, property records — rather than calling a layout library, because a
library that silently repairs a malformed file is exactly the wrong tool for
asking whether the file is well formed.

Per target it establishes, and fails on:

- the file holds one top structure and it is the design;
- the database unit is a nanometre and the user unit a micron;
- the top structure carries one die outline, anchored at the origin;
- that outline equals the LEF macro size, and its area equals the die area the
  flow recorded in `metrics.csv`;
- every placement sits at the top level, and every master it names is defined
  in the same file;
- the count of placements equals `TotalCells`, and the split into logic, fill,
  decap, tap and diode equals `NonPhysCells`, `FillCells`, `DecapCells`,
  `WelltapCells` and `DiodeCells`;
- every instance origin is on the die, and every instance whose master carries a
  cell outline lies inside it;
- every placement carries an instance name, and no two names collide once the
  Verilog and GDS escaping is removed;
- the set of placed instance names equals the set of netlist instance names, and
  every one of them has the same master in both;
- per-master totals agree between the two;
- and the ring census from A.1 was taken from this same netlist, by hash.

| | `tt_um_litneet64_ro_puf` | `tt_um_PUF` |
|---|---:|---:|
| die | 161.000 × 225.760 µm | 161.000 × 111.520 µm |
| structures | 61 | 38 |
| placements | 6549 | 2000 |
| logic / fill / decap / tap | 4226 / 1167 / 700 / 456 | 351 / 306 / 1118 / 225 |
| named with an RTL path | 1792 | 0 |
| checks | 31 pass | 31 pass |

The last cross-check is worth spelling out because the numbers do not match on
their face. A.1's ring census counted 6520 cells in the first netlist; the GDS
places 6549. The difference is 29 `sky130_ef_sc_hd__decap_12`, which the census
never counted because its parser only recognises `sky130_fd_sc_hd__`. The same
arithmetic holds for the second target at 1280 and 2000, where the gap is 720.
The script checks that identity rather than the raw totals, so the two censuses
are tied together instead of merely both existing.

## The GDS publishes the hierarchy too

A.1 found the author's RTL hierarchy sitting in the SPEF's net names. It is in
the GDS as well. The flow writes the placer's instance name into property 61 of
every placement, and for the first target 1792 of those names are full RTL
paths — `genblk1[0].puf_buffer.ro_array_1[0].genblk1[0].inv` is the first
inverter of the first ring of the first block. 1792 is 256 × 7: every inverter
in every ring is named, individually, in the layout file.

That closes a gap the tier split had left open. Tier 2 was meant to be the
attacker who has the GDS but not the author's names, and has to recover which
cell belongs to which ring. On this platform, for this design, the GDS *is* the
author's names. Tier 2 collapses into Tier 1 unless the attacker deliberately
discards property 61 — which is a discipline, not a constraint, and is the
definition of Tier 3.

The second target does not do this. Zero of its 351 logic placements carry an
RTL path; they are all synthesis names like `_238_`. Same shuttle, same flow,
same year — the difference is upstream, in how much hierarchy each author's
coding style left for the flow to preserve. So `tt_um_PUF` is the harder target
in a way the plan did not anticipate when it picked it as the generalisation
case, and A.7 on it is closer to a Tier 3 exercise than A.6 is. That is an
argument for keeping it, not dropping it.

One thing I have not verified with a script and am therefore not putting a
number on: the second target's SPEF does appear to carry some RTL paths even
though its GDS carries none. If that holds, the two files leak different amounts
for the same design, and A.3 should measure it properly rather than take this
paragraph's word for it.

## What it changes

A.3 and A.4 were priced on connectivity having to be recovered before anything
could be recognised. For the first target it does not have to be: the layout
hands over ring membership directly, and the netlist gives the connectivity. The
re-pricing still belongs at G1, but the direction is now clear for one target
and unclear for the other, which is a better position than assuming one number
for both.

Nothing here changes the build. `src/`, `info.yaml`, the macro views and
`dualarm/build_current/` are untouched, and the paper was not rebuilt.

## Scope

This is placement bookkeeping. It reads geometry only far enough to check that
cells sit on the die, and it reads no parasitics at all — no capacitance, no
resistance, no delay. It does not say which ring is faster than which, and no
response has been predicted for either design. The A.5 tolerances are still not
frozen, and until they are, no foreign analysis runs.

It also cannot tell whether the published files match the die that was actually
manufactured. It establishes that they match each other, which is the most any
public artifact can establish and is exactly the position a real attacker is in.
