# The front page, and the chip on a bench

20 September. Two jobs. The README still described a two-arm chip and quoted
the baseline's 7.91 as if it were the chip's, and Matt Venn opens the repo on
the 30th. Then more simulation, this time of the things a nominal deck leaves
out: heat, current in the wires, the supply sagging, how close wires sit,
whether anything can short. And an answer to whether the chip is actually good.

Everything here is the release build, run 83 on `8f8939a`, in
`dualarm/build_armc/`. Long numbers are in the script outputs; this note says
what they mean.

## The README

What was wrong with it, read against the tree:

- two arms, 32 oscillators, and a status section for a two-arm design
- the block diagram: two arms, "select 1 of 32", a fixed window of 1000 cycles,
  one output pin. Out of date on every box
- the headline, 0.46 bits held and 7.91 of 8 called, which is the two-arm
  baseline's. The 18th showed the release build's Arm A bits are different
- "only three of the 32 paths were swept at the stopping boundary" and the 80
  ps against 77.5 ps margin, both superseded (48 paths now; the 17th found the
  77.5 ps is not a margin at any realistic slew)
- the three runs with no logs: reproduced on the 17th, never said
- a render of the two-arm layout, and a repository map with no `chip/` and no
  `extraction/`

It now describes three arms, leads with the release build's number, keeps the
baseline's as the baseline, and says which section was measured on which build.

The two figures that were wrong are replaced, not edited over:
`docs/figures/chip_block_3arm.png` from `make_block_diagram.py --arms 3`, and
`docs/figures/floorplan_3arm.png`, a map of where the three arms sit, drawn
from the release DEF by `make_floorplan.py`. The two-arm figure stays the
paper's until the paper is brought across, so nothing the paper draws changed
today.

## The release build's own number

To put a three-arm number where 7.91 was, the release build needed what the
baseline had: the full RC network, not only the lumped decks. So the sixteen
Arm A rings went through `gen_rc_decks.py` on run 83's SPEF, 32 decks.

Before trusting a new container I re-ran ring 7 of the baseline in it. 571.82
MHz lumped and 567.91 with the full network, both exactly what
`rc_validation.csv` recorded in July.

    Arm A, release build, tt           lumped      full RC
    spread, peak to peak               5.75 %      5.88 %
    every ring slower under RC         -0.67 to -1.67 %
    rank correlation, the two models   0.965
    bits                               11100000    11100000

Two pairs come closer under the fuller model, 2/3 to 0.212% and 8/9 to 0.316%
(2.4 and 3.6 mismatch standard deviations), so the full network is the honest
one to score. Scored the way the baseline was:

    held across dies     0.07 bits of 8   (0.02 to 0.22 across the interval)
    called by a reader   7.99 of 8        (7.97 to 8.00)
    fixed bits           7 of 8 under 0.01 bits

Against 0.46 and 7.91 on the baseline. The chip being made is more predictable
than the one the method was worked out on, not less, and ordering its rings by
extracted capacitance alone still calls all eight.

## Arm C, simulated for the first time

`gen_rc_decks.py` knew only Arm A's instance path. Arm C's is
`g_armc[i].u_roc`, and there is a trap in it: `ro_macro.v` numbers its
inverters 1 to 30 by the node each one drives, `ro_armc.v` numbers them 0 to 29
by the node each one reads. A deck built on the Arm A mapping would have wired
every Arm C resistor one inverter off.

`--arm C` carries the offset, the default path still writes the old decks byte
for byte (18 of 18 on each build), and a walk of every RC deck's resistor graph
finds each of the 31 nets joining its own driver to its own load, 32 decks of
32.

    Arm C, release build, tt           lumped      full RC
    range, MHz                         570.9-583.4 566.9-579.4
    spread, peak to peak               2.17 %      2.19 %
    bits                               11010110    11010110
    closest pair                       0.20 %      0.321 %, 3.7 sigma

The standard deviation of the sixteen is 0.36 of Arm A's in the same build, in
MHz, the way M4 is written. Hand placement takes out about two thirds of the
spread.

It takes out none of the predictability: the arm holds 0.00 bits of 8 under the
full network and a reader calls 8.00. Under the lumped model the closest pair
is nearer, 2.3 sigma, and the arm holds 0.09 bits.

The lumped ss and ff decks put Arm A at `11100000` and Arm C at `11010110` at
all three corners.

## Heat

Each ring deck got its supply current measured. The numbers are the six rings
run, three of each arm:

    corner   one ring       with the selector and the first flop
    ss       0.094 mW
    tt       0.228 mW
    ff       0.405 mW       0.688 mW

The smallest footprint any ring has is Arm C's, 120 um2, because the template
packs it. A uniform source that size on silicon warms by 0.4732 P / (k a)
averaged over itself.

With k taken at 100 W/(m K), what silicon has at about 400 K rather than the
148 it has cold, one ring at the fast corner warms its own patch by 0.175 K and
gets there in 1.4 us of a 41 us window.

