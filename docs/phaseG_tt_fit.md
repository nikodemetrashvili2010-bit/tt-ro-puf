# What Tiny Tapeout puts round the chip

Written on the evening of 4 October, alongside the timed run. The power
switch's drop was simulated on the 5th and that paragraph is marked. Landed
on 18 October with everything run again that day; the parts that changed
since the 4th say so where they are.

Everything so far had checked the chip as a block with eight inputs, a clock
and a reset. On silicon it is one tile group among hundreds, behind a
multiplexer and a power switch, driven by a microcontroller through an SDK I
had only ever met through a fake.

So I read the three sources that decide what the chip will actually see, at
the commits that were current that day, and wrote the reading down as a
script that fails when one of them changes: `sim/tt_fit.py`.

    tt-support-tools           01d5d28   20 August     precheck, the build
    tt-multiplexer             885086c   16 September  pads to project
    tt-micropython-firmware    d485c7a   8 September   the SDK, v3.1.1
    tt-gds-action, ttsky26d    395eedb   18 September  what CI runs
    ttsky-verilog-template     68c3fd3   30 September  the template

On 18 October none of the first three had moved on its default branch, and
the `ttsky26d` tag still points at `395eedb`. The template has one commit
since, `a42e666` on the 14th, a version bump in its devcontainer file.

Six things fit. One did not, and it was on the board, not the chip. It is
fixed since 17 October, see the DIP switch section.

## The layout against their precheck

Four of the precheck's functions run without a PDK install, and I called them
as they are on run 83's GDS, LEF and powered netlist: the pin check, the power
pin check, the cell name check and the analog pin check. All four pass.

The outline is my own few lines with their numbers. The layout's bounding box
and its prBoundary rectangle are both 334.88 by 225.76 um, the die of
`tt_block_2x2_pg.def`, the template the precheck picks for a 2x2 project, 43
pins.

The rest needs Magic, the KLayout program and the PDK's layer file: the two
DRC runs, off-grid, zero area, the layer check. CI ran those on run 83 and
they were green. What I can add is that they have not changed since. The
action at `ttsky26d` takes its tools from `main`, and `main` has not moved
since 20 August, four weeks before run 83 was built.

## The settings the build writes over ours

`create_user_config` in their `project.py` builds seven settings and lays
them over a project's own `config.json`: the design name, the source list,
the die area, the pin template, the two power pin names and the top routing
layer.

`src/config.json` sets none of the seven. Its other 34 stand, the macro
placement and the custom PDN script among them. I had not checked that
before; a setting of ours that they replaced would have been replaced without
a word.

## What a project that is not selected gets

In `tt_mux.v` every project's inputs come through `zbuf_iw_I`, which is
`tt_prim_zbuf`, which on sky130 is an `and2_2`: the signal and the project's
own select. The user module template then splits that bundle into `uio_in`,
`ui_in`, `rst_n` and `clk`.

So a project that is not selected has all four held at 0. `rst_n` low is
reset, and the chip's reset is `rst_n & ena` and asynchronous, so no ring can
run. That is what the datasheet promises about deselecting; now it rests on
their RTL and not on my reading of their documentation.

## A power switch nobody here had mentioned

This is the one I did not know.

Every project sits behind a power switch unless it says otherwise.
`placer.py` in the multiplexer reads `pg_vdd` with a default of True, picks
the low-leakage variant for anything up to four tiles wide, and the support
tools only ever turn it off for a whole shuttle (`no_power_gating`). A 2x2
project gets `tt_pg_1v8_ll_2`, and its control is `um_pg_ena`, the same
select that makes `ena`.

On the 4th the README, the datasheet and SIGNOFF mentioned it 0 times. The
datasheet has two paragraphs on it since the 18th, and `tt_fit.py` reads
`open` if they go, or if the reset the datasheet says the SDK gives on a
first enable is not the one in the SDK. The numbers in them are held by
`sim/verify_datasheet.py`, which reads the switch decks' logs for the
resistances and the drops.

Three things follow.

Deselected is unpowered, which is stronger than reset and costs nothing.

Selecting the project turns its supply on at the same moment its inputs come
alive, so every flop starts at whatever it likes. The 22 September sweep of
all 128 states of the seven enable flops found no second ring on in any of
them, so at most one ring runs until the reset comes. The SDK pulses reset
for 2 ms the first time it enables a project and `measure_puf.py` holds it
for 10 ms more, so a count never starts from that state.

And the rings' supply is the far side of the switch. The switch is one
`pfet3_01v8_hvt`, 3683 um wide in 508 fingers, and its own test bench draws
1 mA through it. The repo's figure for a running ring with its selector and
first flop is 0.688 mW at ff, about a third of a milliamp. The flow's power
report has the rest of the logic at 0.47 to 0.69 mW at the three nominal
corners, which is as much again.

On the 4th I had no device models to hand and wrote that the drop was not
simulated. On the 5th they were there for the selector decks, so I ran it:
that one transistor, turned on, with a current source where the project is.

    corner             switch     at 0.35 mA   at 0.7 mA   at 1 mA
    tt  27 C, 1.80 V   0.89 ohm   0.31 mV      0.62        0.89
    ss 100 C, 1.60 V   1.38       0.48         0.96        1.38
    ff -40 C, 1.95 V   0.61       0.21         0.43        0.61

Half a millivolt, give or take, with a ring running. That is the size of
what the chip's own rails and stripes already drop under a ring, 0.28 to
0.58 mV in `docs/phaseG_realworld.md`, and at the 105.88% a volt that note
works with it slows a ring by about 0.05%.

Every ring alike, though. The switch sits where the supply comes in, so
unlike the rails it does not know which ring is running, only how much
current it takes, and the rings differ in that by a few percent.

