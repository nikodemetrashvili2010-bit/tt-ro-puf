# B00 at tt and ss, and where Arm B loses the last pulse

27 October 2026. Two things were left over from yesterday's screen. B00
came out as the path that needs the widest last pulse at ff, and only B13
had ever been swept at tt and ss. And all eleven paths with a step above
68 ps were Arm B's, with nothing to say which cell does it.

B00 has both corners now, swept the way B13 was.

For the second I put a probe on every net of eight Arm B paths. On the
four that need the wider pulse it dies on or just after the first net,
which is heavy on all four, and not at the cell I suspected. Swapping one
load between two decks swaps their verdicts. Across all 48 paths a heavy
net early in the chain turns out to be needed for a step above 68 ps,
though it is not enough on its own.

Nothing here changes the chip. A swallowed last pulse costs one count, the
one-count error the settle handshake already tolerates.

## B00 at tt and ss

Same sweeps as B13's, from `gen_boundary_sweep.py` with B13's base and
step: a coarse sweep from 30.000 ns in 50 ps steps, 38 phases at tt and 76
at ss, then 13 phases 5 ps apart from the last coarse phase that lost the
pulse.

At tt the coarse sweep loses one phase, 108 ps at the tap, the same one B13
loses. On the 5 ps grid B00 loses everything up to 142 ps and keeps 148,
which reaches `sel_ro` 290 ps wide. B13 on the same grid gave up at 115 and
kept 122, at 231 ps.

At ss the coarse sweep loses three phases, 171, 230 and 294 ps at the tap,
where B13 loses the first two and keeps 295. So B00's 5 ps grid starts at
33.250 ns, 50 ps later than B13's. On it B00 loses everything up to 317 ps
and keeps 323, which reaches `sel_ro` 483 ps wide. B13 gave up at 258 and
kept 264, at 507 ps.

Against the period, which is the same ring in every deck, 1122 ps at ff,
1752.5 at tt and 3435.4 at ss:

    corner  B13 step       share     B00 step       share
    ff      75 to 77 ps    6.7-6.9   83 to 85 ps    7.4-7.6
    tt      115 to 122     6.6-7.0   142 to 148     8.1-8.4
    ss      258 to 264     7.5-7.7   317 to 323     9.2-9.4

ff is the 1 ps grid, tt and ss the 5 ps ones. The shares are percent.

B13 sits at about the same share at ff and tt and a little higher at ss,
which is what the 18th found and what made ff a fair place to rank the
paths. B00's climbs from corner to corner. It needs about 8 ps more than
B13 at ff, 20 to 33 more at tt and 53 to 65 more at ss.

So the ff rank holds at the other corners, for the two paths that have
them, but the gap between two paths is not a fixed share of the period. It
grows as the corner slows. A heavy first net would do that if it costs
more where the cells drive less. It fits; I have not shown it.

Every one of B00's 140 tt and ss phases leaves the flop on a rail, and the
count moves by one edge at most. The first pulse through on each 5 ps
grid, 290 ps at tt and 483 at ss, is over the library's 169.8 and 353.8
for `dfrtp_2` at those corners, and like B13's it belongs to the grid.

## Where the pulse gives out

The screen's table had a pattern in it. Four pairs of Arm B paths run
through the same cell types on the same pins except at one cell, the
o21ba_2, which one path of the pair enters on A1 and the other on A2:

    A2 path  arrived  A1 path  arrived
    B00      0000     B04      0011
    B03      0001     B07      0111
    B12      0001     B08      0011
    B15      0011     B11      0111

In all four the A2 path needs a wider pulse, one or two screened widths
more. I went in sure it was the o21ba_2 and spent part of the morning in
its netlist, working out why A2 would be the slower pin.

