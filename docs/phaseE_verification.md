# Phase E verification: the same numbers, from code that shares none

`chip/verify_phaseE.py`. Written 2026-08-29.

The house rule is that every number appearing in prose has to be
re-derivable by a script that does not share code with the one that produced
it. `verify_predictability.py` exists for that and writes its own SPEF parser
and its own least-squares solver rather than importing the ones under test.
This is the same job for the four days above it.

Nothing here imports `tile_budget`, `armc_cost`, `g2_decision` or
`observability_spec`. Twenty checks, all passing. Two controls, both
breaking what they are aimed at.

## What is re-derived, and how differently

The DEF is parsed again with its own patterns into its own shape. Row
occupancy is then computed a different way: instead of adding up cell areas,
each row becomes a list of intervals, the intervals are merged, and the
merged length is compared with the row's own site span. Both routes reach
26980.877 um2, and the interval version would notice an overlap that a sum
would quietly absorb.

Routing is walked with a different state machine, one that expands the DEF's
`*` repeat notation into explicit coordinates before measuring anything
rather than carrying the previous point through the measurement. The SPEF's
name map is resolved again. The three corner decks are read again. Every
priced total in E.1b is recomputed from the densities and the cell areas, and
every G.2 verdict is recomputed by applying the frozen rule to the recorded
numbers rather than trusting the verdict field.

One thing is not derived a second way, and it is not a shortcut. Cell widths
have no other source: there is no LEF in this repository and the placement is
all there is. So they are recovered by the same idea and a different
algorithm, row by row with no cross-row consistency requirement, and the two
answers have to agree exactly. If they ever differ, both are wrong until
somebody works out why.

## The disagreement it found

The first real run failed on two checks. The routing total came out
25306.955 um here against 25342.170 um from `armc_cost.py`, a gap of 35.215
um, all of it on met1.

The cause is `clknet_0_clk`. It is routed under a non-default rule, and every
one of its met1 runs reads

    + ROUTED met1 TAPER ( 85330 219470 ) ( 86710 * )

with a `TAPER` keyword between the layer and the first coordinate. The
verifier's pattern wanted coordinates immediately after the layer name and
skipped those segments entirely, 33835 database units of them, plus 1380 on
`clk` for the same reason. `armc_cost.py` splits on the `NEW` and `+ ROUTED`
keywords and then finds every coordinate pair in what is left, so the extra
word never troubled it.

The verifier was wrong and the thing it was checking was right. That is a
perfectly good outcome for a verifier, and it is the only reason anybody
looked at the clock net's routing syntax at all. The DEF grammar allows
`TAPER`, `TAPERRULE <rule>` and `STYLE <n>` there, all three are now
accepted, and the selftest has a case with one of each.

It is worth saying what would have happened without the second parser. The
number 25342.2 um would have gone into `docs/phaseE_armc_cost.md`, it would
have been correct, and nobody would have known that a plausible-looking
parser gets it wrong by 0.14 percent. The next script to read that file would
have made the same mistake with nothing to catch it.

## The two controls

A suite that passes on damaged input is not checking anything, so the whole
verification re-runs against damaged input twice, and each control is aimed
at a different half.

**Placement scrambled.** Every component's position is permuted within its
own row. Every row keeps its set of x positions and every cell keeps its row,
so the file still parses and the site count is untouched. What changes is
which master sits where. Five checks fail: row coverage, the class areas, the
free and held split, the per-ring area and the three ring densities. They are
the five that read the placement.

**Every routed segment moved up a metal layer**, cyclically. The total length
is unchanged, so a check that only adds everything up does not notice. The
per-layer lengths and every utilisation figure are wrong, and that is what
fails.

Neither control reaches the other's half, and saying so matters more than the
count. The placement control says nothing about routing. The layer control
says nothing about areas. What actually guards the routing total is that two
files parse it by different methods and have to agree to the unit, which is
exactly the check that caught the TAPER segments.

Four checks are reached by neither control, because the G.2 verdicts and the
E.2 window arithmetic do not depend on the DEF at all. Their guard is that
both are recomputed here from the frozen rule and the corner decks rather
than read out of the artefact.

## The selftest

Ten cases on inputs small enough to check by hand: a four-component DEF, a
two-segment net, a net whose only entry is a via, a net under a non-default
rule, a two-entry SPEF name map, and the scrambler doing what it claims.

Two of them exist because the verifier got the answer wrong first. The
overlap case plants two cells on top of each other and requires the interval
merge to report the overlap rather than double-count the area. The
non-default-rule case is the TAPER bug above, kept so it cannot come back.

## In CI

The `archived-evidence` job goes from 61 commands to 77. The five Phase E
scripts each run their selftest, then regenerate their JSON into `/tmp` and
`diff` it against the committed copy, then the verifier runs.

That pattern works here and it did not work for Phase A. Phase A's inputs
live in `extraction/inputs/`, which is gitignored and never mirrored, so
`spef_census.py` and `ring_topology.py` could only offer `--verify-archive`,
a narrower guarantee that a recorded number cannot change without CI going
red. Everything Phase E reads is committed: the DEF, the netlist, the SPEF,
`metrics.json`, the positions CSV, the three corner decks. So CI re-runs the
whole derivation from the raw bytes and compares, and a stale artefact is a
failed diff rather than an unnoticed drift.

`g2_decision.py --freeze-check` is in there too. It requires the criteria
file's SHA-256 to match in every place it is recorded and can see: the
script, the writeup and `PLAN_TO_DECEMBER.md`. CI only sees the first two,
because the plan is not mirrored, and the check says so on its own output
rather than quietly counting two out of three as agreement.

## What it does not cover, added 2026-08-31

This was written on the 29th and it re-derives the first four days. Five more
days landed after it and they do not have the same treatment, so the house
rule at the top of this page holds for part of the commit and not all of it.
Saying which part is the whole point of having the rule.

Covered: the tile budget, the Arm C cost model, the G.2 decision and the E.2
window table. Twenty checks against code that imports none of the four.

**Not covered: the Arm C region geometry.** The 25.76 by 10.88 um region, the
0.42857 density, the sixteen regions and the 25.96 percent of free area they
take are checked only by `gen_armc.py`, which is also what computed them. Its
eleven checks are real but they are all inside one program, so a wrong
assumption about site pitch or row height would pass all eleven. That number
goes into the countermeasure argument and it should have a second opinion
before the build, not after.

The later three days are a different case rather than a gap. `gen_e2_rtl.py`
emits text and checks it against the spec file it was generated from, which
is already two files disagreeing rather than one file agreeing with itself.
`preregister.py`, `release_manifest.py` and `g3_runbook.py` publish counts and
structure, not measurements: twelve artefacts, 97 gate commands, twelve steps,
4.5 days. Those are re-derivable by counting, and each of the three is read by
one of the others.

So the queue is one item long: extend this script to parse `ARMC_REGIONS.json`
and re-derive the regions from the DEF and the site definition without
touching `gen_armc.py`. That belongs before G.3 step 7, where the regions
first reach the placer.
