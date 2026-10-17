# Amending G.4 before any die exists

18 October 2026. `chip/PREREG_AMENDMENT.json` is the record and
`chip/preregister.py --amendment` holds it to the frozen file. This is the
argument behind it.

## What it is and what it is not

`chip/PREREGISTRATION.json` was frozen on 31 August and it is not touched.
The amendment records it by its SHA-256, `81b697b4...`, and quotes the frozen
text of every key it amends. It says on its face that it is not a
preregistration and must never be cited as one. Same shape as
`G2_AMENDMENT.json`, and for the same reason: a decision taken late has to be
readable as late.

What makes it worth more than a decision taken after the data is that there
is no data. No die exists and none will before mid-2027. Everything in it was
decided with the audit's numbers in hand and nothing else.

The research design was read cold on 8 September and four findings came out
of that. Four more gaps turned up on 23 September and one more today. Nine
items in all. Five come from the four decisions of 3 October, three from
today's, and one from 23 September.

## The family, and M1's test

The frozen family is seven tests under Holm, so the first level is 0.05/7,
0.007143. Arm A's eight pairs split six scored and two abstaining under the
frozen tolerances, so the result the project predicts is six of six, and six
of six has p = 0.015625. As frozen, the leakage claim fails on the exact
result it predicts.

Decided on 3 October: two primaries, M1 on Arm A and M4, Holm over those two.
The smaller p is tested at 0.025 and the other at 0.05. Six of six passes
first. Five of five, 0.03125, can still pass second.

M1's test is the exact one-sided binomial on Arm A's scored pairs. The frozen
text named a correction and never a test, and the two readings that fit it
were far apart.

Everything else is secondary. M2 on all three arms and M1 on Arms B and C
are computed and reported and carry no claim. That takes most of the audit's
third finding with it, because Arm B being near chance stops being a test that
has to come out as a null.

## Which die

New today. M1 and M4 are tests on one die, and the frozen file never says
which. With M2 needing three dies there will be more than one, and a die
picked after they are all read is a result picked. So the two primaries are
tested on the first die read and on no other, and which die that is goes into
the archive with its first reading, before anything is computed on it. The
rest are reported with the same numbers and test nothing. That gives up
whatever power later dies would add, and keeps the primaries one die's tests
however many come in.

## M2's dies, and M4's secondary

M2 runs only if three or more dies are read by 30 September 2027, otherwise
it is reported as not run. The pairs of dies are combined as the mean of the
pairwise Spearman correlations, with a p-value from shuffling each die's ring
labels. As frozen it could not be computed at all: no die count and no rule
for combining correlations that are not independent.

M4 stays as frozen. The secondary named on 3 October is Arm C's spread inside
its lower eight rings and inside its upper eight, pooled, over Arm A's. The
column is 180 um tall and Arm A's block 98, so a gradient up the die adds
more to Arm C's spread than to Arm A's, and that pushes M4 toward the null.

"Lower" and "upper" here are below and above Arm A, by where
`dualarm/src/armc_fix.tcl` puts each ring's NAND, and not ring numbers 0 to 7
and 8 to 15. Those are different sets:

    below Arm A   rings 0, 1, 4, 5, 6, 10, 11, 12   y 27.2 to 59.8 um
    above Arm A   rings 2, 3, 7, 8, 9, 13, 14, 15   y 174.1 to 206.7 um

Each half spans 33 um of height. Pooled means the two sums of squares about
each half's own mean over fourteen degrees of freedom. The secondary decides
nothing.

## M4's interval

The frozen rule says the ratio has to be below 1 with its confidence interval
clear of 1, and names no interval. Three were on the table today and I
took the permutation one.

The ratio is two standard deviations of sixteen values each. That is where the
textbook F interval is least safe. It is exact for normal data, and ring
frequencies shaped by a layout have no reason to be normal; with heavy tails
it comes out too narrow, which would make passing easier than it should be.
A bootstrap over sixteen rings runs narrow as well.

The method, all of it in the amendment:

- each arm's sixteen ring means less that arm's own median
- for a ratio r, Arm C's centred values divided by r and pooled with Arm A's
- the 32 shuffled between the arms 100000 times from one generator, seed
  20261018, the same shuffles used at every r
- p(r) is the share of shuffles at or under the observed ratio, the observed
  split counted as one of them