`bnd_nodes.py` was meant to confirm it. It takes the deck the screen ran
and rewrites three lines, the `.save`, the `.tran` and the `wrdata`, so
every net of the chain is written out over a 9 ns window around the stop.
The circuit lines are not touched. Each pair ran at a phase where the A2
path loses the pulse and the A1 path keeps it: 68 ps for three pairs, 54
for B15 and B11, the only phase those two differ on.

    path  tap    first net        second net      the last pulse
    B00   68 ps  _221_ 27.09 fF   _222_ 1.46 fF   lost at the first net
    B03   69     _221_ 27.09      _222_ 1.46      33 ps there, lost at
                                                  the second
    B12   69     _219_ 17.98      _222_ 1.46      64 ps there, lost at
                                                  the second
    B15   55     _219_ 17.98      _222_ 1.46      28 ps there, lost at
                                                  the second
    B04   68     _216_ 11.95      _217_ 2.56      215 ps at sel_ro
    B07   68     _216_ 11.95      _217_ 2.56      239
    B08   68     _214_ 4.01       _217_ 2.56      245
    B11   54     _214_ 4.01       _217_ 2.56      231

On all four A2 paths the pulse is gone before it reaches the o21ba_2. So
much for the netlist.

What the four have in common is the first net. B00 and B03 start on
`_221_`, B12 and B15 on `_219_`, and the A1 paths on `_216_` and `_214_`.
The o21ba_2's A2 input sits behind the first two and its A1 input behind
the other two, so the pin I was looking at was only a label for which first
net a path has.

Where the pulse does not cross, `bnd_nodes.py` also says how high the net
got. B00's `_221_` reaches 0.90 V of 1.95 and comes back down. On the other
three the pulse gets across the heavy net, narrow, and dies at the next
one: `_222_` reaches 0.12 V on B03, 0.44 on B12 and next to nothing on
B15. B12 has 64 ps on `_219_` and loses it. B04 turns 86 ps on `_216_` into
99 on the net after. A width at half the supply is not the whole story on a
net that heavy, and I did not look at the edges.

Each of these nets has one driver and one load in the SPEF, so what makes
one heavy is its route. `_221_` is 198 um of wire, `_219_` 108, `_216_` 88
and `_214_` 21.

## The load across all 48

The chains run through 37 distinct nets. Six carry more than 12 fF, from
17.68 to 27.09, and the next lighter is `_216_` at 11.95, so "heavy" has a
gap to sit in:

    step at the tap   paths   a heavy net in the first two
    above 68           11     11
    54 to 68            9      4  B15, C00, C04, C05
    under 54           28      1  C06, on its second net

Every path that needs more than 68 ps has a heavy net among its first two.
So it is necessary, and it is not sufficient: four paths have one and stay
under 68, and C06 has one second and passes 54.

Some of what else counts shows in the screen. On each of the four first
nets above, the path that enters the a221o_2 on B2 needs one width less
than the one that enters on A1: B03 against B00, B07 against B04, B11
against B08, B15 against B12. So a pin matters after all, just not the one
I was looking at. And C04 starts on a heavier net than B12, through the
same pin of the same cell type, and needs less. At 68 ps B12's pulse dies
in the a22o_2 after its heavy net and C04's gets through the a21o_2 after
its own, so what follows the heavy net counts too.

Separating those would take more what-ifs than the one below, and I stopped
at one.

## Swapping one load

The probes show where the pulse dies, not why. The cleanest test I could
think of was to move the load. Two what-if decks, each a probe deck with
one number changed, the capacitor on the first net: B00 gets B04's
11.95 fF in place of its own 27.09, and B04 gets B00's.

    deck                  first net  delay to it  the last pulse
    B00 as built          27.09 fF   124 ps       lost at the first net,
                                                  peak 0.90 V
    B00 with B04's load   11.95       87          214 ps at sel_ro
    B04 as built          11.95       87          215 ps at sel_ro
    B04 with B00's load   27.09      124          lost at the first net,
                                                  peak 0.92 V

The verdicts swap, and the delay to the first net goes with the load to the
picosecond. Within this pair the load decides it and the o21ba_2's pin does
not.

These two decks are not the chip. Each carries a comment saying so, and
they live in their own folder with their own csv. They say what the model
does with one capacitor moved, and nothing about whether a router could have
made `_221_` shorter. The chip is taped out either way.

