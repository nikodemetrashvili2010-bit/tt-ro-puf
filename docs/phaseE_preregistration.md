# Phase G.4: the 2027 analysis, frozen before there is any silicon

`chip/preregister.py`, `chip/PREREGISTRATION.json`. Written 2026-08-31.

G.4's acceptance condition is that pair definitions, exclusions, conditions
and primary metrics are timestamped before silicon. They are, and the file
that holds them is gated on its own SHA-256:

    81b697b4904dd406586df06d8ff411fdcd50b331420eba62c840bc4bfec58b8f

recorded in the script, in this file and in `PLAN_TO_DECEMBER.md`, with
`--freeze-check` in CI. Same discipline as the A.5 tolerances and the G.2
criteria.

The reason to do this now rather than in 2027 is not paperwork. The parts
arrive in June 2027. Between now and then there is every opportunity to
notice that a different pairing, a different exclusion or a different metric
would make the result look better, and no way afterwards to prove that
nobody did. Writing them down while no data exists is the only thing that
makes the eventual numbers mean anything.

## The protocol, in one line

**27 condition cells, 20 repeats, 48 oscillators: 25920 readings a die.**

Three voltages, 1.62 to 1.98 V. Three temperatures, -40 to 125 C. Three safe
window lengths. That box is the one the SPICE corners already cover, which
`P10` checks rather than assumes, so nothing gets measured at a condition the
simulation has never seen.

The order inside every cell is ABBA: arm A, then B, then B, then A, then C
twice mirrored the same way. Sequential comparison drifts. A mirrored order
cancels a linear drift across the cell, and it costs nothing but sequencing.

The fourth window, the one that overflows at every corner, is not in the
measurement grid. It is there to prove the sticky flag works and it is read
separately.

## The pairing, and why it is the boring one

Adjacent within an arm: ring 0 against 1, 2 against 3, up to 14 against 15.
Eight pairs an arm, 24 in all.

Sixteen rings split into eight pairs 2,027,025 different ways, and the choice
matters: `sim/spice/gono/pairing_policy.py` exists because re-pairing is the
cheapest countermeasure anyone could propose and it scores what that costs in
stability. This preregistration is not that study. It commits to the pairing
the RTL already builds and the one Section 7's result is quoted at, so that
the silicon tests the claim on the record rather than a claim chosen later.

The pairs are built by the script, not listed in the file. Twenty-four hand
written pairs put a typo one keystroke from a different experiment, and `P04`
checks that every ring in every arm appears exactly once.

## Nothing is copied that already exists

The abstention rule is `extraction/TOLERANCES.json`'s, referenced by that
file's hash and read at analysis time. `k`, the pair sigma and the
high-margin threshold do not appear in the preregistration at all, and `P03`
fails if any of them is pasted in.

That check needed a second pass. The first version searched for each value as
a bare string, and `k = 5` matched the "5" inside `50000000`. It looks for
the distinctive thresholds by value and for `k` only in a labelled form now,
and the file says why: a bare small integer cannot be told from any other
number, so pretending to detect it would be theatre.

The window lengths and the reference clock come from
`chip/OBSERVABILITY.json` the same way. `P08` catches a protocol that names a
clock the windows were never sized against, which is the mistake that turns
every count into a number nobody can compare.

## The four metrics

| | what it measures | direction |
|---|---|---|
| M1 | predictable bits an arm, out of 8 | Arm A high, Arm B near chance, Arm C between and closer to B if constraints work |
| M2 | across-die repeatability of the frequency pattern | Arm A repeats, Arm B does not |
| M3 | bit stability across the 27 cells | reported, not predicted; it is the cost side |
| M4 | Arm C's frequency spread over Arm A's | below 1 if placement equalization worked |

M4 is the countermeasure claim and it is the one the whole third arm exists
for. It is a ratio on the same die, so it does not depend on how fast that
particular part came out.

**Both headline metrics have a stated way to fail.** If Arm A's predictable
bits are not above chance after correction, the leakage claim fails and the
paper says so. If Arm C's spread ratio is not below 1 with its interval clear
of 1, equalization did not suppress the layout term and the paper reports a
null. `P13` requires that both are in the falsification block.

Seven tests: M1 across three arms, M2 across three arms, M4 once. Holm
correction, named here rather than chosen once the spread is known, and `P15`
checks the word is there.

## The exclusions, and the one that is a refusal

Four things get dropped before any analysis, all of them mechanical: a
reading whose sticky overflow is set, and the cell around it; a reading whose
protocol byte the collector does not know; a cell whose repeats disagree
about the build id; an oscillator that reads zero in every repeat, which is
recorded as dead with its index published.

Then the abstention rule, which is not an exclusion in the same sense.
Abstentions are counted and published, and their sign is never scored either
way.

And then a refusal, which `P17` enforces: **no reading is dropped for being
an outlier.** If a die behaves strangely that is a result and it gets a
paragraph, not a filter. A three-sigma rule added in 2027 would be
indistinguishable from making the answer come out right, which is exactly
what a preregistration is for.

## Seventeen checks

All passing. Fifteen planted faults on a fixture plus two that come from the
files the preregistration leans on, and one direct test of the pair builder
against arithmetic that does not call it.

Two faults are worth naming. `P06` is tripped by making the tolerances file
and the preregistration disagree about the sign of a bit, which is the sort
of thing that would silently invert half the results. `P16` is tripped by
declaring that predictions need not be archived before measurement, which is
the single line that would make the whole exercise decorative.

## What this does not settle

The predictions themselves. This freezes how they will be judged, not what
they are. The per-pair sign predictions come out of Phase A's pipeline
against the final build's own database, and they get archived and hashed
before any die is read. That is a step for after the Arm C build, when there
is a final layout to predict from.

The collector is also not written. E.3 is deliberately out of the
manufacturing path, and the protocol above is what it will have to satisfy
when it does get written, not a description of something that exists.
