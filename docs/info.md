<!---
This file is used to generate the TinyTapeout project datasheet.
-->

## How it works

This project is a ring-oscillator Physically Unclonable Function (RO-PUF)
experiment. An RO-PUF compares nominally identical oscillators and uses their
frequency ordering to form response bits. Useful device-specific behavior must
come from manufacturing variation rather than a deterministic implementation
bias shared by the design.

The design has 32 ring oscillators split into two arms of 16. Arm A is placed
and routed as standard cells by the automated flow. Arm B uses sixteen
instances of one hardened oscillator macro. Both arms use the same oscillator
circuit, but their physical implementation is different. Each oscillator is a
31-stage ring: one enable NAND and 30 inverters, with a buffered tap for the
measurement core.

Oscillators are measured one at a time through a shared counter. A synchronized
start request clears the counter and opens a fixed 1000-cycle measurement
window (the hardware constant WINDOW; it is not externally selectable). The selected oscillator's edges are accumulated in an
asynchronous ripple counter. When the window closes, the oscillator stops; the
counter crosses a two-flop sampler and must produce three consecutive equal
samples before the frozen count and `done` are published.

A coherent nominal post-layout simulation of the current build predicts a
5.53% peak-to-peak spread in Arm A, associated closely with extracted routing
capacitance. Nine builds that vary only placement density put that number in
context: they run from 4.19% to 6.99%, median 5.75%. That build passes Magic
and KLayout DRC, XOR, LVS, antenna, detailed routing, and power-grid
connectivity with zero violations, so the prediction and the candidate GDS come
from the same flow run; the ring-oscillator STA warnings are listed separately
in SIGNOFF.
Arm B's sixteen instances reuse the same internal macro layout; its plotted
pre-silicon value is one extracted-macro result repeated sixteen times, not
sixteen separate measurements. The experiment will test whether Arm A's
centred frequency pattern repeats more strongly across fabricated chips than
Arm B's pattern. Cross-die repeatability, uniqueness, and security impact are
unknown until those measurements are made.

## How to test

Drive `clk` with a clean reference clock and release `rst_n`.

Keep `clk` running until `done`. If a measurement must be aborted, assert
`rst_n` or deselect the project (`ena=0`) before stopping the clock; either path
asynchronously shuts down the selected oscillator.

1. Select an oscillator: set the arm with `ui[1]` (0 = Arm A, 1 = Arm B) and
   the oscillator index with `ui[2]` through `ui[5]`.
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

There is no hurry over step 4. `done` stays high and the count is held until the
next start pulse, so the two bytes can be read as slowly as you like.

Repeat for each oscillator in both arms and collect repeated samples. Testing
the research hypothesis requires multiple physical chips measured under the
same controlled conditions, followed by repeated voltage and temperature
runs. The scripts and data-label convention are documented in `firmware/`.

## Choosing the reference clock

`info.yaml` declares 50 MHz and the measurement script in `firmware/` asks for
25 MHz. Both are correct and neither is a mistake. 50 MHz is the clock the build
was signed off at and the one the demo board starts with. 25 MHz is what I
recommend for characterization, and every count in the analysis assumes it.

The window is a fixed 1000 reference-clock cycles, so the clock sets how long an
oscillator is counted for and therefore how many counts you get:

    count = f_osc * 1000 / f_clk

At 25 MHz the window is 40 microseconds. The nominal post-layout prediction for
Arm A, 540.0 to 570.7 MHz, comes out as roughly 21600 to 22830 counts, and the
5.53% spread between the slowest and fastest ring is about 1230 counts. At
50 MHz the window is 20 microseconds and all of those halve.

Two things decide the clock. One count is the smallest difference the chip can
report, and at 25 MHz that is 44 parts per million against a per-ring mismatch
sigma of about 620 ppm from the Monte Carlo work, so a count is roughly a
fourteenth of a sigma. At 50 MHz it is 88 ppm and a seventh of a sigma. Slower
clock, finer measurement.

Pulling the other way, the counter is 16 bits and there is no overflow flag. It
wraps silently. Wrapping needs `f_osc * 1000 / f_clk` to pass 65535, so the
clock must stay above

    f_clk_min = f_osc * 1000 / 65536

The fastest ring in the simulated fast corner is 888.3 MHz, which puts that
floor at 13.6 MHz. At 25 MHz that same ring reads 35532, a little over half of
full scale, so there is close to a factor of two in hand for silicon coming out
faster than the model. At 50 MHz there is four times.

25 MHz is where those two pull evenly, and it is what the firmware uses. If you
run a corner that is faster than simulation suggests, raise the clock rather
than trusting a count near the ceiling. The script already warns above 65000,
but a wrapped count below that warning looks like a perfectly ordinary slow
oscillator and nothing will tell you.

## External hardware

A microcontroller such as the RP2040 on the TinyTapeout demo board can set the
control inputs and read the counter bytes. A stable reference clock and a way
to record supply voltage and temperature are needed for controlled comparison.
