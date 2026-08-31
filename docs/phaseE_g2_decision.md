# Phase G.2: Arm C, sixteen rings

`chip/g2_decision.py`, `chip/G2_CRITERIA.json`, `chip/G2_DECISION.json`.
Written 2026-08-27.

G.2's acceptance condition is that research value, area, cost and schedule
are documented and the choice between Arm C and the load ladder is made.

**The decision is Arm C, sixteen rings, under placement and routing
equalization constraints. The tile count does not change: still 2x2, four
tiles, three to buy after the coupon.**

The rule this was decided under is `chip/G2_CRITERIA.json`, sha256

    c4e3d3049d0e99b21974bf77413c83a7da90a3a5c18a61bafad5079757a62c77

frozen on 27 August before either option had been put through it. That hash
is in the script, in this file and in `PLAN_TO_DECEMBER.md`, and
`--freeze-check` in CI requires all four to agree. Same discipline as the A.5
tolerances, same reason: a rule written after seeing which option wins is a
description of the winner.

## The filter

Six hard constraints, each against a number measured in E.1a or E.1b.

| | constraint | limit |
|---|---|---|
| H1 | fits the free row area with a quarter still in reserve | <= 75% |
| H2 | needs no tile beyond the committed 2x2 | <= 4 |
| H3 | leaves both existing arms at sixteen oscillators | == 32 |
| H4 | gives the new arm at least eight oscillators | >= 8 |
| H5 | costs at most one new input pin | <= 1 |
| H6 | builds in at most five working days | <= 5 |

Fifteen configurations went through it. Twelve survived.

| option | area um2 | of free | tiles | pins | days | verdict |
|---|---:|---:|---:|---:|---:|---|
| Arm C, 8 rings, tight | 1893.3 | 10.96% | 4 | 1 | 4 | survives |
| Arm C, 8 rings, mean | 2388.9 | 13.83% | 4 | 1 | 4 | survives |
| Arm C, 8 rings, loose | 3204.9 | 18.55% | 4 | 1 | 4 | survives |
| Arm C, 12 rings, tight | 2809.1 | 16.26% | 4 | 1 | 4 | survives |
| Arm C, 12 rings, mean | 3552.6 | 20.57% | 4 | 1 | 4 | survives |
| Arm C, 12 rings, loose | 4776.5 | 27.65% | 4 | 1 | 4 | survives |
| Arm C, 16 rings, tight | 3724.9 | 21.57% | 4 | 1 | 4 | survives |
| Arm C, 16 rings, mean | 4716.2 | 27.30% | 4 | 1 | 4 | survives |
| Arm C, 16 rings, loose | 6348.1 | 36.75% | 4 | 1 | 4 | survives |
| ladder, 8 rungs | 1207.7 | 6.99% | 4 | 1 | 2 | survives |
| ladder, 12 rungs | 1870.8 | 10.83% | 4 | 1 | 2 | survives |
| ladder, 16 rungs | 2594.0 | 15.02% | 4 | 1 | 2 | survives |
| both, 16 tight + 16 rungs | 6319.0 | 36.58% | 4 | 1 | 6 | out on H6 |
| both, 16 mean + 16 rungs | 7310.3 | 42.32% | 4 | 1 | 6 | out on H6 |
| both, 16 loose + 16 rungs | 8942.1 | 51.77% | 4 | 1 | 6 | out on H6 |

Building both is on the table because the plan's instruction not to force
both into a compromised floorplan is a judgement, and a judgement is
something the frozen rule should get to answer rather than something to
assert. It answered. The reason is not area, which is the interesting part:
even the loosest pairing takes 51.77 percent of the free row area and clears
H1 with room to spare. It fails on schedule. Two builds is six working days
against a limit of five, and that limit exists because the chip path is 17 to
23 days against a shuttle opening in September, with G.3's full re-run of the
evidence suite behind it.

## A check that fired, and was wrong

The gate has a check, `G10`, whose first version required some real option to
be rejected. A rule that passes everything put to it is decorative and that
seemed worth testing for.

It failed on the first real run. All twelve of the single-arm configurations
survive, because the die has enough spare room that nothing on the table
comes near any limit. That is a fact about the floorplan, not a fault, and
loosening a threshold to make a check go green is exactly what the freeze
discipline exists to prevent.

