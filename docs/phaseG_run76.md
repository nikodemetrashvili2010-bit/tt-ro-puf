# Run 76: 507 of 512, and one test that read the pins too early

9 September, commit `546ca14`, the soft obstruction plus the two test
fixes from run 75.

    archived-evidence   green    46s
    gds                 green   5m 12s
    precheck            green   2m 35s
    gl_test             red       39s
    viewer              red        7s
    test / test         green     29s

`test / test` is green for the first time since 4 September. `viewer` is
Pages, unchanged, one click in the repository settings. The other two are
the day's work.

## Arm A: 507 of 512 in place

The annotation, in full this time, because it is short:

    Arm A: 507 of 512 in place
    moved   bank[14] g_inv[11]  266340,157760 -> 264960,157760  (1.380 um)
    moved   bank[7]  g_inv[26]  294860,108800 -> 294860,106080  (2.720 um)
    moved   bank[7]  g_inv[27]  293480,108800 -> 295320,108800  (1.840 um)
    moved   bank[7]  g_inv[28]  292100,108800 -> 293940,108800  (1.840 um)
    moved   bank[9]  g_inv[26]  292560,111520 -> 292560,108800  (2.720 um)
    rotated bank[7]  g_inv[26]  FS -> N
    rotated bank[9]  g_inv[26]  N -> FS

(the names are `u_puf.u_core.g_ro_bank[n].u_ro.g_inv[m].u_inv`, shortened
here so the lines fit)

Run 75 was 64.

The soft obstruction does what the sources said it would. Global
placement stayed out of the box, and detailed placement left 507 cells on
the sites step 33 gave them. First time any placement mechanism has held
Arm A in this flow.

Five did not hold. They are in three rings and the shape of them says
something.

Ring 7 has two cells shoved right by 1840 dbu, four sites exactly, and a
third put down into the row below with its orientation flipped to match
that row. Ring 9 has one cell put down a row into ring 7's row, landing
in the gap the shove opened. Ring 14 has one moved left by 1380, three
sites.

Those are legalizer moves: the smallest displacement that clears an
overlap, sideways when there is room and into the next row when there is
not. So something was standing on ring 7 or ring 9 when detailed
placement ran, and something on ring 14.

It was not there at global placement. Global placement cannot put
anything in the box, which is the whole point of the box. It arrived
after.

The flow adds cells after global placement in three places: `repair_design`
at step 32, which buffers fanout and slew; clock tree synthesis; and
`repair_timing` after it, which inserts hold buffers. Any of the three
could be it.

This is not hypothetical. The two-arm build's own DEF has 93 cells inside
the same rectangle that are not Arm A, and 14 of them carry `SOURCE
TIMING`: eight `dlygate4sd3_1` hold buffers named `hold*` and six
`clkdlybuf4s25_1` fanout buffers named `fanout*`. The resizer put cells
in this region before, back when Arm A's own neighbours were in it. Now
that the box has emptied it of neighbours, the resizer is the only thing
left that can.

The annotation could not say which. So `placement_fidelity.py` now
reports the box as well as the arm: every instance whose origin is inside
the rectangle and is not an Arm A cell, with its master and its DEF
`SOURCE`. Taps and fillers are counted rather than listed, since they
belong there.

It is a report and not a check. On the frozen DEF it comes to 74 taps,
947 fillers and the 93 above, which is the placer's own doing and is not
a failure, so F01 to F05 are untouched and the frozen control still
passes 512 of 512. The selftest plants a tap, a filler, a `buf_2` marked
`TIMING` and a cell just past the right edge, and requires the first two
counted, the third named and the fourth left out.

There is a lever that could pre-empt a resizer buffer: `RSZ_DONT_TOUCH_RX`
on the Arm A instance and net names. It is the same lever run 73 built
and held back after run 74 showed it pointed at nothing.

Pulling it now would be pulling it at a guess. It does nothing about the
clock tree, and if the five are hold buffers it protects the wrong nets.
The next run names the cells. Then the fix is one line or it is a
different line, and either way it is aimed.

One more thing about the box, and it is not a defect.

