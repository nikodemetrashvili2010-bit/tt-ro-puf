# Phase E.2: the observability spec, and the window that would have wrapped

`chip/observability_spec.py`, `chip/OBSERVABILITY.json`,
`chip/e2_acceptance.csv`. Written 2026-08-28.

E.2 asks for a selectable measurement window with at least two lengths, a
sticky counter-overflow indication, a measurement-active indication if it
earns its pin, a protocol and build version the collector can read, and
explicit tests proving reset, overflow, byte readout and every mode.

None of that is RTL yet. `src/` is untouched, as it has been since 7 August,
because every edit there costs a full re-verify and G.3 is where that gets
paid once, covering the Arm C build and these additions together. What this
day produces is the specification, checked against the current build, and the
acceptance tests generated from it.

## The finding

**The obvious window length wraps the counter at the fast corner.**

The counter is 16 bits and the reference clock is 50 MHz, so a window of N
cycles counts `f * N / 50e6` ring edges. The current build has one fixed
window of 1000 cycles, which at the nominal corner gives about 11000 counts
and looks entirely comfortable. The temptation is to add longer windows for
better resolution, and 4096 cycles is the natural next power of two.

The corner decks say no. Across the three SPICE runs in
`dualarm/build_current`, Arm A's sixteen rings span **276.19 MHz at the slow
corner to 888.31 MHz at the fast one**. At 888.31 MHz a 4096-cycle window
counts 72770 edges, and the counter stops at 65535. It wraps, and a wrapped
count reads as 7235, which is a perfectly plausible number for a slow
oscillator.

That is the failure the plan already names for the collector: a silent wrap
must be impossible to mistake for a slow oscillator. It is cheaper to design
out of the window table than to detect afterwards.

So the safe ceiling is not a judgement. It is `65535 * 50e6 / 888.31e6 =
3688` cycles, and the largest power of two under it is 2048.

## The four windows

| select | cycles | slow count | fast count | us at 50 MHz | role |
|---:|---:|---:|---:|---:|---|
| 0 | 256 | 1414 | 4548 | 5.12 | safe at every corner |
| 1 | 512 | 2828 | 9096 | 10.24 | safe at every corner |
| 2 | 2048 | 11313 | 36385 | 40.96 | safe at every corner |
| 3 | 16384 | 90501 | 291082 | 327.68 | overflows at every corner |

Three safe, in a 1:2:8 ratio, and one that always overflows.

The ratio is the point of having three. Absolute counts depend on the die and
the corner, and no acceptance test can predict one. A ratio between two
windows on the same oscillator on the same die does not depend on either.
Doubling the window has to double the count and taking eight times the window
has to give eight times the count, and a gating bug, a start-edge bug or a
wrap all break that immediately.

The fourth window exists because the sticky overflow flag cannot be tested on
silicon without a mode that sets it. 16384 cycles is the smallest power of
two that passes 65535 counts even at 276.19 MHz, so it overflows on every die
and at every corner rather than only on a fast one. A mode that overflows
sometimes would be a test that passes sometimes.

Both bounds are derived rather than picked, and the selftest re-derives them
by hand arithmetic that does not call the chooser, on three different
frequency spans, checking that the top safe window is the largest that fits
and that halving the overflow window would not have overflowed.

## The pin map

E.1b spent `ui[7]` on the third arm's second select bit, so everything here
comes out of `uio[1:7]`.

| pin | dir | use | who |
|---|---|---|---|
| ui[0] | in | start | existing |
| ui[1] | in | arm select bit 0 | existing |
| ui[2:5] | in | ro_idx[3:0] | existing |
| ui[6] | in | readout byte select | existing |
| ui[7] | in | arm select bit 1 | Arm C |
| uo[7:0] | out | readout byte | existing |
| uio[0] | out | done | existing |
| uio[1] | in | window select bit 0 | E.2 |
| uio[2] | in | window select bit 1 | E.2 |
| uio[3] | in | read version instead of count | E.2 |
| uio[4] | out | counter overflowed, sticky | E.2 |
| uio[5] | out | measurement active | E.2 |
| uio[6:7] | in | reserved | spare |

`uio_oe = 0x31`, which the script derives from the directions above rather
than being told.