My first two tries at that deck were wrong. Written as the schematic has
it, 3683 um in 508 fingers, this ngspice found no model, because without a
compatibility mode it picks the bin by the whole width. Written as 508
devices of 7.25 um it gave 1.27 V of drop at 1 mA: I had put the 508 on
the model's own `mult`, which only scales its mismatch, and simulated one
finger. It is `m=508` on the instance.

That is the channel and nothing else. The switch's own metal and the grid
on both sides of it are not in the deck, and neither is what the supply does
while a ring takes its current in pulses. `docs/phaseG_realworld.md` lists
the Tiny Tapeout grid above the stripes as not settled, and the switch is on
that line now as well. A voltage label on a data file still names the board's
supply. The three decks and their logs are in `sim/spice/pg/`.

## The clock the board really makes

`measure_puf.py` asks for 50 MHz with `clock_project_PWM`. The SDK then looks
for a system clock that divides to it, and I ran its own search function on
the request: it sets the RP2 to 100 MHz and divides by 2. Exact, and half up,
half down. `info.yaml` asks for the same 50 MHz, which matters because the
SDK starts the clock from the shuttle index by itself whenever it enables a
project, before the script has asked for anything.

The exactness is the divider's. The 100 MHz is a PLL on the board's crystal
and carries the crystal's error, which the script already warns about when
the clock was not measured.

On the 4th the script did not write down what the SDK says it achieved,
though there is a property for it, `auto_clocking_freq`. It does since the
18th, beside the clock it asked for, with a warning when the two differ.

## The calls, and who drives what

All nine SDK names the script uses exist in v3.1.1, which is still the
newest. The board drives `uio` 1, 2 and 3, the chip drives 0, 4 and 5, and
no pin has two drivers. On the 4th nobody drove 6 and 7. The chip does not
read them, so they only floated as far as the pad. The board drives both low
since the 18th.

`enable()` refuses a project whose danger level is not safe unless it is
called with `force=True`, and returns False. On the 4th the script did not
look at what it returned, and the version read straight after would have
stopped the run with a message about version bytes and not about why. It
stops on the refusal itself now.

## The one that did not fit: a DIP switch left on

In the mode the SDK ships with, `ASIC_RP_CONTROL`, it looks at each `ui_in`
pin as it starts. A pin that reads high it leaves as an input, logs an error,
and carries on. That is the rule for the demo board's DIP switches: a switch
left on holds the pin high, and the SDK will not fight it.

From then on the script's writes to that pin go nowhere.

What that does depends on the pin. `ui[0]` is start, and stuck high there is
no edge, so every run times out and the file is full of -1. `ui[6]` is the
byte select, and the version read fails. Both are loud.

The other six are the arm and the index. One of those stuck at 1 and half the
48 selections measure the other half's rings: the row says ring 4 and the
chip counted ring 5. Every count looks right. Nothing in the chip, the SDK's
return values or the script noticed, and the analysis would have read sixteen
pairs of identical rings as a finding.

On the 4th `measure_puf.py` never read `ui_in` back and never looked at the
pin modes, and I did not change it that day, because it needed a test and the
fake board had to learn to hold a pin. That went in on 17 October. The script
drives every pin both ways with the project in reset and reads each write
back, so a pin it cannot drive stops the run with the bits named. `tt_fit.py`
prints `ok` for it now, where on the 4th it printed `open`.

## The checks checked

Eleven planted faults, each caught by the check that should catch it.

Five are from the 4th: an input pin moved one routing track along in the LEF,
which is their pin check saying so and not mine; the multiplexer's select
tied high, twice, for the inputs and for the switch; a clock the board cannot
divide to; and a direction mask that puts the board and the chip on one `uio`
pin.

Six are from the 18th and are the board side, each made on a copy of the
tree with one file changed, and each has to turn exactly one check `open`:
the datasheet's switch paragraph gone, the datasheet giving the SDK's first
reset as 5 ms where the SDK has 2, the achieved clock no longer written down,
what `enable()` returns ignored, `uio` 6 and 7 left floating, and `ui_in` no
longer read back.

As a control the same script read the firmware and the datasheet as they
were in `571c47b`, the day before. It printed `open` for the power switch,
the clock and the calls, and `ok` for the DIP switch, which is the order the
fixes went in.

My first planted pin fault was wrong. I moved one edge of the pin's rectangle
by half a micron on a pin 0.3 wide, which made a rectangle with its left
edge past its right, and their code fell over on an assertion of its own
before it got to comparing anything. A check that crashes is not a check
that caught something. It moves both edges now and the message is theirs.

## Run again on 18 October

Three fresh clones at the commits in the table, `gdstk` 1.0.1, and run 83's
final LEF and powered netlist from the PC: all seven checks `ok`. Before the
firmware and the datasheet changed it read as on the 5th, line for line,
except the DIP switch line, which said `ok` where the 5th's said `open`.

The three switch decks ran again on a fresh ngspice 42 and `sky130A` tree and
their logs came out byte for byte the 5th's.

One sentence here was wrong as written on the 4th: it put the flow's power
report at 0.47 to 0.69 mW "over the corners". That is the three nominal
corners. Over all nine it is 0.46 to 0.70.

## Not covered

The multiplexer's own timing: how long the clock takes from the pad to the
project, what the pads pass. Tiny Tapeout's site says 66 MHz and up to 10 ns
each way; I have no source for either here beyond their word.

The power switch beyond its channel, above.

Anything about the board itself, the package and the socket. The SDK is read,
not run: nothing here executed a line of it on a microcontroller, apart from
the one function that picks the system clock.

`tt_fit.py` is not in the evidence gate. It needs three of Tiny Tapeout's
repositories checked out and run 83's final views, and the gate runs on the
repository alone. `REPRODUCIBILITY.md` has how to run it.
