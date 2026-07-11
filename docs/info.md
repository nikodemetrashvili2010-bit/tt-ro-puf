<!---
This file is used to generate your project datasheet. Please fill in the
information below and delete any unused sections.
-->

## How it works

This is a ring-oscillator Physically Unclonable Function (PUF). A PUF turns the
tiny, uncontrollable differences between manufactured chips into a value that is
unique to each physical chip.

The design holds 32 ring oscillators, split into two arms of 16. Arm A is placed
by the automated flow; Arm B is built from hardened, matched oscillator macros.
Both arms are the same circuit, so any difference between them comes from layout.
Each oscillator is a 31-stage ring (one enable NAND plus 30 inverters), and its
frequency depends on manufacturing variation.

Oscillators are measured one at a time through a shared counter, which keeps the
measurement identical for every oscillator. A start pulse clears the counter and
opens a fixed window of `window` reference-clock cycles. During the window the
selected oscillator's edges are accumulated in an asynchronous ripple counter.
When the window closes the count freezes and `done` is asserted. The count is
proportional to the oscillator's frequency. Comparing counts between oscillators,
and between chips, is what reveals the layout-induced bias this project studies.

The chip is an experiment with a specific prediction. Simulation with the
flow's own extracted parasitics says the auto-placed arm's sixteen oscillators
spread about 5% peak-to-peak from routing capacitance alone, in a pattern
fixed by the mask and therefore identical on every die, while the matched
arm's sixteen copies sit at one frequency. If real chips reproduce this, the
auto-placed arm is shipping fake entropy and the matched macro is the right
way to build an RO-PUF on this flow.

## How to test

Drive `clk` with a clean reference clock and release `rst_n`.

1. Select an oscillator: set the arm with `ui[1]` (0 = Arm A, 1 = Arm B) and the
   oscillator index with `ui[2]` to `ui[5]`.
2. Pulse `ui[0]` (start) high, then low.
3. Wait for `done` on `uio[0]` to go high.
4. Read the 16-bit count as two bytes on `uo[7:0]`: set `ui[6]` low for the low
   byte, then high for the high byte.

Repeat for every oscillator in each arm and compare the counts. A faster
oscillator gives a higher count.

## External hardware

A microcontroller (for example the RP2040 on the Tiny Tapeout demo board) to set
the select and start lines and read back the two counter bytes, plus a clean
clock source on `clk`. No other external hardware is required.
