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
10.5% peak-to-peak spread in Arm A, associated closely with extracted routing
capacitance. That build passes Magic and KLayout DRC, XOR, LVS, antenna, detailed
routing, and power-grid connectivity with zero violations, so the prediction
and the manufacturable GDS come from the same run; the ring-oscillator STA
warnings are listed separately in SIGNOFF.
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
4. Read the 16-bit count as two bytes on `uo[7:0]`: set `ui[6]` low for the
   low byte, then high for the high byte.

Repeat for each oscillator in both arms and collect repeated samples. Testing
the research hypothesis requires multiple physical chips measured under the
same controlled conditions, followed by repeated voltage and temperature
runs. The scripts and data-label convention are documented in `firmware/`.

## External hardware

A microcontroller such as the RP2040 on the TinyTapeout demo board can set the
control inputs and read the counter bytes. A stable reference clock and a way
to record supply voltage and temperature are needed for controlled comparison.