The whole measurement at 0.688 mW warms the die by 0.069 K through an assumed
100 K/W, which is higher than a QFN on a small board should be, on purpose.

The worst temperature coefficient anywhere in the -40 to 125 C box is 0.054%
per kelvin, at 1.62 V. So a running ring reads 0.013% off its cold self. Both
rings of a pair do that.

What does not cancel is the part that differs inside a pair, the footprints and
a 5.3% power spread between rings, and it comes to 0.0015% at most, forty times
under the mismatch scale.

Heat cannot short anything here either. The ring wires carry tens of microamps
and the Joule heat in one is well under a microwatt. What turns current into a
short or an open over years is electromigration, which is the next section.

## Current in the wires

The limits are the ones the sky130 tech LEF declares, at Tj = 90 C,
`sky130_fd_sc_hd__nom.tlef` from the cell library repository at the commit the
PDK tree uses: met1 2.8 mA/um DC and 6.1 RMS, met4 6.8 DC, a via1 cut 0.29 mA.

The three heaviest ring wires in the release SPEF got a 0 V source between
their driver and the wire and were run at ff:

    wire                     RMS       peak      as a 0.14 um wire
    Arm A ring 5, node 15    64.2 uA   364 uA    0.46 mA/um RMS
    Arm A ring 15, node 30   50.9 uA   328 uA    0.36 mA/um RMS
    Arm C ring 6, node 30    55.9 uA   357 uA    0.40 mA/um RMS

Their average is zero to a tenth of a microamp, which is what a wire that
charges and discharges the same capacitor has to do. At minimum width the worst
is 13 times under the RMS limit.

The rails and vias come out of the grid solve below. The worst met1 rail
segment carries 62.6 uA, 0.13 mA/um against 2.8. The worst via stack carries
72.8 uA over seven via1 cuts, about 10 uA a cut against 290. The stripes are at
0.04 mA/um against 6.8.

One number looked worse than it is. The selector deck's supply current has an
RMS of 2.04 mA against an average of 0.35, because ngspice's ideal source hands
every edge its current instantly with no decap in between. Even that whole RMS
on one 0.48 um rail would be 4.3 mA/um, under 6.1.

## Spacing, which is what "safe distance" means on a die

The flow's Magic DRC and KLayout DRC both report zero on run 83, and LVS
reports zero, which is what would catch two nets touching. I checked the
spacing a second way because it was asked for directly:
`real_world/space_width.py` loads the release GDS in KLayout's Python module
and runs width and same-layer spacing on every routing layer.

    layer   width fails   space fails   smallest gap drawn
    li1     0             0             0.170 um, the rule
    met1    0             0             0.140 um, the rule
    met2    0             0             0.150 um
    met3    0             0             0.335 um
    met4    0             0             0.350 um

Before believing a column of zeros I planted two met1 bars 0.10 um apart and
one 0.10 um wide in a copy of the GDS. It reported the gap and the width.

The first version of that script reported a smallest li1 gap of 0.000 um, which
would have been a short. It was KLayout returning zero-length edge pairs for
corner-to-corner cases, two corners 0.255 um apart with `distance()` reading 0.
The script now measures the gap from the edge geometry itself.

## The supply, with a ring running

`real_world.py` builds the power grid out of the DEF's SPECIALNETS: the 41 met1
rails of each net at 0.48 um, the six met4 stripes of each at 2.4 um, and the
via stack at every crossing, 1x7, 1x6 and 1x6 cuts.

It hangs a ring's measured current on its own 32 cells, each on the rail its
orientation puts its supply pin on, and solves the network. Two feeds bracket
what the Tiny Tapeout grid does above the stripes: only the stripe ends held at
the supply, the worst it could do, or the whole stripe held, the best.

    stripes fed at their ends    VPWR drop plus VGND rise   frequency
    Arm A                        0.280 to 0.578 mV          0.030 to 0.061 %
    Arm C                        0.275 to 0.530 mV          0.029 to 0.056 %
    Arm B, on its stripe pins    0.143 to 0.256 mV          0.015 to 0.027 %

With the supply pushing 105.88% per volt, a pair's two rings differ by up to
0.026% (Arm A) and 0.024% (Arm C). That is at most 9% of that pair's own gap in
Arm A and 6% in Arm C under the worst feed, 8% and 7% under the best, and no
bit changes under either.

It is also in the design database, so it moves a reader's prediction as much as
the chip.

Arm B's pairs sit side by side in one row, each macro's power pins on its own
stripe pair, so the grid treats both halves of a pair alike and their
difference is 0.0006%. That rests on the Tiny Tapeout grid feeding the stripes
alike, which I cannot see from here, and the inside of the macro's own grid is
not modelled at all.

A second solver written separately, its own DEF parse and scipy's direct solve,
gives the same drops to the microvolt on the rings it was run on.

## Well taps