Two pins are left spare. That is deliberate: E.3's collector work is out of
the manufacturing path and has not been designed, and finishing the pin
budget to the last bit before then would be spending on nothing.

## Does `active` earn its pin

The plan asks that, so: yes, and here is the case.

`done` goes high when a count is valid and stays high until the next start.
After a reset and before any measurement it is low. During a measurement it
is also low. So `done` alone cannot tell "never run" from "running", and
after a run it cannot tell a fresh result from one taken a minute ago without
the collector tracking state it may not have.

`active` is high exactly while the window is open. The pair separates all
three states, and it costs one pin and one wire, because `en_window` is
already the signal that gates the oscillator. The collector can watch active
fall and done rise in the same event rather than polling done and hoping.

## The version bytes

`uio[3]` high puts a version on `uo_out` instead of a count byte, and the
existing `ui[6]` byte select picks which one: low gives the protocol version,
high gives the build id. No new pin for the second byte.

Protocol version is **2**. Version 1 is the current build's readout, which
has no version register at all, so a collector that reads a byte and gets
something it does not recognise is talking to a chip older than the protocol
rather than to a broken one. Build id is **0x1A**, set by hand for the 26d
tapeout and recorded here; it is not derived from the netlist, because a
register whose value must equal a hash of the netlist it lives in cannot be
computed.

The rule that follows for the collector: refuse to record data whose protocol
byte it does not know, rather than guessing the format.

## Free pins are checked, not assumed

The check that took the longest to get right is the dullest one, and it was
wrong twice.

A pin is not free because its name is missing from the netlist, and it is not
busy because its name is present. `uio_out[7:1]` all appear, and every one of
them is driven by a `conb_1` tie cell holding it at zero, which is what an
unused output looks like after synthesis. `ui_in[7]` is the opposite: the
source ties it into an unused reduction, the optimiser deletes that, and the
name is gone from the netlist entirely. Reading either as "in use" or "free"
by name alone gets the answer backwards.

So an output is busy when the net driving it comes from something other than
a tie cell, or when a cell drives the port directly. `uio_out[0]` is the
second kind: it has no `assign` line at all, it is `.X(uio_out[0])` on a
buffer, and the first version of this check called `done` a free pin because
of it. An input is busy when it reaches some instance.

Under that reading, `ui[7]` and `uio[1:7]` are genuinely free and `info.yaml`
agrees with the netlist on every one of the sixteen. `busy_pins` has its own
selftest case covering all five shapes: tie-held output, cell-driven output,
output assigned from real logic, input something reads, input nothing reads.

## The acceptance table

21 tests in `chip/e2_acceptance.csv`, generated from the spec rather than
written out, so every mode is covered by construction. Seven kinds: reset,
mode, linearity, overflow, readout, version, state.

They are written as properties, not as expected numbers, everywhere except
overflow. A test that says "the count should be about 11000" is a test that
fails on a fast die and passes on a broken one. A test that says "the count
at 512 cycles is twice the count at 256, to within one percent" holds on
every die and breaks on every gating bug.

The three worth naming:

- the sticky flag survives the next measurement, so a collector that reads it
  after a batch still learns that something in the batch wrapped;
- the version select does not disturb a stored count, so reading the protocol
  byte between the two count bytes is safe;
- after reset and before any start, `done` and `active` are both low, which is
  a state no completed run can produce.

Twelve checks in the script, all passing, twelve planted faults each naming
the one check it must trip, plus the `busy_pins` case and the window
arithmetic re-derivation.

## What this does not settle

The RTL. This is a specification and an acceptance table, and neither has
been implemented or simulated. The gate-level tests that prove reset,
overflow and byte readout have to run against a built design, and that is
Phase E's build step, checked at G.3.

The window table assumes the reference clock is the 50 MHz `clock_hz` in
`info.yaml`. If the collector drives it slower, every count scales down and
the safe windows get safer; faster, and the ceiling moves down with it. The
spec should carry that as a stated operating condition and the collector
should record the clock it used, which E.3.3 already requires.

Arm B and Arm C ring frequencies are not measured here. The corner span used
is Arm A's, because that is what the three decks in `dualarm/build_current`
contain. A hardened macro that oscillates faster than 888.31 MHz at the fast
corner would move the safe ceiling, and checking that is one line of the Arm C
build's own verification.
