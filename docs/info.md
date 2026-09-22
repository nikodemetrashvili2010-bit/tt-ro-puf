<!---
This file is used to generate the TinyTapeout project datasheet.
-->

## How it works

This project is a ring-oscillator Physically Unclonable Function (RO-PUF)
experiment.

An RO-PUF compares nominally identical oscillators and uses their frequency
ordering to form response bits. Useful device-specific behavior must come from
manufacturing variation rather than a deterministic implementation bias shared
by the design.

The design has 48 ring oscillators split into three arms of 16. Arm A is placed
and routed as standard cells by the automated flow, with no constraint beyond
the ones the flow imposes on itself. Arm B uses sixteen instances of one
hardened oscillator macro, so its sixteen layouts are the same layout. Arm C is
standard cells again, like Arm A, but its sixteen rings are placed by hand from
one template: the same 32 cells on the same 4-row, 8-cell grid at the same
offsets inside sixteen identical regions, fixed before the placer runs, with
the routing left to the flow.

All three arms use the same oscillator circuit. Each oscillator is a 31-stage
ring: one enable NAND and 30 inverters, with a buffered tap taken halfway along
the chain for the measurement core. Arm A against Arm B asks whether an
automated layout leaves a fingerprint that a matched layout does not. Arm A
against Arm C asks a narrower question: how much of that fingerprint is
placement freedom on its own, with routing and cell choice left alone. The
comparison is preregistered.

Oscillators are measured one at a time through a shared counter. A synchronized
start request clears the counter and opens a measurement window of 256, 512,
2048 or 16384 reference-clock cycles, selected on `uio[2:1]`. The selected
oscillator's edges are accumulated in an asynchronous ripple counter. When the
window closes, the oscillator stops; the counter crosses a two-flop sampler and
must produce three consecutive equal samples before the frozen count and `done`
are published.

`uio[5]` is high while the window is open, and `uio[4]` latches if the counter
wrapped and stays latched until reset.

A coherent nominal post-layout simulation of the release build, run 83,
predicts a 5.73% peak-to-peak spread in Arm A from the lumped decks, 5.88%
with the full extracted RC network, and it follows the routing capacitance
closely. Arm C spreads 2.19%
under the same RC network, about a third of Arm A. Nine builds of the earlier
two-arm layout that vary only placement density put the Arm A number in
context: they run from 4.19% to 6.99%, median 5.75%.

That build passes Magic and KLayout DRC, XOR, LVS, antenna, detailed routing,
and power-grid connectivity with zero violations, so the prediction and the
candidate GDS come from the same flow run; the ring-oscillator STA warnings are
listed separately in SIGNOFF. Arm B's sixteen instances reuse the same internal
macro layout, and since 2026-08-04 each one has been extracted separately with
the top-level routes it actually carries, rather than one macro result being
plotted sixteen times.

On the release build's routes the sixteen spread 0.0033% peak to peak at tt,
0.0001% at ss and 0.0019% at ff, less than one count at the 2048-cycle window
and the 50 MHz clock the firmware uses, so one such reading cannot tell them
apart; on the two-arm layout's routes it was 0.0025% at tt. That is a measured
pre-silicon result rather than an assumption, and it is what makes Arm B the
control.

The experiment will test whether Arm A's centred frequency pattern repeats more
strongly across fabricated chips than Arm B's pattern. Cross-die repeatability,
uniqueness, and security impact are unknown until those measurements are made.

One timing figure belongs here rather than only in SIGNOFF. When a window
closes the ring's last pulse can come out any width, and where it sits right at
the selector's own threshold the chain squeezes it instead of stretching it.
Swept through the release build's slowest selector path down to 0.2 ps steps,
the narrowest clock the counter flop saw that way was 80 ps, the same as on the
two-arm layout, against the 77.5 ps the library characterizes for it at
ff_n40C_1v95. Every finer grid found a narrower pulse than the one before, so
this is not a number with a floor under it.

It is not the 2.5 ps margin it looks like. The 77.5 ps is the library's figure
at a 10 ps clock slew and it climbs fast with slew, so at any realistic slew
the pulse is under it. It does not need to clear it either. It is the last
pulse before a stop, the flop was simulated at transistor level rather than
looked up, and whichever way it resolves the count moves by one, which the
three-sample handshake absorbs. On the two-arm layout the slow corners were
nowhere near it, 484 ps against 169.8 at tt and 810 ps against 353.8 at ss.
`SIGNOFF.md` has the rest.

## How to test

Drive `clk` with a clean reference clock and release `rst_n`.