The release build keeps all 419 taps of the baseline at the same sites, so
fixing 1024 cells by hand took none of them. The tap step lays them on a
checkerboard, a row's own taps 25.76 um apart with the next row's in the gaps,
and the farthest any site sits from a tap in its own row or the next is 13.16
um, at a row end.

I measured along a row first and it reported 25.76 um holes that the rows above
and below cover. The 15 um I hold it to is the figure the OpenROAD sky130 tap
discussion works to; the public rule tables I could reach do not state one, so
it is a working figure, not a quoted rule.

## The three arms on a bench

A Monte Carlo over 20,000 dies: the release frequencies (full RC at tt, lumped
at ss and ff) for Arms A and C and the baseline's per-instance runs for Arm B,
a 0.062% mismatch per ring per die, the supply term above, and 0.0013% of
reading noise.

    arm   bits held   reader   uniqueness   one reading flips   corner flips
    A     0.04        8.00     0.001        0                   0
    B     8.00        4.03     0.501        0.68 %              0.25 %
    C     0.01        8.00     0.000        0                   0.03 %

The 0.68% is what theory says it should be for noise that small against
mismatch that size, arctan(0.0018/0.088)/pi, 0.67%, and twenty repeats with a
vote take it far down. Mismatch is held fixed across corners here, which it is
not on silicon, so the corner column is the floor for Arm B, not the estimate.

## So, is the chip good

As a piece of silicon, on everything checked: yes. DRC, LVS and antenna are
clean. Timing closes at nine corners. The selector works on all 48 paths. The
counter cannot wrap at 2048 cycles on any corner. The wires run 13 or more
times under their current limits. A ring warms itself by a fifth of a degree.
The supply sags half a millivolt. Taps are where the flow put them, and nothing
drawn is closer than the rule.

As an experiment it does what it was built to do, and the pre-silicon answer is
stark. Arms A and C are fully decided by the layout; Arm B is not. Hand
placement shrinks the pattern to a third and leaves every bit of it readable
from the design files.

## Where the real-world risk actually is: the bench

The preregistration's box is 1.62 to 1.98 V and -40 to 125 C. Nothing in the
repository says how the bench gets there, and two parts of it are dangerous to
the board rather than the chip.

- 125 C. Raspberry Pi rate the RP2040 on the demo board at -40 to +85 C. A
  board baked to 125 C is 40 degrees past its microcontroller, which is also
  what generates the 50 MHz reference. Heat the breakout only: it comes off the
  demo board on its DF12 connectors, so it can sit under a hot air stream or on
  a hot plate on an extension while the rest stays at room temperature
- -40 C. Cold boards pull water out of the air, and frost melting on a board
  that is powered is how pins short. Dry air or nitrogen over the chip, or a
  sealed bag with desiccant, and let it warm back up above the dew point before
  it is opened
- 1.62 and 1.98 V. The core supply has to be set and measured at the chip,
  which the preregistration asks for. How the demo board lets that happen is
  not in the repository, and it needs finding out before 2027, not in it

## Mistakes

Kept, all seven.

The first 32 decks ran two at a time with two OpenMP threads each on two cores
and took 190 s a deck instead of 30. I read it as a slow machine for ten
minutes.

`num_threads` comes from ngspice's init file, not `OMP_NUM_THREADS`, and the
file has to sit where the deck runs because `run_ngspice.py` starts ngspice in
the deck's directory. The two power decks started before that fix were killed
and re-run, and ring 0's lumped result came back the same to every printed
digit single-threaded.

`pkill -f` twice matched my own shell's command line and killed it.

The loop capacitance check first used the sample standard deviation, 1.83,
where the notes quote the population one, 1.77. The check says population now.

The Arm C to Arm A ratio came out 0.347 first, because it was taken on
percentages of each arm's mean. M4 is written in MHz, and that gives 0.363.

The self-heating check first compared a ring's whole 0.0197% shift, with the
selector's power counted as if it sat on the ring, against a tenth of the
mismatch scale, and failed. The shift is common to both rings of a pair and a
bit is a comparison, so the check now takes what differs inside a pair,
0.0015%. The whole shift is still printed, with the ring's own power only.

The supply check was first written to compare every pair's difference with the
smallest gap in either arm, which mixes Arm C's pairs with Arm A's gap. A trial
run before it was wired in showed it would fail by a hair on a comparison that
means nothing. It takes each pair against its own gap now.

And the tap distance and the 0.000 um li1 gap above.

## What this does not settle

Mismatch that changes with supply and temperature, which is what really decides
Arm B's reliability across the 27 cells. The Tiny Tapeout grid, package and
board above the stripes, and the macro's own grid. Arm B on the release build's
routes. Ageing, not modelled at all.

`real_world.py` is not wired into the evidence gate yet. Adding it moves the
gate count and the manifest, so it goes in with the push rather than today.
`verify_predictability.py` is in the gate already and now holds every
release-build and Arm C figure in the README, 138 checks in all, and the whole
gate is 130 of 130 in a container clone with today's files in place.
