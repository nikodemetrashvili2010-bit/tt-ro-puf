# The last pulse before a stop, through every selector path

26 October 2026. Until today the boundary sweep had run through one of the
release build's 48 selector paths, B13, chosen because it has the slowest
rise. The other 47 carried every edge in the steady sweep and had never had a
ring stopped in front of them.

`SIGNOFF.md` had that row down as "before final trust", and it was the last
selector item on the open list.

All 48 are screened now at ff, four phases each, and the one path that came
out worse than B13 is swept down to 0.2 ps. Every phase on every path leaves
the flop on a rail and the count moves by one edge at most.

B13 was not the worst path. B00 is.

## Why a screen and not 47 sweeps

B13's coarse sweep is 38 phases. Here a deck takes 29 to 40 s, 33 as a rule.
Two at a time take three times as long. So 38 phases on 47 paths would have
been about 16 hours.

What makes it cheaper is in the decks. The first eighty lines of all 48 are
the same bytes: the same macro ring, the same enable, the same tap. Only the
chain after the tap changes.

So at a given enable phase every deck hands its chain the same last pulse,
near enough, and the screen can hold the phases fixed and move the path.

The four phases are on B13's own grid. The enable falls at 30.080, 30.090,
30.100 and 30.110 ns, and the last high at the tap is 32, 54, 68 and 82 ps.

B13's step is between 75 and 77 ps on its 1 ps sweep, so it should lose the
first three and keep the fourth, and it does. Its last two phases are also
rows of the archived 5 ps sweep, and they come back field for field.

"Near enough" turned out to need saying. I first wrote the check on the tap
with a 1 ps tolerance, on the reasoning that the ring is the same circuit in
every deck, and the first six paths came back 1.66 ps apart at the narrowest
phase.

The chain's first cell loads the tap, an a221o_2 on one pin here and an
a22o_2 on another there, and the solver picks its steps around a different
circuit each time. So one phase gives a pulse a picosecond or more wider or
narrower from path to path.

Across all 48 it spans 3.90 ps at the 32 ps phase and 1.4 ps at most at the
other three. The check allows 5 ps, a third of the 14 ps between the screened
widths.

## What came back

    arrived  paths  step at the tap    which
    0111      28    between 32 and 54  A00, A02, A03, A05 to A15, B07, B11,
                                       C01 to C03, C06, C07, C09 to C15
    0011       9    between 54 and 68  A01, A04, B04, B08, B15, C00, C04,
                                       C05, C08
    0001      10    between 68 and 82  B01, B02, B03, B05, B06, B09, B10,
                                       B12, B13, B14
    0000       1    above 82           B00

The arrived column reads the four phases in order, 1 where the last pulse
reached the flop.

No path passes the 32 ps pulse.

Each path's own widths sit inside the spread above, so a step written
"between 54 and 68" is between about 53 and 69 on some of them.
`boundary_screen_ff.csv` has every path's own four.

192 phases, every one settled to 0.000 or 1.950 V. Between adjacent phases
the count moves by one edge or not at all, and on no path does a wider pulse
get lost after a narrower one arrived.

The narrowest high that reached `sel_ro` on this grid is 101 ps, on C04 at the
68 ps phase. The widest first arrival is 245 ps, on B08.

All eleven paths with a step above 68 ps are Arm B's. Every Arm B path leaves
the selector through an o21ba_2 into the A2 pin of the last a211o_2, and no
Arm A or Arm C path goes that way: Arm A's leave through an o21a_2 into B1,
Arm C's through an and3_2 into C1, and none of those 32 needs more than 68.

Rise delay does not order it. C06 rises in 316 ps and passes the 54 ps pulse,
B12 rises in 282 and needs more than 68.

Five of Arm B's sixteen stay at 68 or under, B04, B07, B08, B11 and B15, so
the tail is not the whole story either. Four phases are not enough to say
which cell does it, and I have not tried.

## B00, the path that needed more

B00 was the twelfth path through and the first to lose all four pulses, the
82 ps one included. Its step is above B13's and the screen could not say
where, so I stopped the queue and gave B00 the grids B13 had below its coarse
one:

    grid     phases  step at the tap    narrowest pulse at sel_ro
    5 ps       13    82 to 89 ps        186 ps
    1 ps        6    83 to 85 ps        143 ps
    0.2 ps      6    about 84 ps         69 ps

