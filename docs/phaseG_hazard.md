# The selector hazard, counted again, and a second start

23 September. Last night's stress run ended on a hazard in the counter clock
mux and two cheap fixes for it: a line in the datasheet about holding the
window bits, and a second start for every selection in the firmware.

I did both, and then went looking for whether the chip is actually good to
go, allowing for what a simulation cannot see.

Before any of that I had to count the hazard again, because last night's count
was wrong.

## One cell was wrong

`sim/mux_hazard.py` as it went into `stress` looked for a cell whose output is
0 for every selector value and which has two inputs that can both be 1 while
the selector changes. It found one, `_448_`, an `and3_2`, on 832 of the 4032
changes of selection, and `docs/phaseG_stress.md` said so three times.

The test was too narrow. A cell that is 0 at both ends of one particular
change, and 1 for some other selector, can pulse on that change just the same.
So can a cell whose inputs are pulsing themselves.

The script looked at neither, and of the twelve cells where a pulse can start,
`_448_` is the only one that is 0 for all 64 values.

It does ternary simulation now, which is the textbook way (Eichelberger, 1965)
and what I should have written first.

For a change from a to b, every selector bit that changes is X, every ring
output is 0, since all of them are stopped when a start comes, and every cell
in the cone of `sel_ro` is evaluated in three values. If `sel_ro` comes out X
while it is 0 at both ends, some choice of gate and wire delays pulses it.

On run 83's netlist:

    nets in the cone of sel_ro            123
    changes on which sel_ro can pulse     1728 of 4032
    cells where a pulse starts            12
      _448_ and3_2    672      _311_ and2b_2   288
      _438_ and3b_2   608      _306_ and2b_2   288
      _295_ nor2_2    384      _317_ and2_2    288
      _447_ o21a_2    288      _298_ nor2_2    288
      _300_ and2b_2   216      _302_ and2b_2   216
      _297_ nor2_2    216      _304_ and2_2    216
    slots a change can pulse into         64 of 64

The counts beside each cell add up to more than 1728 because one change can
start a pulse in two places.

Between the 48 slots that select a ring it is 960 of the 2256 changes. Every
slot is the destination of some of them, so no ring is out of reach by where it
sits in the mux.

It is not new with the third arm, either. The two-arm baseline's mux,
`dualarm/build_current`, gives 2048 of 4032 from nine cells.

Synthesis builds a 64 to 1 mux out of predecoded selector terms, and a
predecoded mux driven by six flops that switch together does this. Nobody had
looked, and nothing before last night's stress run predicted a count closely
enough to see one extra.

The selftest plants what the old version could not see: a pulse that starts in
one cell and reaches `sel_ro` through a second, where neither cell is 0 for
every selector value. Written out in closed form it can pulse on exactly 768
transitions, the script has to say 768, and it has to say nothing for a clean
twin with the inverter under the second cell swapped for a tie cell.

The gate runs the selftest and `--expect 1728` on the release netlist from
today, so a rebuild that changes the tree turns CI red.

## What the hazard can and cannot do

It cannot do anything to the chip. The pulse is on the counter clock, a net
that carries a running ring's full rate for the whole of a measurement, and all
it can do there is clock the counter. It cannot turn a ring on.

The 48 enables come from seven flops through their own `and3` cells, and last
night's sweep of all 128 of those flop states found no second enable high, not
even for a delta cycle.

What it can do is add a count to the first run after a change of selection, one
count in every simulation so far, 43 ppm at the 2048 window, if the pulse
reaches the counter after its reset has let go.

The same clock edge starts both, the selector through the mux tree and the
reset release through `_292_`, `_294_` and a delay buffer. The structure cannot
say which one wins.

A timed run against the extracted layout can say what the models predict, and
it is running as I write this. What the silicon does, only the silicon can say,
which is why the fix below records the evidence instead of assuming it away.

## The second start

`firmware/measure_puf.py` starts every selection twice now and keeps both
counts. A second start on the same selection loads the six selector flops with
what they already hold, so nothing in the mux moves, and last night's twelve
repeated starts in simulation all began at 0.

`count` is the second run and is the reading. `count_first` is the first one,
and the first minus the second, averaged over repeats, is the hazard measured
on the real die. One pair of runs can also differ by the ordinary one-count
boundary jitter, so it is the average that means something, not any single row.

At the end of a run the script prints how many differences were -1, 0 and +1.
The analyzer reports the mean per chip and condition, and splits it in two when
given a list of the changes a timed run predicts to count.

It costs one more run per selection, about 3 ms with the script's millisecond
waits between pin writes, and nothing on the chip.

