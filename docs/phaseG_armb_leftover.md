# What is left of Arm B, on the release routes

29 October 2026. Section 8.2 of the paper asks four things of Arm B's
sixteen instances: whether the little that separates them is the routes,
whether anything in the design database predicts it, whether it keeps its
sign across corners, and what it is worth in bits. Until today all four had
been asked of the baseline's routes only. Run 83 drew every route again, the
sixteen were run on those on 22 September, and only the first question got
read off the new logs.

`matched_arm.py --build release` asks all four now. Three came back the way
they did on the baseline. The fourth threw up something the baseline never
had, and running it down took most of the day.

## Section 8.2, on run 83's routes

    corner  spread    above the no-route   entropy of 8  a reader calls
                      reference
    tt      0.00326%  10 of 16             7.9996        4.0301
    ss      0.00014%   1 of 16             8.0000        4.0009
    ff      0.00187%  12 of 16             7.9998        4.0142

Stability is absent, as before. The eight pairs keep their sign 4, 2 and 4
times out of 8 between the three corner pairs, which is a coin, and no
per-instance correlation between corners survives Holm. Arm A on the same
die, with the two-feature corrector Section 6 uses, takes out 77.9% of its
spread. The baseline's figure was 89.5, and nobody had worked out the
release one before; `matched_arm.py` does it from the release SPEF now.

Predictability is where it went odd. 21 corrector cells, leave-one-out,
seven correctors at three corners, and one is positive: the enable route's
capacitance at tt, +34.3%. The raw correlation behind it is r = -0.805, p =
0.0002, and it survives Holm over both routes and all three corners at
0.0010. Heavier enable route, slower ring, about 3.7 ppm a fF. Same sign at
ff, r = -0.443, and not at ss. On the baseline's routes the same comparison
gave r = -0.35, p = 0.18.

That should not happen. An instance's enable comes out of an `and3_2`,
along its route, into the macro's input delay buffer and from there to one
input of the NAND. Once the ring is running every one of those nodes sits at
the supply. A route on a node that never moves has nothing to pull with.

## Taking it apart

All of these at tt, all in `sim/spice/gono/armb3/tol/`, and all read by
`armb_residual.py`.

First the archived deck again, with one line added to write the waveforms
(`rt3`). Its log came back the archive's to the digit, all 150 values, so
the environment is the one that made `armb3/`.

Then the windows. The correlation is there from the second rise to the
44th: r = -0.80 at the deck's own window, rises 5 to 25, and -0.83 from 25
to 40. Period by period, each instance keeps its own offset. The sixteen
means sit 10.6 ppm apart (standard deviation) where single periods scatter
4.6 ppm about them. So it is not the start, it is there every cycle.

Then the solver ten times tighter, `reltol` 1e-4 (`rt4`), and nothing else
changed. The correlation goes: r = -0.059. The sixteen still spread, 27.1
ppm against 32.6, but in another order altogether, r = +0.22 between the
two runs, and now 13 of the 16 read above the reference. Every ring moves,
the reference by +64.5 ppm and the sixteen by +53.8 to +88.6.

Then a null. The same deck with the sixteen replaced by sixteen copies of
instance 0, routes and all, each enabled 37 ps after the one before
(`null3`, `null4`). One circuit sixteen times. They spread 4.3 ppm at the
archived tolerance and 1.8 at 1e-4, against 32.6 and 27.1 for the real
sixteen. So the solver puts one circuit in the same place wherever it
starts it, and puts different circuits in different places, by tens of ppm,
in an order that changes when the tolerance does.

Last, one ring per deck, nothing else in it to share the solver's steps
with, at three settings each tighter than the last in tolerance and in the
largest step allowed (`alone/`). Instance 8 has the heaviest output route,
45.4 fF, and instance 14 the heaviest enable route, 8.8 fF.

    setting  reltol  step cap   against the reference run alone
                                k08          k14
    s1       1e-5    0.25 ps    -2.33 ppm    -0.76 ppm
    s2       1e-6    0.1 ps     -0.034       -0.020
    s3       1e-7    0.05 ps    -0.006

