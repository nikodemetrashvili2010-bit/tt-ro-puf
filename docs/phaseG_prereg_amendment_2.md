# Amending G.4 a second time, still before any die

21 October 2026. `chip/PREREG_AMENDMENT_2.json` is the record and
`chip/preregister.py --amendment` holds it to the two files it amends. This is
the argument behind it.

## What it is and what it is not

It changes no byte of `chip/PREREGISTRATION.json`, frozen on 31 August, or of
`chip/PREREG_AMENDMENT.json`, the first amendment, written on 18 October and
on GitHub since the 19th. It records both by SHA-256 and quotes the text it
amends in each. It says on its face that it is not a preregistration and
must never be cited as one. No die has been read. None exists, and none will
before mid-2027.

One item. The first amendment left the abstention rule as frozen, and this
one adds a condition to it.

## What was found

Every prediction in the project was read from one extraction, the SPEF
OpenRCX wrote for the release build. On 20 October the same layout went
through magic, which extracts the inside of the standard cells as well as the
routes, and the archive's ring decks were run again with its loads.
`sim/spice/magic/` has all of it.

In percent of the arm's mean, the convention `predictable_bits.py` and
`extraction/TOLERANCES.json` use, positive when the even ring is faster:

    pair    SPEF     magic    magic with fill, four grid positions
    0/1    +1.083   -0.015   -0.033 to -0.328
    4/5    +2.037   +1.628   +1.641 to +1.825
    6/7    -1.423   -2.428   -1.753 to -1.957
    10/11  -2.291   -0.964   -0.685 to -0.975
    12/13  -2.878   -2.258   -2.052 to -2.225
    14/15  -1.840   -2.992   -1.044 to -1.168

Those are Arm A's six scored pairs under the frozen rule. Five come out the
same way in every view and stay over the line. Pair 0/1 does not. The SPEF
puts 1.36 fF more on ring 1 than on ring 0, and magic about a tenth of a fF,
so where the SPEF calls ring 0 faster by 1.08 percent, magic calls the two
level.

Neither extractor is silicon, and this does not say which is nearer. It says
the call on 0/1 depends on which tool reads the layout.

## The rule now

A pair is scored only if its separation clears the line in
`TOLERANCES.json`, with the same sign, in both tables: the SPEF's, which the
predictions are read from, and magic's, through lumped decks because its
extraction is capacitance only. Everything else is an abstention, counted and
published, its sign never scored either way, as before. The line is read from
`TOLERANCES.json` and not re-derived, a separation is f_a minus f_b as a
percent of the mean of that arm's sixteen rings in the same table, and for a
scored pair the two tables agree on the sign, which is the prediction. Same
rule for every arm.

The tables, each recorded by hash in the amendment:

    first, Arm A   sim/spice/gono/rc_validation_3arm.csv, rc_MHz
    first, Arm B   sim/spice/gono/armb3/armb_instances_out.txt, f_kNN
    first, Arm C   sim/spice/gono/rc_validation_armc.csv, rc_MHz
    second         sim/spice/magic/magic_rings.csv, magic_MHz

What it does:

    arm  scored as frozen                   scored now
    A    0/1 4/5 6/7 10/11 12/13 14/15     4/5 6/7 10/11 12/13 14/15
    B    none                               none
    C    4/5 8/9 10/11 12/13 14/15          4/5 12/13 14/15

Arm C's 8/9 and 10/11 go because magic puts them under the line, -0.010 and
+0.525. Arm B scores nothing either way.

## Why this and not the other two

Three ways were on the table on 20 October: leave the scored set alone and
record the check, score only what both extractors agree on, or move M1 to a
rank correlation over the sixteen rings.

The line already allows each ring an extraction error the size of one ring's
mismatch, T2a in `TOLERANCES.json`. Two open extractors part on 0/1 by about
1.3 fF, many times that. A call that turns on the choice of tool is a call
about the tool and not about the layout, and the line's own reasoning, T6, is
that such a call is not scored: a low-margin sign that comes out right is not
a result and one that comes out wrong is not a failure. So this is the frozen
rule's idea applied to a second source of error it had not met.