B13 on the same grids: 75 to 82, 75 to 77 and about 76 ps, with 202, 128 and
80 at `sel_ro`. So B00 needs a pulse about 8 ps wider than B13's before the
flop sees it. Every one of its 25 phases resolves the same way, to a rail,
with the count moving by one edge.

The 5 ps grid is B13's, 30.100 to 30.160 ns, so the two sweeps read row
against row: the same pulse at the tap within a picosecond or two, a
different chain.

69 ps is under the 77.5 ps the library gives `dfrtp_2` at ff_n40C_1v95, and
the flop resolved it as it resolved B13's 80.

`SIGNOFF.md` has said since 17 September that the 77.5 was never a margin,
being the figure at a 10 ps clock slew, and since B13's fine sweeps that the
width right at a threshold belongs to the grid. B00 says it again from a
second path. A finer grid would find a narrower pulse still, and it would
still cost one count whichever way it went.

That B13 was the worst was the one thing I had wrong going in. It was chosen
as the slowest rise, 349 ps, on the reasoning that the slowest chain would
give up first. B00 rises in 294 ps through four cells and gives up later than
B13 does through five. I should have seen it coming. B13's own write-up had
already said the path counts as well as the ring, after B15 gave up near
100 ps and B00 near 111 on the two-arm baseline, and the screen is that
sentence measured. That B00 was a different tree on a different build, so the
name matching is mostly chance.

## The setup, and how I know it is the archive's

ngspice 42 from Ubuntu's archive and a `sky130A` tree made the way
`docs/phaseG_spice_rerun.md` says, fd_pr at `403964d` and fd_sc_hd at
`5a42fd0`, in a fresh container. `gen_boundary_sweep.py --build
dualarm/build_armc --osc B13 --corner ff` wrote all 38 decks of `bnd3/B13`
again byte for byte, and phase 24 run again reduced to the archive's own
waveform, md5 `72826716`, with a log the same apart from its dates.

The first time I ran that phase it came back in 0.07 s and wrote nothing.
`PDK_ROOT` lives in the shell, and the shell was a fresh one. The reducer
then said there were no waveforms to reduce, which is how I saw it.

Everything ran one deck at a time, 217 decks, about two hours of machine
time with B00's 25 in the middle of the screen. Pausing for B00 cut B03's
second deck off halfway, and the queue skips a deck only when its log ends
the way a finished ngspice run ends, so it ran that one again from the
start.

## What checks it

`sim/spice/gono/boundary_screen.py` reads the screen through
`analyze_boundary_sweep.py`'s own phase reader and adds six checks over the
whole set:

    S01  every path has its four phases, each with a steady delay measured
    S02  every phase leaves the flop on a rail
    S03  no two adjacent phases differ by more than one edge
    S04  a pulse that reaches the flop is never followed by a wider one
         that does not, and the count never steps down
    S05  B13's phases at 30.100 and 30.110 ns are the archived 5 ps rows
    S06  the last pulse at the tap agrees across the paths at each phase

Its selftest builds three synthetic paths with the analyser's own synthetic
ring and plants six faults, each tripping its one check.

Two of them tripped two checks the first time. A flop hung at mid-rail on the
first phase also counted as a crossing, so the count stepped down after it
and S04 fired as well; on the last phase it trips S02 alone. And a pulse lost
by giving the gates a 1 s minimum width lost every pulse, the steady train
too, so S01 and S03 fired with S04. A 90 ps minimum loses only the 82 ps
pulse.

A second reader written for the purpose, with its own parser and its own
crossings and nothing imported from the repository, agrees with the screen on
all 48 paths: the four widths at the tap, which arrived, the narrowest at
`sel_ro`, the flop's edges and where it ends.

It agrees with the analyser on all 25 of B00's phases too, and on B13's 1 and
0.2 ps sweeps as a control.

The gate reads all of it again from the reduced waveforms, the screen's csv
and B00's three, and diffs each against the committed copy. Nine lines.

## What it does not settle

The screen places each step to within the gap between two of its pulses and
says nothing about the pulse that sits exactly on it. B13's grids showed that
number shrinking with every finer grid, and B00's do the same, so it belongs
to the grid and is not a floor.

It is ff only. B13 alone has tt and ss, and B00, the path with the highest
step at ff, has neither.

On the 18th B13's step sat at 6.6 to 7.0 percent of the period at tt against
6.8 at ff, and at 7.5 to 7.7 at ss, which makes ff a fair place to rank the
paths. A rank is still not a sweep.
