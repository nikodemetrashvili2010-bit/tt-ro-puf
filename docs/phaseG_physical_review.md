# The physical review, and what changed on the bench side

27 and 28 October 2026. The question on the evening of the 27th was the
hard one: where does the physical world break this chip when the digital
simulations all pass. Injection locking and cross-talk, layout asymmetry,
supply and temperature, reset and metastability. Then, a few hours later,
fix everything so it works in an imperfect world.

The layout does not change. Run 83 is what goes to the shuttle, the
predictions are frozen against its extraction, and a rebuild would route
Arms A and C again and start over the placement fight that took runs 74 to
83. Nothing found here is a defect that needs one. What changed is the side
that can still change: the bench firmware, the analyzer, and a script that
says what runs beside each ring, so the first die shows these effects if
they are there instead of hiding them in the counts.

## What runs beside a ring

Only one ring runs at a time, and that is structure, not protocol
(`docs/phaseG_checklist_review.md`), so a neighbouring ring is never the
aggressor. What does switch during a run is the 50 MHz clock tree and the
flops that change on its edges: the window timer, which counts every cycle
of the window, and `cnt_meta` and `cnt_sync`, which sample the counter
every cycle.

`sim/spice/gono/clock_neighbours.py` reads run 83 for that. For the 32
routed rings it takes the SPEF's coupling from each ring's 31 loop nets to
everything else, wire only, since the SPEF has `PIN_CAP NONE`:

- the clock tree couples to 11 of them, 9 in Arm C. C08 is the worst at
  0.760 fF on `clknet_4_15_0_clk`, 7.5 percent of its 10.14 fF loop, then
  C15 0.632, C13 0.627, C06 0.556, C11 0.489, C00 0.470, C01 0.455, C03
  0.444, A15 0.305, A08 0.123 and C09 0.056
- the window timer's two low bits couple to C12, 0.747 fF from `wtimer[1]`
  and 0.641 from `wtimer[0]`, 1.388 in all. That is more than any clock net
  puts on any ring, and both are square waves for the whole window, 25 and
  12.5 MHz. I missed this on the 27th, I had only counted the clock tree,
  and found it writing the script
- `cnt_sync[11]` couples 0.487 fF to A14, and bit 0 0.092 to C14 and 0.040
  to C09. Bit 11 changes about eleven times in a window

For Arm B the SPEF has nothing inside the macro, so the script reads the DEF
instead: how much top-level wire crosses each macro's ring area, the box the
LEF obstructs on li1. The LEF stops li1 and met1 there, a strip of met2 and a
bit of met3, and the router used the rest. The clock crosses six of the
sixteen, 16.5 um each: `clknet_4_6_0_clk` on met2 over B05, B09 and B13, and
the `clk` root on met4 over B06, B10 and B14. `cnt_sync` bits cross B12 and
B15.

These are lengths and not capacitance. magic, which extracted the whole
layout flat on 20 October, puts 0.03 fF (B11) to 0.74 fF (B15) of top-level
wiring onto the macro rings in all (`sim/spice/magic/README.md`), so the
clock's share on any one macro is somewhere under that.

The checks behind those numbers: 32 rings of 31 nets with every coupling
node resolved, each net's caps adding to its `*D_NET` total, the clock's own
side of the SPEF giving the same coupling to each ring, the macros where
`config.json` puts them, and no top-level li1 or met1 over any ring area.
Six planted faults, each caught by its own check alone. The CSV is in the
gate.

None of this has been simulated switching. The lumped decks put a net's
whole SPEF total on it as a grounded load, the RC decks keep a coupling as a
coupling only when both ends are in the ring and ground the rest
(`gen_rc_decks.py`), and magic's coupled decks keep only a ring's couplings
to itself. The 17 September review said the clock's pull is the same for
all 48 rings. It is not. A00 has nothing next to it and C08 has a clock
wire along it.

### How much it could do

A ring close enough to a multiple of an aggressor's frequency can lock onto
it. Estimated, not simulated: the coupled share of the loop's capacitance,
times the size of the aggressor's harmonic at the ring's frequency, shared
over the 31 nets, gives a lock range of order 100 ppm on the worst ring, and
I would not trust that to better than a factor of three either way.