So the check was wrong rather than the data. It is now a control: a probe
that is unacceptable on every axis at once, built in the script and never
counted as an option, run through the same rule, and every constraint has to
reject it. The rule is proved to have teeth without any real option having to
fail. The same shape as the scrambled control at the end of
`verify_predictability.py`.

The line that replaced it is worth keeping in view: on this die the hard
constraints do not discriminate between the single-arm options at all. The
decision is entirely on the preference order.

## The argument

The rule's preference order puts research value first, and no script should
score that, so this is the part a reader can disagree with.

**Arm C answers the question the paper exists to ask.** The hypothesis is
that an automated open flow leaks the layout into the frequency pattern in a
way a hardened macro does not. Arm A and Arm B already test that, and the
result they can give is a comparison of two treatments. What they cannot say
is whether the leakage is inherent to automated placement or merely to
*unconstrained* automated placement. Arm C is the treatment that separates
those, and it is the one a reader who builds open silicon actually wants: if
constraints suppress the leakage, the countermeasure is free and available
today in the flow everyone already runs. If they do not, the hard macro is
necessary and that is a stronger statement than anything two arms can
support.

**The ladder answers a different question, and a smaller one.** A causal
calibration curve from deliberate load to measured frequency is useful. It
is also a calibration of a relationship the SPICE work has already
characterised at 4.94 MHz per fF, and confirming a slope on silicon is
confirmation rather than a countermeasure result.

**The costs point the other way and are not large enough to matter.** The
ladder is 2594.0 um2 against Arm C's 4716.2 at mean density, a difference of
2122 um2, which is 12.3 percent of the free area on a die where 63 percent
would still be spare either way. Two build days against four. Neither
difference buys back a weaker result.

**The risk is the real argument for the ladder and it is a real argument.**
The open flow has no supported way to force sixteen identical placements.
That is the point of the experiment and it is also the thing that might not
work, which is why the criteria file records Arm C's delivery risk as high
and the ladder's as low before either was scored. A treatment that cannot be
built is worth nothing, and an experiment that is discovered to be
unbuildable in October, with a shuttle closing, is worse than one that was
never attempted.

That risk is handled by a deadline and a fallback rather than by picking the
safer option now.

## The build criterion, and when to give up

Arm C succeeds only if the constraints actually equalise the rings. E.1b
measured what unconstrained placement does to Arm A: bounding boxes from
218.96 to 382.87 um2 for the same 32 cells, densities from 0.314 to 0.549, a
spread of 1.75 to one, and ring shapes from 24.84 um across and four rows
tall to 13.34 across and seven rows tall.

So the criterion, preregistered here and to be frozen into the build's own
spec before the first constrained build runs:

- every Arm C ring's bounding box has the same width, the same height and the
  same row span, exactly, and
- the cell-area density of every Arm C ring agrees to within 0.02, and
- Arm A and Arm B come out of the build unchanged at the geometry-record
  level.

`chip/tile_budget.py` already measures all three, so the criterion is
checkable by a script that existed before the build did.

**The abort rule: if two constrained builds do not meet it, stop and build
the ladder.** That is four working days spent and the ladder's two still fit
inside H6's five-day limit for the arm that ships. Writing the deadline down
now is the difference between a fallback and a retreat.

This criterion is not part of the G.2 rule frozen on the 27th and is not
covered by that hash. It is a build criterion, dated today, and it belongs to
Phase E's build step.

## What this does not decide

The ladder's rung spacing, if the ladder is ever built, still needs the gate
capacitance the SPEF does not carry. E.1b said so and nothing here changes
it.

Whether all 17272.816 um2 of free row area is genuinely free is still a power
question, not a geometry one. Arm C at 16 rings and mean density takes 27.30
percent of it, so being wrong about a third of the decap would not change
this decision. Being wrong about three quarters of it would.

## For the purchase

Tiles: **unchanged at four**. Nothing on the table needs a fifth, and the
loosest option that fits leaves 63 percent of the free row area. The
purchase question that is still open is the one in
`docs/outreach/email_2_matt_tiles.md`: whether the free-tile coupon carries
over to 26d or is tied to a shuttle, which decides whether three tiles or
four have to be paid for. Chase that before buying. The subsidised PCB is
gated by nothing and should be bought the day 26d opens.
