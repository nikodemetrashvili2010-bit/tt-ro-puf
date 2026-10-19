# The Tang Nano bench

19 October 2026. The chip's three RTL files, unedited, running on a Tang
Nano 9K, with an ESP32 on 23 jumper wires standing in for the demo board and
running `firmware/measure_puf.py`. The repository's own firmware had not
driven real pins against this design before. The FPGA lab run of 12 October,
at tinytapeout.fpgas.online, used a script written for that lab.

The protocol, the version check, the read back, the double start and the
analyzer all worked on hardware. The jumper wires did not, and no run of all
48 rings finished with every wire connected.

## The setup

The FPGA build is the one from 3 October. `ro_puf.v`, `ro_puf_core.v` and
`tt_um_ro_puf.v` are byte for byte the files in `src/`, and each ring is a
LUT stand-in of the same shape, an enable NAND and 30 inverters tapped at
stage 15.

The clock is the board's 27 MHz crystal. A LUT ring runs at about 22 MHz
here, so nothing below says anything about sky130 frequencies.

The ESP32 (an ESP32-D0WD-V3 board, MicroPython 1.29.0) runs measure_puf/6
with only the CONFIG block changed: chip id `fpga_tn9k`, condition
`fpga_27mhz`, the clock set to 27 MHz, and a note in the header saying the
counts are not chip data. Where the demo board has Tiny Tapeout's SDK, the
ESP32 has a small stand-in with the same calls that maps each chip pin to an
ESP32 pin.

uio[3:1] go over wires of their own here. On the lab's boards a Pmod HAT
joins them to ui_in[3:1], so the 12 October run never drove them.

None of the bench files are in the repository. Their hashes are at the end.

## The wire check

Before the firmware, a script called `bringup.py` goes through the 22 signal
wires and holds each one to a number the chip has to give: outputs at 0 in
reset, every ESP32 output reading back what it drives, the two version
bytes, a first count, the four windows scaling 1 : 2 : 8 : 64, done dropping
at a start and coming back one window later, one ring ten times, all 48
selections reading different rings, every uo bit seen both ways, and the
overflow line staying low.

**It failed a wire the first time.** Pin 30 to GPIO17, index bit 2: every
pair of selections that differ only in that bit read the same ring, 24 pairs
of 24. With that jumper swapped for a fresh one it passed all ten:

    version bytes            2 and 0x1a
    ring A0, four windows    209, 417, 1666, 13324
    start to done            621 us at 16384, 94 us at 2048
    ring A0 ten times        1666 every time
    48 rings at 16384        12733 to 13666, repeat range 2 (median)

The ratios are 1.995, 3.995 and 7.998. Both timings carry some MicroPython
overhead, which the difference cancels: 14336 cycles in 527 us is 27.2 MHz.

Two things it can not see. The overflow wire, because a LUT ring is about a
fifth of the 108 MHz it takes to wrap the counter at the 16384 window. And
two selection wires swapped with each other, since every selection still
reads a ring of its own, only under another number.

## Two runs, a wire lost in each

Both runs went through. 2880 rows each in 33 seconds, version bytes right, no
timeout, no zero count, no overflow, nothing garbled, and
`analyze_counts.py` read both files. Every ring repeats within one count over
the 60 rounds. The analyzer's WRAP warning on both is about the chip's
911 MHz corner and means nothing for rings at 22 MHz.

Then the data said something the firmware had not.

**Run 1.** Every selection with index bit 0 set read the same ring as the one
without it, all 24 pairs within a tenth of a count. Pin 28 to GPIO14 had lost
contact in the quarter of an hour or so between the wire check and the run.

**Run 2.** Every count was eight times too small, 199 to 214 where about 1660
was due. Window bit 1, pin 41 to GPIO15, had lost contact and the chip ran
the 256 window. On the 24 rings run 1 measured correctly, run 1 over run 2
comes out 7.968 to 8.000.

The firmware could not have caught either. Run 1 is the very case its
`ui_in` read back was written for, half the selections measuring the other
half's rings. But the read back sees the ESP32's own pin, and that reads what
it drives whether or not the wire still reaches the Tang Nano. The window
bits are not read back at all.

`analyze_counts.py` did see run 1, without knowing it. Its bit check pairs
index 0 with 1, 2 with 3 and so on in each arm, which are exactly the
selections that differ in index bit 0, and it gave bit error rates of 0.454,
0.407 and 0.290 on the three arms. Run 2 gives 0 on all three. Nothing in it
says why.

On the demo board those lines are traces, so this one belongs to the bench.
Still, a check for selections that differ in one bit and read the same ring
would work on any run's data, and it is not in `analyze_counts.py` yet.

So neither file is a clean set of 48 rings. Both are kept, renamed for what
went wrong in them.

## The first start

One thing came out of both runs anyway. The first start after a change of
selection reads high far more often than low:

    run   window   first minus second    -1      0     +1    +2
    1     2048                          168   1895    786    31
    2     256                            19   2084    772     5

About 27 percent of first starts land one count high at either window. That
fits a fixed extra edge at the switch rather than anything that grows with
the window.

It looks like the effect the firmware starts twice for, since 23 September,
keeping the second. This is a LUT selector though, not sky130's, and it says
nothing about how often the chip will do it. On 12 October the iCE40 build on
the lab's board, same RTL, came out at zero on average at the short windows.

## What else went wrong

- The stand-in written on 3 October could not have run measure_puf/6 at all.
  The firmware imports `ttboard.boot.demoboard_detect` since the 18th and
  reads `ui_in` back since the 17th. The stand-in had no such module, and it
  handed back whatever number it was given, so the read back could never
  fail. Fixed on the 19th before the bench, and tried under MicroPython
  1.29.0 against a fake board first.
- The PC had no driver for the ESP32's CP2102, so there was no COM port.
- One upload with `mpremote run` arrived garbled, a SyntaxError on line 88,
  which is `import random`. The next connection got 64 bytes of 0xFF where
  the start of the raw REPL reply should be, and the one after it nothing at
  all. From then on the firmware was copied onto the ESP32 with `mpremote cp`
  and run from its own flash, and it ran clean both times.
- Three jumpers failed in about forty minutes. 30 to GPIO17 was out at the
  first wire check. 28 to GPIO14 and 41 to GPIO15 lost contact after the
  check had passed, so those two were on the right pins and their plugs just
  stopped holding.

## What this shows and what it does not

It shows the protocol and the firmware working against the chip's logic on
real pins, with real timing: the version bytes, the read back, the double
start, 2880 rows without a timeout, a file the analyzer takes. And once, every
wire held to what the chip has to give.

It does not show anything about sky130, the ring frequencies or the overflow
flag. The SDK is not in it either; the 12 October lab run had the real one on
a real demo board.

There is no complete run yet. `bench_run.bat` does the check, the
measurement and the check again and will not measure if the first check
fails, and that is the next run.

## Files

On the bench PC, outside the repository, sha256 first sixteen digits:

    77466d6257849f58  Tang Nano bitstream, 3 October
    0a2420110252b8df  measure_puf.py, CONFIG only (repo copy b9707894...)
    93e4a88c583f1f8f  bringup.py
    f68f176f285014d5  ttboard/demoboard.py, the stand-in
    39ac38e9548a4bea  ttboard/boot/demoboard_detect.py
    e4b0efac210f60c0  bench_run.bat
    a4a03013bf4094d5  wire check, failing on pin 30
    34f4578f7db4ee7d  wire check, all ten passing
    85b3f2be1f8a81e8  the garbled upload
    7ebe4676730ff67d  run 1, index bit 0 off
    f445d38af3b7ab93  run 2, window bit 1 off