Two things follow. The bits are safe: the line every scored pair has to
clear is 0.618 percent of the arm mean, and the closest scored pair is
C14/15 at 0.648 in the SPEF's RC decks. Arm A's closest is A10/11 at 0.964
in magic's table. A pull of 300 ppm, the top of the estimate, is a twentieth
of the line. What is not safe is a pulled ring's frequency. It would read the
multiple, not itself, and for Arm B, whose rings differ by mismatch alone,
about 620 ppm a ring, a hundred ppm is not nothing for M2.

The supply moves a ring about 1060 ppm a millivolt, so a lock range that
size is a tenth of a millivolt of supply wide. A ring would not sit in it, it
would drift in and out, pinned to the multiple for some readings and free
for the rest. Whether any ring lands near a multiple at all depends on where
silicon puts it: Arm A at tt is 538 to 570 MHz, which has 550 (11 x 50) in
the middle of it, and Arm C at ff reaches 900 (18 x 50).

Simulated the same evening, `docs/phaseG_clock_pull.md`. The size was about
right and the ring was wrong. Where the coupling lands decides it, not how
much there is: C08's lies evenly along eight stages in a row and cancels,
nothing above the solver's noise, while C11's sits on one node, the NAND's
input, and pulls it about 300 ppm either way at 100 ps edges and about 400
at the clock's real ones. C15 about 100, C12's timer bit about 60. The bits
are still safe, 400 ppm is a fifteenth of the line, and a pulled ring's
frequency is still the thing to watch. For C11 the window is under a
millivolt of supply wide.

## Supply and temperature

These were in the archive already, from `analyze_noise.py` on the two-arm
baseline's Arm A, whose cells sit where the release build's do:

- 105.88 percent a volt, so 1.06 percent for 10 mV, and it is common mode.
  The part that differs between rings is 0.027 percent at 1.62 V and 0.034
  at 1.98 V, 1.5 to 1.9 ppm a millivolt
- +0.0035 percent a degree, 35 ppm, between 0 and 85 C at 1.80 V
- all eight of that Arm A's bits keep their sign at all 11 supply and
  temperature points

So the supply is a common-mode problem. It cancels in a pair read at the
same moment and does not cancel in a pair read at two different moments,
and the firmware read the two rings of a pair at random places in a round:
1 mV between them is about 1060 ppm. A round had 0.29 s of sleeping in it.

## Reset and metastability

Nothing new. Every control input goes through two `async_reg` stages before
anything reads it, start is edge detected after them, reset asserts
asynchronously and lets go through two stages, and the counter is only read
after the ring has stopped and three samples in a row agree. The first-run
count after a change of selection is the known one (`docs/phaseG_hazard.md`)
and the firmware keeps the second start.

## What changed

`firmware/measure_puf.py` is `measure_puf/7`:

- the waits in a reading are `SETTLE_US`, 16 periods of the slowest clock
  the run uses and never under 20 us, where each start used to sit through
  three 1 ms sleeps. The chip needs three clock cycles. A round's rows are
  printed after the round, not between readings
- each round's rows carry the die temperature of the board's own RP2,
  `t_rp_c`, read through `ADC.CORE_TEMP` as the SDK reads it and empty off
  an RP2, and the header carries the RP2's system clock with a warning if
  the project clock does not divide it
- `CLK_SWEEP_HZ` reads every ring again at other clocks after the main
  rounds, `SWEEP_ROUNDS` rounds each, with the project held in reset while
  the clock changes, and every row says the clock it was counted at.
  48 and 52 MHz divide evenly, 96 and 104 MHz halved, from the SDK's own
  search at v3.1.1

What did not change: the seeded random order of all 48 every round, two
starts a reading, the second one's count, and every line
`preregister.py --amendment` A08 looks for. A08 passes.

`firmware/analyze_counts.py` keeps sweep rows out of every statistic and
has two new sections at the end, both labelled exploratory and feeding
nothing above them:

- drift: each reading's offset from its ring's median, and the median of
  those over the 24 readings either side, the reading itself left out, as
  the common mode at that moment. A ring's median is taken at drifting
  moments too, so it is taken again from the corrected copy, three passes
  in all. The section prints how far the common mode moved and what the
  repeat noise and the held-out bit errors are with it divided out