k02 and k11, light routes both, sat at -0.61 and -0.59 at s1. The
reference itself moved +6.9 ppm from s1 to s2 and another 0.9 to s3, so
even the absolute frequency is settling at about the third setting. It
reads 570.730 MHz there against 570.636 in the archived deck, 164 ppm
apart. No conclusion in the repository rests on the fourth digit of an
absolute frequency, but that is how far the default tolerance sits from
the answer.

That is the answer. The routes move a ring by a few hundredths of a ppm at
most, on the side a passive load should push it. Everything else in the
shared deck, the 33 ppm, the instances above the reference and the enable
route's correlation, is the solver.

## What changes

The spreads Section 8.1 quotes for both builds, 0.0025% and 0.0033% at tt
and the rest, come out of eighteen-ring decks at ngspice's default
tolerance. At tt on the release build that is shown to be what such a deck
does to sixteen slightly different circuits; the other corners and the
baseline are the same kind of deck and were not taken apart. They were
always called bounds, and they are, but the bound is the solver and not
the routes. The routes' own share at tt is under 0.04 ppm, 0.000004%.

Section 8.2's direction test leaned on instances reading faster than a
reference with no route, which a passive route cannot cause. They did read
faster, and at tt on the release build it was the solver. The four run
alone sit just under the reference, closer the tighter the solver, as a
passive route should. The conclusion, that the leftover is not the routes,
holds. At tt on the release build it is shown directly now instead of
inferred from a reading that was noise.

The release routes' enable correlation is the solver's as well. Section 8.2
gets a paragraph saying so, and so does Section 10, where the floor under
the per-instance runs was already put down to the solver without anything
run to show it.

The bits do not move. Taken as it stands the leftover gives a reader 4.03
of 8; with the routes' real effect in place of it the pairs are 0.034 ppm
apart at most and a reader gets 4.00.

Anything else in the repository that rests on a few tens of ppm between
different circuits in one deck at the default tolerance needs the same
look. Arm A's and Arm C's pair gaps are 0.2 to 3%, two thousand ppm and up.
The supply confound is 348 ppm. The clock pull of 28 October ran at 1e-4
and compares one circuit with itself. The pair drift envelopes
`pairing_policy.py` reads off the corner logs run from 0.004% to 0.282%,
and the bottom of that, 40 ppm, is in the range where this matters. Those
logs are sixteen-ring lumped decks at a 5 ps step, and against the one-ring
lumped decks at 1 ps their rings sit 0.18% slower with 60 ppm of scatter
about that, on both builds. How much of the scatter survives in the ratio
of two corners I do not know. Not checked yet. That goes on the list.

## The setup

ngspice 42, the same container and `sky130A` tree as the boundary runs.
`armb_residual.py make` writes every deck from `armb3/armb_instances.spice`,
`check` holds the archive to it, and both are in the gate with the report
and its selftest. The shared decks took 13 to 15 minutes each, one at a
time. Alone, a deck took 1.5 minutes at s1, about 3 at s2 and 5 to 7 at s3.

The waveforms are 46 MB a shared run and do not go in the repository. Each
run keeps its deck, its log and its rising crossings, taken the way the
deck's own meas lines take them, and `check` holds every crossing file to
its log's own trig and targ times, within 0.005 ps on all 18 rings.

`verify_predictability.py` reads the same logs with its own code for the
paper's release figures, 11 checks, 149 in all.

## Mistakes

- I wrote in August that a passive route can only slow a ring and took
  instances above the reference as proof the leftover is not the routes.
  The conclusion was right and the proof was solver noise.
- The first runs at s1, alone, put every instance 0.6 to 2.3 ppm under the
  reference, heaviest route slowest, and I took that for the routes' real
  effect and was about to run all sixteen at s1 as the answer. s2 took the
  heaviest from 2.33 to 0.034. s1 was the solver too, just less of it.
- A one-ring deck run beside the boundary screen made both about three
  times slower. The screen's decks took 69 to 213 s instead of about 30.
- The background job holding the boundary queue hit its two-hour limit at
  01:47 and nothing restarted it until 07:50. About six hours of machine
  time.

## Not done

- The other fourteen instances alone at s2 or s3. Two of the heaviest
  routes are, and the effect falls with the load.
- ss and ff. The shared decks at those corners are the same solver at the
  same tolerance, and I expect the same answer, but nothing has run there.
- `pairing_policy.py`'s drift figures, above.
