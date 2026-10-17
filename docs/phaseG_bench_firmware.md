# The bench firmware catches up

18 October 2026. Five things `firmware/measure_puf.py` got wrong or left out,
found while writing the FPGA scripts on 10 and 12 October and reading Tiny
Tapeout's sources on the 4th, and two in `firmware/analyze_counts.py`. None of
it touches the chip. The two FPGA scripts already had most of these fixed;
the repository's own firmware had none of them.

## What changed in measure_puf.py

**It probes the board.** `mpremote run` soft resets the board before it runs
a file, and the SDK's `main.py` only runs from the friendly REPL, so on a run
started that way nothing had told the SDK which board and carrier it was on.
The SDK's README says to call `DemoboardDetect.probe()` before
`DemoBoard.get()`, and the script does now. A board whose `main.py` already
made a DemoBoard is not probed again, because the probe turns every RP2 pin
back to an input under the DemoBoard using them. The header records which
happened and what board the probe found.

**A stop prints.** Every stop was `raise SystemExit("...")`, and MicroPython
on the board prints nothing for a SystemExit, it soft resets. So the version
check, the missing project and the pin read back all ended a run in silence.
They raise a `Stop` now, caught once at the bottom of the file and printed as
a `# ERROR:` line. The reset and the clock stop still happen on the way out,
as before.

**It stops if `enable()` says no.** The SDK refuses a project whose danger
level is not safe and returns False. The script ignored that, carried on to
the version read, and would have stopped there with a message about version
bytes and nothing about the reason.

**It writes down the clock it got.** `auto_clocking_freq` is what the SDK
says it set the PWM to. It goes into the header as `clk_hz_sdk` beside
`clk_hz_requested`, with a warning line when they differ, since every count
scales with the clock.

**uio 6 and 7 are driven low.** The chip reads neither. Nothing drove them,
so the line between the RP2 and the pad sat wherever it drifted. The mask is
`0b1100_1110` now and the chip's own `uio_oe`, 0x31, still shares no bit with
it.

The header also carries the SDK's version string. The script version is
`measure_puf/6`.

## What changed in analyze_counts.py

The SDK prints its own log lines to the console before the script's header,
so a file straight off a board starts with lines that are neither comments
nor rows. The analyzer took the first line not starting `#` as the CSV
header, which on such a file was one of the SDK's, and every column came out
missing. It starts at the line that begins `run_id,` now.

A file with a `# ERROR:` line is a run that stopped, and the analyzer
refuses it with the reason. Before today a run cut short loaded whatever rows
it had.

Lines below the header that are not rows still fail, loudly, with a line
number. At its default log level the SDK prints nothing after the script
starts measuring; `clock_project_stop` logs at debug.

## How it was checked

`test_measure_puf.py` and `test_analyze_counts.py` are 33 tests now, 26 on
the 17th.

The new ones. A refused `enable()` stops before the board drives anything.
The probe runs once on a fresh board and not at all on one `main.py` set up,
and an inconclusive probe is written down while the run goes on. The clock
the SDK made lands in the header. `uio` 6 and 7 are outputs and only ever
driven low. And the analyzer reads a file with SDK lines above its header,
and refuses one that ends in an ERROR line.

The fake board prints an SDK-style line when the project is enabled, so the
end-to-end test that runs the firmware and loads its output into the
analyzer goes through the same shape of file a board would give. Before the
analyzer change that test failed on exactly that line.

The SDK calls were read in its source at v2.0.4, v3.0.0 and v3.1.1:
`DemoboardDetect.probe()` and `PCB_str()`, the singleton the script looks at,
`enable()` returning True or False, `auto_clocking_freq`, `version`. All of
them are there in all three.

Then the firmware itself under the MicroPython 1.22.1 unix port, with a fake
`ttboard` package written for it and three rounds instead of sixty. A whole
run, 144 rows, the probe called once and `uio_oe` at 0xce at the end; a wrong
version byte, a pin held high, a refused `enable()` and an unsure probe with a
clock off by 256 Hz, each giving the line it should. The output of the whole
run loaded into the analyzer with sixteen rings in each arm, and the wrong
version run was refused. That harness is not in the repository, it is the
fake and not the board.

`sim/tt_fit.py` reads the firmware too. Its clock and calls lines went from
`open` to `ok` with this change, and its selftest plants the faults these
fixes are for.

## Mistakes on the way

The new DIP switch test expected the first write to fail on 0xFF. The first
of the five writes is 0x00, which reads back 0x08 with bit 3 held high, and
that is where the run stops. The test was wrong and the firmware was right.

The first warning for an unsure probe said it "could not tell which board
this is". On SDK 2.0 the probe returns False for every RP2040 board from TT06
on, by design: it assumes TT06 when neither of its two tests is conclusive,
and its own boot prints "(best guess)" for the same case. So that line would
have fired on every RP2040 board from TT06 on. It says the probe was not
conclusive and what it assumed now.

In the MicroPython run my own fake printed a line after the rows, and the
analyzer stopped on it. That is the analyzer doing what it should with a line
it does not know, and the reason for the paragraph above about lines below
the header.

## Not covered

None of it has run on an RP2040 or an RP2350, or against the SDK's own code
with only the hardware faked, which the 10 October scripts had. The fake
boards keep the chip's pin protocol and not the SDK's internals.