Keep `clk` running until `done`. If a measurement must be aborted, assert
`rst_n` or deselect the project (`ena=0`) before stopping the clock; either path
asynchronously shuts down the selected oscillator.

0. Choose a window on `uio[2:1]`: 0 is 256 cycles, 1 is 512, 2 is 2048 and 3
   is 16384. 2 is the measurement setting. 3 is there to overflow the counter
   on purpose, so that the flag on `uio[4]` can be exercised on any die.
1. Select an oscillator: set the arm with `ui[1]` and `ui[7]` (0 = Arm A,
   1 = Arm B, 2 = Arm C) and the oscillator index with `ui[2]` through `ui[5]`.
2. Keep arm and index stable for at least three `clk` cycles, hold `ui[0]`
   (`start`) high for at least three more cycles, then drive it low. Leave arm
   and index unchanged until `done`.
3. Wait for `done` on `uio[0]`.
4. Read the 16-bit count as two bytes on `uo[7:0]`. `ui[6]` low selects the low
   byte and high selects the high byte. **Wait three `clk` cycles after changing
   `ui[6]` before reading `uo`.** `ui[6]` goes through the same two-flop
   synchronizer as the arm and index bits, so the byte on `uo` is still the old
   one for two clock edges after you change the pin. There is no error flag for
   this. You get a valid-looking byte from the wrong half of the count.

There is no hurry over step 4.

`done` stays high and the count is held until the next start pulse, so the two
bytes can be read as slowly as you like. Check `uio[4]` while you are there: if
it is high the count wrapped and the reading means nothing, whatever it looks
like.

Driving `uio[3]` high swaps `uo` from the count to two version bytes, protocol
on the low half and build id on the high half, so a board can tell which design
it is talking to before it trusts anything else. It does not disturb a stored
count.

Repeat for each oscillator in all three arms and collect repeated samples.

Testing the research hypothesis requires multiple physical chips measured under
the same controlled conditions, followed by repeated voltage and temperature
runs. The scripts and data-label convention are documented in `firmware/`.

## Choosing the reference clock

`info.yaml` declares 50 MHz, the build was signed off at 50 MHz, the demo board
starts there, and the measurement script in `firmware/` asks for 50 MHz too.
The earlier version of this design had a fixed 1000-cycle window and no way to
change it, so the clock was the only knob and the script recommended 25 MHz to
get counts worth having.

The window is selectable now and the clock does not have to carry that job any
more.

How long an oscillator is counted for is the window, and the count follows:

    count = f_osc * WINDOW / f_clk

At 50 MHz the 2048-cycle window is 41 microseconds. The nominal post-layout
prediction for Arm A on the release build, 538.4 to 570.0 MHz, comes out as
roughly 22052 to 23347 counts, and the spread between the slowest and fastest
ring is about 1295 counts. Arm C sits higher and much closer together, 23383 to
23895. The 512 window gives a quarter of each, and 256 an eighth. Two things
decide the window. One count is the smallest difference the chip can report,
and at 2048 that is 43 parts per million against a per-ring mismatch sigma of
about 620 ppm from the Monte Carlo work, so a count is roughly a fourteenth of
a sigma. At 512 it is 171 ppm and a bit over a quarter of a sigma. Longer
window, finer measurement.

Pulling the other way, the counter is 16 bits. Wrapping needs
`f_osc * WINDOW / f_clk` to pass 65535, so at a given window the clock must
stay above

    f_clk_min = f_osc * WINDOW / 65536

The fastest ring on the chip in the simulated fast corner is an Arm C ring at
911.1 MHz, which at 2048 puts that floor at 28.5 MHz. At 50 MHz that same ring
reads 37318, a little over half of full scale, so there is still close to a
factor of two in hand for silicon coming out faster than the model. Arm A's
fastest there is 887.2 MHz, or 891.7 in the decks the Arm C figure comes from,
and Arm B's is 891.4, so it is Arm C that sets the floor now.

2048 at 50 MHz is where those two pull evenly, and it is what the firmware
uses. If a die runs faster than that leaves room for, `uio[4]` says so: it
latches on the wrap and holds until reset, so a wrapped count is reported
rather than inferred from how close to the ceiling it looks. Drop to the 512
window and rerun.

The 16384 window is the other direction on purpose. It overflows at every
corner on every die, which is what makes it a test of the flag rather than a
measurement.

## External hardware

A microcontroller such as the RP2040 on the TinyTapeout demo board can set the
control inputs and read the counter bytes. A stable reference clock and a way
to record supply voltage and temperature are needed for controlled comparison.