- a ring pulled onto the clock, three ways. A median on a whole number of
  windows, or of half or quarter windows for the timer bits, which a free
  ring also does about 3 times in 512. A pile of readings on one such
  multiple where the ring's own spread puts few, for the ring that drifts in
  and out. And with the sweep, a ring whose frequency at the other clocks
  disagrees with its own at 50 MHz once the shift every ring shares is
  taken out, since a free ring has one frequency whatever counts it

On a planted ramp of 1500 ppm a round the drift section finds 26571 ppm, 5th
to 95th percentile, and the ramp worked out by hand gives 26571. The median
repeat SD goes from 8530 ppm to 46 and the bit errors to none. At 100 ppm a
round it is 577 to 23, which is the dither floor. On the fake board with B05
locked 120 ppm off its own frequency, the sweep finds it at +120 and +114
ppm against limits of 25 and 29, and nothing else.

The tests run both files whole: `test_measure_puf.py` puts the firmware
through a run on the fake board with a ring locked, and the analyzer reads
what it printed. 59 tests where there were 40.

## What I suggested on the 27th and did not do

ABBA order for the two rings of a pair. The amendment of 18 October replaced
the frozen ABBA order with a seeded random order of all 48 every round, and
said what it gave up, the exact cancelling of a linear drift
(`docs/phaseG_prereg_amendment.md`). The firmware has to read the way the
amendment says, and A08 holds it to that. The part of the same idea that the
amendment allows is a shorter round, and that is the pace change.

A check that the project clock divides the RP2's clock. `sim/tt_fit.py`
already does that for 50 MHz against the SDK's own search, written on 4
October and in the repository since the 18th. I offered it as new. The
firmware's warning is only for a board whose settings moved the system
clock.

Logging the core supply. The board cannot measure the chip's supply, and
the header already has a field for a measured one.

Layout: met2 to met4 obstruction over each Arm B ring, the clock tree and
the window timer kept out of ring areas, `RSZ_DONT_TOUCH_RX` on the ring
cells. All of that is for the next chip, for the reason at the top. On this
one the rings already survive the flow, 32 of 32, checked on every CI build.

## Limits

- the lock range is an estimate. A deck with the clock tree and the timer
  bits driven beside a ring is the way to know, and it has not been written.
  Written that evening for four rings, `docs/phaseG_clock_pull.md`; the
  Arm B macros are still only lengths
- the pile-up look needs a ring whose readings spread over two counts or
  more. A ring pinned all the time is the median's to catch, and a ring that
  barely moves and is pinned now and then is caught by neither
- the drift correction follows what changes slower than about a round. A
  wobble faster than that averages out of the common mode and stays in the
  readings
- `t_rp_c` is the board's microcontroller, not the chip
- version 7 has only run on the fake board. The ESP32 bench on 19 October
  ran version 6. How long a round takes now depends on MicroPython's speed
  on the board's RP2, and the first real run's `t_ms` will say

## Mistakes kept

- the review of the 27th counted the clock tree and not the flops that move
  with it, so it missed the window timer beside C12
- it offered ABBA and the clock-division check as new; one goes against the
  amendment and the other was already in `tt_fit.py`
- it gave C14/15 at 1.027 in magic as the closest scored pair in both
  tables. In magic's the closest is A10/11 at 0.964
- the first version read the temperature with `ADC(4)`, the RP2040's
  channel. The current demo board carries an RP2350B, where the sensor is
  channel 8 and 4 is GPIO 44, so every round would have read a pin. Found
  reading the SDK's own `pins/adc.py`, which uses `ADC.CORE_TEMP`
- the first warning about the RP2's clock fired on any odd divider too.
  A whole odd divider only moves the duty cycle, which a design that uses
  rising edges alone never sees
- the drift estimate took each ring's median once and left about 90 ppm on
  a steep ramp. Three passes leave 46
- the firmware header's first draft said a round took about half a second.
  The sleeps were 0.29 s, and the rest was never measured
- the test fixture first checked that B05 sat on a multiple of the window
  by its own frequency. It only does because it is locked
- this file said 58 tests at first. There are 59
- the estimate picked C08 as the worst ring because the most clock wire runs
  beside it. Where the wire lands matters more, and C08's cancels; SPICE
  that evening put C11 first
