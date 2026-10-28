# The clock beside a ring, simulated, and the rest again

28 October, evening. Before `b6cae0a` goes up the ask was to simulate
again whether everything on the chip is right, with a real world that is
not perfect. That meant three things: the logic simulations once more on
the release RTL, the new firmware against that RTL instead of a fake board,
and the one number the physical review could only estimate, how hard the
clock pulls a ring it runs beside.

## The logic, again

Nothing under `src/`, `test/` or `dualarm/` has changed since `38e9801`
(`git diff`), so this is a repeat, and meant as one.

- `make check`, the core, puf and tt testbenches: 3 of 3
- `test/`: the cocotb regression 11 of 11, and the E.2 table 21 of 21
- gate level: not here. The sky130 cell models are a download this
  machine is not allowed to make. GitHub's `gl_test` ran on `38e9801`,
  the last push, on the 27th and passed, and run 83's own netlist is the
  one the stress runs of 22 September used (`docs/phaseG_stress.md`)

## The firmware against the RTL

`firmware/cosim/` runs `measure_puf.py` itself, version 7, under cocotb
against the chip's RTL, with the behavioural rings `test/` uses. Four
CONFIG lines change, the chip id, the rounds, the sweep clocks and the
sweep rounds, and nothing else. Every pin it reads or writes, every sleep
and every clock it asks for costs simulated time, so the poll for `done`,
the 20 us settles and the sweep meet the real synchronizers and state
machine. Each clock change in the sweep also puts a 700 ps runt pulse on
`clk` with the project held in reset.

- fast, 0.1 us a pin operation, five clock cycles: one main round and one
  at 52 MHz, 96 rows, a round's readings 7 ms first to last
- typical, 5 us: two main rounds and two at 48 MHz, 192 rows, 12 to 13 ms
- uneven, a seeded 1 to 30 us each: one main round, one at 48 and one at
  52 MHz, 144 rows, 25 to 26 ms

Every round has all 48 rings, and every count and every first-start
count in the 432 rows is within one of what the model's frequency gives,
0.98 at the worst. No timeout, no overflow, the project in reset through
every clock change, and the analyzer reads all three files. I recounted
the rows against the models' half periods with a script of its own, and
it agrees.

Two things showed up that the fake board never would. The models put some
rings on round frequencies, so C05 reads exactly 25 quarter windows and C15
exactly 5 windows, and the analyzer's first check flags both as sitting on a
multiple. The sweep is what tells a ring that sits on a multiple from one
held there, and in the typical run it says no ring is off by more than 89
ppm at 48 MHz, C05 and C15 included.

And 48 MHz is 20833 ps in whole picoseconds, which is 48 000 768 Hz. The
simulated board says so, as the SDK would, so the firmware's warning about a
clock it did not ask for fires and the rows carry the clock it got. On the
real board the SDK makes 48 MHz exactly.

## The clock beside a ring

`sim/spice/gono/inject.py` takes `gen_rc_decks.py`'s distributed deck of one
ring, every resistor and coupling as the SPEF has them, and changes one
thing: a coupling whose far end is on a named aggressor net goes to an ideal
square wave instead of to ground. Full supply swing, 100 ps edges, even
duty. The square wave runs at f0/n, f0 the ring's own frequency from a
reference deck with the aggressor held at 0 V, and n odd, so its n-th
harmonic sits exactly on the ring and both of its edges push the same way.

A ring pulled that way runs faster or slower depending on the phase between
the two, and the largest change over the phase is the lock range: a ring
that comes within that much of a harmonic locks onto it. So the square wave
starts 8 or 16 different fractions of a ring period late, one deck each, and
each deck is read over a whole number of the square wave's periods after 30
ns.

The reference decks are the archived ones, `rc3/armC/`, with one change,
and they read 71 to 83 ppm above the archived logs. That is the solver,
not the change: the archive ran at ngspice's default `reltol` of 1e-3 and
these at 1e-4, and the archived C08 deck itself moves 71 ppm between the
two. At 1e-4 the archived deck and this one agree to 3.7 ppm, and at 1e-5
to 0.5. 1e-4 is what everything here uses; the pull is a difference
between decks that differ only in when the square wave starts.

Where the coupling lands, from the same SPEF and the same parser, for the
rings with the most of it:

    ring  aggressor    on the loop  how it lies
    C08   clock leaf   0.760 fF     about 0.1 on each of i9 to i15,
                                    0.03 on i8
    C11   clock leaf   0.489 fF     all of it on the NAND's input
    C12   timer bit 0  0.641 fF     i24 to i30, 0.19, 0.15 and 0.15 on
                                    i25, i27 and i29
    C15   clock leaf   0.632 fF     i23 to i30, heavier on i24, i28 and
                                    i30, 0.11, 0.15 and 0.14

Two stages in a row switch opposite ways. Charge that lands evenly on a
run of stages pushes one forward and the next one back, and most of it
cancels. Charge that lands on one node, or on every other stage, does
not. C11 also has 1.493 fF on its output net past the tap buffer, outside
the loop; the decks drive that too, since it is part of what is measured.