In the two-arm build those 93 cells were the selector mux, the enable
decode, nine flops and the fourteen resizer cells, sitting between and
beside the rings. They are outside now. So Arm A's coordinates are the
extracted build's and its neighbours are not, while the SPEF the Phase D
and E numbers came from had those neighbours in it. That is the price of
the box rather than a fault in it, it is not undone by anything short of
removing the box, and it belongs in the paper's description of Arm A as a
limitation rather than in a footnote.

## gl_test: six of seven, and the seventh was a nanosecond

The gate-level netlist passed `test_power_on_defaults`,
`test_all_selectors_and_bytes`, `test_held_start_is_one_run`,
`test_selector_is_latched`, `test_restart_during_measurement` and
`test_reset_during_measurement`.

Sixteen measurements through the real counter and readout cells, the
sixteen macro enables one-hot on every cycle, the selector latched
against a mid-run change, a restart, a reset. That is the chip's protocol
working on the netlist the GDS was made from, and it had never been seen
before this run.

The one failure:

    assert 32 == 0
      where 32 = int(LogicArray('00100000', ...)) = tb.uio_out.value

`uio_out` 0x20 is bit 5, the measurement-active pin. The reporter did not
name the test.

It is `test_deselect_shutdown`, and 0x20 identifies it rather than
elimination doing the work: bit 5 is high only while a measurement is
running, and that is the only test which reads `uio_out` in flight. It
drops `ena` on a falling edge, waits one nanosecond, and requires the
pins quiet. RTL passes that because RTL has no delay. The netlist has
one.

`sky130_fd_sc_hd__dfrtp`'s functional model instantiates its flip-flop
primitive with `` `UNIT_DELAY ``, and the gate-level makefile passes
`-DUNIT_DELAY=#1`, one nanosecond at the models' `1ns/1ps` timescale.
Every flop's output moves one nanosecond after its clock or its reset.

Combinational cells have no delay in either view. That is the zero-delay
ring loop the same makefile's comment is about.

The deselect path is two flops deep: `ena` clears the reset
synchronizer, and the synchronizer's output clears the core, `en_window`
included. So the pin goes low two nanoseconds after `ena` falls, and the
test looked at one.

I built the path from the real models to be sure of the count. The first
version printed at three fixed probe points:

    +1ns  after ena=0: project_rst_n=1 en_window=1
    +2ns  after ena=0: project_rst_n=0 en_window=1
    +5ns  after ena=0: project_rst_n=0 en_window=0

That is enough to know 1 ns is too early and 5 ns is late enough. It is
not enough to know whether 5 has any margin. Read one way it says the pin
only just makes it, and I picked the quarter clock while believing that.

So I rebuilt it as the real path, cell for cell: `ena` through the
`clkdlybuf4s25_1` the netlist actually has on it, then the `and2` with
`rst_n`, then the two synchronizer flops, then the window flop. And I
recorded transitions instead of samples.

    ena falls at t, next rising edge is +10.0 ns
      gated reset       falls at +0.000 ns
      project_rst_n     falls at +1.000 ns
      en_window, uio[5] falls at +2.000 ns

Two nanoseconds, not five. The +2 line in the first run was a display
racing the flop at the same timestamp.

So the probe has to land after 2 ns and before 10, and the quarter clock
at 5 ns is the middle of that window with three nanoseconds of margin
behind it. Which is what I wanted, and had not actually shown.

The delay buffer contributes nothing, as expected. `clkdlybuf4s25`'s
functional view is two `buf` primitives and a power-good UDP, no
`UNIT_DELAY`, so its name is about silicon and not about simulation.

`ena` falls on a falling edge, so 5 ns is still five short of the next
rising edge, and the claim the test makes, that shutdown does not wait
for a clock, is the claim it still tests. The two `project_rst_n` probes
later in the same test get the same wait, for the same reason: one
nanosecond after a rising edge is exactly when a gate-level flop is
changing.

RTL is 7 of 7 with the change. The gate-level netlist is not in this
repository and the next gl_test is what runs it.

And the reporter now prints the `testcase` line above each failure, so
next time it names the test instead of leaving it to be deduced.

## Where that leaves the chip

Builds, prechecks, holds 507 of 512 Arm A cells, and passes six of seven
protocol tests on the gate-level netlist with the seventh explained to
the nanosecond.

Open on the chip path: the five cells, which run 77 names; Pages; and
Arm C, which waits on the five.