Two more things went into the same file. Before anything is measured it reads
the version bytes through `uio[3]` and stops unless they are 2 and 0x1A, which
catches the wrong project, a board that is not driving the pins and a die whose
project does not answer, before a single count is written.

And the old version, on the way out, stopped the clock and left the reset
alone. `docs/info.md` has said since July to abort with `rst_n` or `ena` before
stopping the clock, because a ring whose window is open when the clock stops
stays on. It resets first now.

## A board that does not exist yet

The firmware runs under MicroPython on a board that nobody has. So
`firmware/test_measure_puf.py` runs the file itself under CPython with the two
things MicroPython provides replaced: `time`, and the SDK's `DemoBoard`, with a
fake that keeps the chip's pin protocol but not its physics.

A start edge on `ui[0]` takes the selection, `done` rises, `ui[6]` picks the
byte, `uio[3]` swaps in the version bytes, `uio[4]` sticks. A listed change of
selection adds one count to the next run, the way the selector would.

I checked the calls the firmware makes against tt-micropython-firmware v3.1.1,
the release from 8 September. Pin bits come back as a `Logic` there, which has
`__int__` and `__bool__`, so `int(tt.uio_out[4])` and `while not tt.uio_out[0]`
both do what they look like.

Four tests. A whole run, 60 rounds of 48 selections at two starts each, 5760
starts, where the planted count turns up in `count_first` and never in `count`,
and the file then loads in the analyzer with all three arms.

The wrong version bytes, which must stop before any count. An operator stopping
the run, which must reset before the clock stops. And a shuttle without the
project. Last night's firmware fails three of the four.

## The analyzer could not read the firmware

`analyze_counts.py` refused any row whose arm was not 0 or 1, with "arm/idx out
of range". The firmware has measured three arms since 4 September, so the first
Arm C row of the first real run would have stopped the whole analysis.

Nothing had ever fed the firmware's output to the analyzer, which is how it
survived. Running the fake board's output through it is how it came up.

It takes arm 2 now and reports all three arms wherever it reported two, except
the primary delta, which is Arm A against Arm B by definition. It reads
`count_first` and `overflow` when they are there, and older files without them
still load.

`FASTEST_SIM_MHZ` was 888.3, the two-arm baseline's fastest Arm A ring. The
release build's fastest is Arm C's ring 10 at 911.1 in the fast corner, the
number the datasheet quotes.

The change moves the point where the wrap check says the fast corner already
wraps from 27.8 to 28.5 MHz at the 2048 window, so a 28 MHz clock was being
called thin when it wraps. The test pins that edge now.

## The datasheet and the README

`docs/info.md` got three things.

Hold the window bits on `uio[2:1]` until `done`, with the reason: the window is
compared on every clock, so a change under a run moves its end, and a shorter
window than the timer has already passed runs until the 16-bit timer comes
round, up to 65536 cycles. Arm 3 selects nothing: `done` comes back and the
count is 0, apart from the one a change of selection can add. And start each
selection twice and keep the second count.

`sim/verify_datasheet.py` ties the first and the last of those to their
sources: the window decode and compare in the RTL, with no register in between,
and the two runs in `measure_one`. 29 checks, and each new one fails when I
break the line it reads, one at a time.

`firmware/README.md` had a protocol section from the chip before this one: a
fixed 1000-cycle window, 25 MHz, a wrap at 1638 MHz, rings at 840 to 888 MHz in
the fast corner.

Rewritten for 2048 cycles at 50 MHz, the 28.5 MHz floor, 275 to 911 MHz across
the corners, the second start and the version check. The README also called the
analyzer's primary delta the statistic to preregister, which stopped being true
on 31 August when the preregistration chose a different M2.

## Mistakes

- The one cell. Above, and corrected where it stands in
  `docs/phaseG_stress.md` with the date on it, not rewritten.
- The first expected set I wrote for the new selftest was too narrow, and
  the script found transitions my list did not have. The script was right.
  The expectation is written in closed form now, from when an AND of known
  and unknown inputs is X, and the two agree on 768.
- The first ternary version did not tell a tie cell's `HI` pin from its
  `LO` pin. A `conb_1` drives both, one at 1 and one at 0.

## Not covered, and open

Nothing here runs on silicon. The fake board keeps the protocol, so it proves
the order of calls and what gets written down, not timing. `time.sleep_ms(1)`
between pin writes is over ten thousand times the three clock cycles the chip
needs at 50 MHz, so the timing on a real board has room to spare, but it has
never been tried.

The timed run of the hazard is the next part, and with it whether any of the
960 changes between rings actually reads one high in the models. The first die
settles it for real.