What came back, at tt, as the change in frequency from the reference
deck, averaged over the read. The phase is when the square wave starts, in
sixteenths of a ring period for C11 and C15 and in eighths for C12; the
half steps are a second set started halfway between the first one's.

    C11, 100 ps edges, 7 and 11 to 15 not run
    phase      0    0.5      1    1.5      2   3 to 6
    ppm      -22   -180   -310    -45     +1   -1 to 0
    phase      8    8.5      9    9.5     10
    ppm      +32   +281   +197    +32      0

    C15, 100 ps edges, 11 to 14 not run
    phase     15      0      1   2 to 6      7      8      9     10
    ppm      +12   +100    +33  -2 to 0    -13    -90    -40     -2

    C12 from the timer's bit 0, 100 ps edges
    phase   7.5     0   0.5  1 to 3   3.5     4   4.5  5 to 7
    ppm     -24   -58    +2  -3       +25   +55     0  -2

C08 shows nothing. Its eight phases read between +0.4 and +4.0 ppm, the same
offset of about 2 ppm in all of them and no shape, which is what the solver
does between decks that differ only in when the source moves.

C11 has two spikes, half a ring period apart. At one, each edge of the
square wave meets the NAND's input switching the same way and hurries it; at
the other it meets it switching the opposite way and holds it back. Away
from them the ring is within about a ppm of its own frequency.

The crossings say the spikes are the ring and not something on the output
net: against the reference it falls behind by about 6 ps every period of the
square wave, 3 ps an edge, from the first period of the read to the last.
The pull also moves the ring's phase while it is read, so near a spike a
single period can sit above the read's average; the steepest single period
is 316 ppm slow and 291 fast.

The edges matter, and 100 ps was a choice, not a measurement. So I measured
two in SPICE. The clock leaf, a `clkbuf_8` with 31 fF on it, switches in 47
ps rising and 39 falling, 20 to 80 percent; the timer's bit 0, a `dfrtp_2`
with about 30 fF, in 157 and 81.

Run again at 70 ps edges, centred where the 100 ps ones were, C11's slow
spike is 376 ppm, 397 in its steepest period. At the fast spike's phase 9 it
reads 182, but that phase is on the spike's shoulder; its top, at 8.5, was
not run at 70 ps. So with the clock's real edges C11's pull is about 400
ppm. The timer bit is slower than 100 ps, so C12's 58 is high rather than
low.

Where a ring's coupling lands decides how hard it is pulled, then, and by
that measure C11 is the worst ring here, not C08. If its own frequency is
up to about 400 ppm above an odd multiple of the clock, or about 300 below
it, the clock pulls it onto the multiple and it stays there.

## What it means for the chip

Not a defect, and no change to the layout. The numbers:

- the bits. The line every scored pair clears is 0.618 percent. 400 ppm is
  0.04, a fifteenth of it. C11's pair, C10/11, is 1.15 percent apart; C15
  is half of the closest scored pair, C14/15 at 0.648, and its 100 ppm
  would take that to 0.638 at worst. No scored bit can turn on this
- how often. The supply moves a ring about 1060 ppm a millivolt, so C11's
  window is under a millivolt of supply wide, and the next odd multiple of
  50 MHz is 100 MHz away, about 165 mV. At any one setting the chance C11
  sits in a window is a few tenths of a percent; C15's is about a quarter
  of that
- what it looks like. A locked ring reads an exact multiple: C11 onto 550
  MHz would read 22528, eleven windows. The analyzer's first pulled-ring
  check flags exactly that, and the clock sweep moves the multiple away by
  four percent, so a locked ring changes frequency and a free one does not

For the next chip the rule is simple: no clock or timer net running beside
a single ring node. Running evenly along a stretch of stages costs nothing
this can measure, C08 shows that.

## What this does not cover

- the Arm B macros. The SPEF sees them as boxes and magic's coupled decks
  keep only a ring's couplings to itself, so the clock over B05, B06, B09,
  B10, B13 and B14 is a length and nothing more. If one of those wires
  crosses a single node the way C11's clock does, it pulls like C11, and
  for Arm B, whose rings differ by mismatch alone, that matters more
- the rings not run. C06's coupling sits mostly on the NAND's input, like
  C11's but about half of it; its decks are made and were not run. A08 has
  0.11 fF on two stages that switch the same way, C09 0.056 on one node.
  C00, C01, C03 and C13 spread theirs evenly over runs of stages, the way
  C08 does. The counter bit beside A14 changes about eleven times a window
  and is not periodic
- tt only, at 1.80 V and 27 C, and only odd multiples. A real clock's duty
  is not exactly half, so even multiples pull a little too
- C15 without half steps, so its top may sit a little above 100. Some
  phases were left for time: C11's 7 and 15, on a spike's shoulder, and
  11 to 14 of both rings, between phases that read within a couple of ppm
- ideal sources. A real clock leaf has its buffer behind it, and the supply
  the buffers draw from is ideal in every deck, so a pull through the rails
  is not here
- the noise. Decks that differ only in when the square wave starts read
  about a ppm apart at `reltol` 1e-4, a few ppm in a single period

## Mistakes kept

- for an hour and a half I read C08's null as the answer for the chip.
  It is the answer for C08, and I said so as soon as C11 came back
- the physical review took the ring with the most clock wire beside it for
  the one pulled hardest. Where the wire lands decides that
- the small decks, at a hundredth of the swing, were meant to show the
  noise floor. They ran more than three times slower than the full ones,
  so they were stopped after two; C08's own phases show the floor instead