Leaving it alone would have kept a pair magic calls level inside a test that
needs six of six. The rank correlation was the 8 September audit's
suggestion and is the strongest of the three, but it replaces the test that
was chosen on 3 October with a different statistic, and the falsification
rule is written about a count of bits.

## What it costs

M1 on Arm A can no longer pass on its own. Five of five is 1/32, 0.03125,
over the first Holm level, so it is tested at 0.05 only after M4 has cleared
0.025. If M4 fails, M1 fails with it.

That was taken knowing what M4 looks like in every model. Run through
`chip/primary_tests.py` with the model frequencies as they stand:

    model           M4 ratio   p(1)
    SPEF            0.363      0.0011
    magic           0.471      0.012
    magic + fill    0.20-0.23  0.00011 or less

With the 0.062 percent ring mismatch drawn onto magic's frequencies 200
times, p(1) stayed under 0.025 every time, the largest 0.023. So magic
without fill is where the trade costs most, and even there M4 clears the
first level. What no model holds is the die-position gradient from the 8
September audit, which works against M4.

Pair 0/1 scores nothing whichever way it comes out. And the scored pairs now
rest on a second tool's numbers as well as the first's.

## Fill is left out of the rule

Whether Tiny Tapeout's fill reaches inside the tile, and with which tool, is
not known. With the fill open_pdks' generator draws, at four grid positions,
the first in SPICE and the other three moved from it by the fitted slope,
Arm A's five scored pairs keep their sign and stay over the line in every
one. None of Arm C's three does: 12/13 turns round, and 4/5 and 14/15 keep
their sign but fall under the line. M1 on Arm C is secondary and carries no
claim, so they stay in its scored list with that note.

## The two tables are not the same kind of deck

The SPEF's side is the RC decks the predictions come from. magic's side is
lumped, one capacitor per net, the only kind a capacitance-only extraction
gives. So the rule compares the prediction as made with the second
extractor's lumped view, and that should be said plainly.

Like for like, the SPEF's own lumped decks, the `lumped_MHz` column of the
same tables, keep Arm A's five scored pairs over the line with the same
signs, and split on 0/1 the same way: +1.069 against magic's -0.015. So the
split is the extractor's and not the resistance's. The lumped decks differ
from the RC decks elsewhere. They put 2/3 and 8/9 over the line, which the RC
decks and the frozen rule leave out, and Arm C's 4/5 and 14/15 under it,
-0.588 and -0.602 where the RC decks have -1.322 and -0.648.

## What the gate checks

`preregister.py --amendment` runs the first amendment's nine checks and then
six more:

    B01  records the frozen file and the first amendment by hash
    B02  says it is not a preregistration, no die read when written
    B03  its quotes are what both files say
    B04  dated after the first amendment and before silicon, with who,
         what, why and what it gives up
    B05  reads the archive's SPEF tables, magic's table and the frozen
         line, each the file whose hash it records
    B06  the scored pairs it lists, and the frozen rule's, are what the
         rule gives when worked again from those tables

Each has a planted fault in `--selftest`, on a copy of the real files, and
B06 has two: a pair added to the list by hand, and a magic table that calls
0/1 the SPEF's way, recorded by its own hash so that B05 still holds. Every
fault trips its own check and no other.

`sim/spice/magic/tabulate.py` writes `magic_rings.csv` from the deck logs,
with a selftest of seven checks, and the gate writes it again and diffs it.
`chip/hash_stability.py` H02 holds every hash the amendment records.

## Mistakes on the way

Two from 20 October, kept.

The comparison tables that day divided each pair by its own mean instead of
the arm's. The convention here, and in `sim/spice/magic/`, is the arm's,
which is the frozen one. It moves no number by more than 0.06, and no pair
crosses the line or changes sign either way.

And the M4 line that day was read off peak-to-peak spreads, 0.37, 0.41 and
0.24, and called Arm C's spread well under Arm A's. M4 is a ratio of
standard deviations, and on that measure magic without fill gives 0.47,
which leaves less room under 0.56 than "well under" said.

## Not settled

Everything left open by the first amendment is still open: the M4
secondary's interval, M2's shuffles and seed, E.3, and the paper's
preregistration section, which now takes up both amendments. Whatever
archive of the per-pair predictions is made before the first die is read
takes the scored pairs above.