## The setup, and how I know the probes are the screen's runs

The same as yesterday: ngspice 42 from Ubuntu's archive and a `sky130A` tree
with fd_pr at `403964d` and fd_sc_hd at `5a42fd0`. As a control,
`gen_boundary_sweep.py` wrote all 140 of B13's tt and ss decks again byte
for byte.

A probe changes what is written out, and its window starts 6 ns before the
stop where the screen's output starts at zero. The largest step stays 1 ps,
so the solver should take the same steps.

To check, I took every row the screen kept inside each probe's window and
looked for it in the probe's full output: 1560 rows over the eight paths,
every one there at the same time with the same tap, `sel_ro` and q, to the
last printed digit. The full outputs are 1.7 MB each and are not kept. The
reduced copies share 632 of those rows, and N05 below holds them to it on
every read.

152 decks in all, one at a time, 34 to 45 s each. One took 92 s, because I
ran the gate beside it.

## What checks it

`sim/spice/gono/bnd_nodes.py` reads the probes and checks:

    N01  every deck has a waveform for every net of its chain
    N02  every net has a steady rise delay, in order down the chain
    N03  a pulse lost at one net is not found again further down
    N04  sel_ro's verdict is the screen's for the same deck
    N05  the tap, sel_ro and q are the screen's on every row both kept

N05 fails a deck with no row in common rather than passing it. The what-if
decks are read with `--no-screen`, which reports N04 and N05 as not run,
not as passed.

The selftest builds a synthetic pair, B00 losing its pulse at the third
stage and B04 keeping it, and plants six faults that trip one check each,
two of them for N05. It also checks that `--make` rewrites its three lines
and refuses a deck where one of them turns up twice, and that `--reduce`
keeps a faithful copy and refuses a lossy one.

Two second readers, written for this with their own parsers and nothing
from the repository. One agrees with the analyser on all 140 of B00's
phases, and on B13's tt and ss sweeps as a control. The other agrees with
`bnd_nodes.py` on the width or the peak of all 40 probed nets, the what-ifs
included.

The gate reads all of it again from the reduced waveforms and diffs it
against the committed csvs, thirteen lines.

## What I got wrong on the way

- the o21ba_2, as above. The probes were meant to confirm it
- the probe tool's docstring said the A2 paths' first nets were the two
  heaviest in the selector. 27.09 is, 17.98 is fourth, with `_213_` and
  `_198_` between. It also said one screened width more for every pair,
  and two of the four are two. Both were written from memory of the screen,
  and I caught them listing the loads
- the reducer took its level from the waveform's maximum. A real rail
  overshoots, B00's tap reaches 2.05 V on a 1.95 V supply in the full
  output, so the level sat above half the supply and `--reduce` refused
  B00's copy because it read differently. The selftest had missed it
  because its edges were steps with nothing between rows to cross. They
  ramp through three samples now, and the old rule fails the test
- the synthetic B00 did not lose its pulse at first. Each synthetic stage
  lengthens a high by 40 ps, so the pulse grew all the way down. Its third
  stage wants 160 ps now
- the bump a dropped synthetic pulse leaves was flat, so a reduction that
  threw its rows away still read the same peak, and the test that
  `--reduce` refuses a lossy copy had nothing to refuse. It slopes now
- the what-if decks' comment was one line of 99 columns. I wrapped it and
  ran both decks again rather than edit a deck after it had run. Same
  numbers
- a read without the screen printed the same PASS line as one with it,
  which claimed N04 had passed when it had not run

## What it does not settle

A heavy net early in the chain is needed for a step above 68 ps and is not
enough. The pin the pulse enters on and the cell after the heavy net count
as well, and nothing here separates them.

The what-if moves a capacitor in a deck. It is not a layout.

Only B00 and B13 have tt and ss. The other 46 paths are ff only, and so are
the probes.

The 5 ps grids place B00's steps to within 5 ps and say nothing about a
pulse right on one. At ff every finer grid let a narrower pulse through, on
both paths, and I would expect the same at tt and ss.