- the interval is every r with p(r) above the level Holm gives M4, and it is
  clear of 1 exactly when p(1) is at or under that level

It assumes only that the two arms, once centred, differ in scale and not in
shape.

What it costs, measured rather than guessed. On normal arms of sixteen, the
case where the F interval is exact, the permutation test wants the measured
ratio under about 0.56 to clear 0.025, where F wants 0.591. At 0.05 it is
0.62 against 0.645. The 0.56 is a median over 150 synthetic pairs of arms; the
middle half of them needed 0.50 to 0.61. The F figures are the F(15,15)
quantiles and come out the same every time.

`chip/primary_tests.py` is the implementation, both tests and Holm, 244 lines
with a selftest of thirteen checks. The amendment records its SHA-256, and
`chip/hash_stability.py` H02 fails the gate if a byte of it changes. If it
ever has to, that is another amendment.

I checked it against a second implementation that shares no code with it,
numpy permutations and its own centring, on four synthetic pairs of arms at
two values of r each. All eight p-values agree inside two standard errors of
the shuffling.

## Which count is a reading, and the order

Since 23 September the firmware starts every selection twice and keeps both,
because the first run after a change of selection can read one count high.
The frozen protocol was written when a reading was one start. The amendment
says what the firmware and the datasheet have said since: a reading is the
second start's count, and `count_first` is analysed on its own and never
stands in for one.

The frozen order is ABBA by arm. No script in the repository reads that way,
and `measure_puf.py` has read every repeat in a fresh seeded random order since
July. Decided today to keep the random order. The frozen sentence also fixes
nothing about the order of the sixteen rings inside an arm, and an order that
repeats there lines ring index up with any drift inside the block, which is
spread M4 would count.

What it gives up is the exact cancelling of a linear drift that a mirrored
order buys. Drift averages over the twenty repeats instead, and every reading
carries a time stamp.

## 1.95 V

Decided on 3 October, found on 23 September. 1.98 V is 30 mV past the 0 to
1.95 V SkyWater gives for the gate and drain of its 1.8 V devices and past
the fastest library corner, ff_n40C_1v95, which means the library's timing,
and every timing check in the repository with it, stops 30 mV short of the
top of the frozen box. The box is 1.62, 1.80 and 1.95 V now and is no longer
ten percent either side of 1.80.

`preregister.py` P10 still reads the frozen box and passes on it, which is
right: the frozen file did say 1.98. The amended box is held by A06 instead,
inside the library's corners, 1.60 to 1.95 V.

## What the gate checks now

`preregister.py --amendment` runs nine checks:

    A01  records the frozen preregistration by its hash
    A02  says it is not a preregistration, no die read when written
    A03  every item's quote is still what the frozen file says
    A04  every item dated between the freeze and silicon, with who,
         what, why and what it gives up
    A05  two primaries at 0.025 and 0.05, six of six under the first
         and over the frozen family's first
    A06  the amended voltages inside the library's corners
    A07  the M4 method complete, and the same shuffles and seed as the
         recorded implementation
    A08  the order and the reading are what the bench firmware does
    A09  the secondary's halves are the rings the hook puts below and
         above Arm A

Each has a planted fault in `--selftest`, made on a copy of the real files,
and each fault trips its own check and no other. A05 works its fractions
without importing `primary_tests.py`, and A09 reads the hook rather than
taking the amendment's word for which ring is where. Two lines in the gate,
and `primary_tests.py` went into the runbook's covers list for B07.

## Mistakes on the way

Four, kept.

My first draft said the firmware had read in random order since September.
It was 24 July, `8f5509b`, by its own history.

The first draft of the secondary's reason said a vertical gradient adds to
Arm C's spread and not to Arm A's. It adds to both, more to Arm C's, because
Arm A spans 98 um of the same direction.

I nearly wrote the secondary's halves as rings 0 to 7 and 8 to 15. The hook
says otherwise, and that is what A09 is there for now.

The first comment at the top of the amendment counted three gaps after the
audit. There were four on 23 September and one today.

## Not settled

Whether the secondary gets an interval, and which. How many shuffles and
which seed for M2's p-value, now that M2 is secondary. E.3, the collector the
protocol says has to read in this order, is still not written;
`measure_puf.py` already reads that way and it is not that collector.

The paper's section on the preregistration describes the frozen file. It
takes this up in Phase C, with the same sentence about not citing it as one.
