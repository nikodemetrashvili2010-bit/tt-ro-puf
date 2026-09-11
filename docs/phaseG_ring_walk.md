# The ring check was blind, and the three-arm netlist has never been checked

10 September. Nikoloz asked whether the chip is good, and the honest way
to answer that is to list what has been verified and by what, rather than
what has been green. Doing that turned up a hole.

## What gate-level simulation cannot see

The gate-level job runs the real netlist, and since run 76 it passes the
protocol: sixteen measurements, one-hot enables, latching, restart,
reset. But it only ever selects Arm B. An Arm A or Arm C ring is a
zero-delay feedback loop in sky130's functional models, so enabling one
stops simulated time and the job would hang until GitHub killed it. That
is by design and `test.py` says so.

So gate-level simulation tells you nothing about whether the Arm A and
Arm C rings survived synthesis and placement intact. If `repair_design`
decided a ring net was too long and put a buffer on it, that ring is a
thirty-three stage oscillator instead of thirty-one, at a different
frequency, and every number the extraction predicts for it is wrong.

The only thing that can catch that is a check on the netlist itself.

## The check that was supposed to do that

`sim/spice/gono/verify_ring_topology.py` has been in the gate since
before Phase E. Its docstring says it asserts each ring is exactly one
`nand2_1`, thirty `inv_1` and one `buf_1`, "which is what would happen if
the flow buffered a ring net."

Two things wrong with that, one at a time.

It reads `dualarm/build_current/`, the two-arm netlist. It has never seen
a three-arm netlist. Runs 75 and 76 each produced one, and the only thing
that read either was `placement_fidelity.py`, which reads the DEF for
positions and never looks at a wire.

And it would not have caught a buffer anyway. It counts cells whose
instance name starts with the ring's hierarchy, `g_ro_bank[3].u_ro.`, and
checks their types. But the flow names a cell it inserts `fanout12` or
`hold79` or `wire3`, flat at the top level, with no hierarchy. The two-arm
netlist has 37 `fanout`, 79 `hold`, 3 `wire` and 9 `input` cells named
that way.

A buffer spliced into a loop would carry a name like that, would never
match the ring's prefix, and the census would still say 1 + 30 + 1.

I did not want to argue that from the naming convention, so I planted
one: a `buf_2` called `wire99` spliced between inverters 7 and 8 of ring
3 in a copy of the two-arm netlist, the ring's own wire cut and rejoined
through it.

    [ok]   Arm A bank 3: 1 nand + 30 inv + 1 buf, nothing inserted
    == SUMMARY == 16/16 Arm A rings structurally intact

Sixteen of sixteen, on a netlist with a buffer in a loop. The check had
been passing in the gate on every push since it was written and would
have passed on a broken chip. That is the shape the house style calls a
check that passes because it found nothing to check.

## Following the wire instead

The replacement walks. From each ring's `u_nand.Y` it takes the net,
finds what loads it, steps to that cell's output, and keeps going until
it arrives back at `u_nand`. Names are used for two things only, finding
the NAND to start from and recognising the tap buffer; the loop is
whatever is actually wired.

Every net it crosses is examined for every load, so a cell hanging off a
ring net without being in the loop is seen too.

Six checks per ring. The ring exists. The NAND is a `nand2_1`. The loop
closes on `u_nand.B` after exactly thirty inverters. Every one of them is
an `inv_1`. Nothing outside the ring touches a loop net, in the loop or
off it. Exactly one tap, `u_buf`, a `buf_1`, on a loop net.

Ten planted faults, each tripping exactly its own check and no other: a
whole ring missing, the NAND resized, an inverter dropped, the loop left
open, the loop closing on the wrong NAND pin, an inverter resized, the
spliced buffer, a fanout buffer hung off a ring net, the tap resized, the
tap missing. The selftest ends on the frozen two-arm netlist as its
real-input control.

On the planted netlist:

    [FAIL] Arm A ring  3: wire99 (buf_2) is in the loop on
           u_puf.u_core.g_ro_bank[3].u_ro.n[7]
    == SUMMARY == 15/16 rings intact (Arm A)

And on the real two-arm netlist, 16 of 16 by the walk. So the two-arm
build's rings are intact, which is the first time that has been shown
rather than assumed, and the SPICE and extraction numbers built on that
netlist stand.

Arm C rings live under `g_armc[N].u_roc` and number their inverters
from zero where Arm A numbers from one. The walk does not care, which is
the point of walking. `--arms AC` expects both; the frozen netlist is run
with `A` and a three-arm netlist run with `AC` fails if Arm C is missing,
rather than passing on an empty list.

The first version of the file had that prefix as `u_ro`, the same as Arm
A. Nothing in it could have said so: the fixture is built from the same
constant, and the only real netlist on disk has no Arm C. It would have
reported all sixteen Arm C rings missing under the title RING BROKEN, on
the first run that carried it. It was caught because run 77's box report
happened to print an Arm C instance name. The selftest now reads both
instance names out of `ro_puf_core.v` and fails if the constants drift.

## Where it runs now

Two places. `--selftest` in the archived-evidence gate beside the
existing line, which is now 122 commands. And a step in the gds job,
after the Arm A fidelity step and in the same shape, that reads
`runs/wokwi/final/nl/*.nl.v`, the netlist the GDS was cut from, with
`--arms AC`, and puts the result on the run page as a notice or an error
titled `RING BROKEN`.

Like the fidelity step it does not fail the job, so the precheck and
gate-level test behind it still run.

Run 77 is the first time any three-arm netlist gets this. Until it
reports, the honest statement is that the three-arm rings are unverified.

## Which nets cross the box, and a check that was reading the wrong thing

While the shell was down I worked out from the two-arm netlist what the
flow can still do inside the box after global placement is kept out of
it. Exactly thirty-two nets cross Arm A's boundary and no others: each
ring's `en` input, driven by an `and3_2`, and each ring's `out` tap, into
an `a22o_2` of the selector mux. In the two-arm build both of those gates
sat inside the rectangle, along with the fourteen resizer cells, none of
which touched a ring net; they served the decoders and flops that lived
there. The box has evicted those loads, so those cells go with them.

What is left is anything the flow does to the thirty-two crossing nets
themselves, which are longer now. A buffer inserted on one lands near its
driver or along the wire. Or the driver gets resized, `u_buf` from `buf_1`
to something wider, to drive the longer wire.

That second one exposed my own checker. `placement_fidelity.py` compared
origin and orientation. A `u_buf` resized in place keeps both, reads "in
place", and the arm is no longer the one that was extracted. F06 now
compares each cell's master against the frozen DEF, the file the
coordinates came from. Frozen control 512 of 512; a `u_buf` resized to
`buf_2` in a copy of it reads 511 of 512, one retyped, named.

## Run 77 named them, and it was not the resizer

Nikoloz pushed `run 76` while the shell was down. Its gds run, number
77, is green through precheck, `gl_test` is green at 7 of 7 for the
first time, and the box report came back with eleven foreign cells,
against 93 in the two-arm build:

    box 247480,70720 to 307740,171360 holds 74 taps, 1160 fillers
      and 11 other cells
    g_armc[13].u_roc.g_inv[2].u_inv  inv_1      at 307280,70720
    _334_              and3_2                    at 292560,111520
    _681_              dfrtp_2                   at 307280,114240
    _684_              dfrtp_2                   at 306360,136000
    _461_              a221o_2                   at 251160,155040
    fanout54           clkdlybuf4s25_1  TIMING   at 253920,157760
    clkbuf_4_10_0_clk  clkbuf_8         TIMING   at 266340,157760
    clkload1           clkbuf_4         TIMING   at 274620,160480
    clkbuf_4_11_0_clk  clkbuf_8         TIMING   at 274620,163200
    _691_              dfrtp_2                   at 306360,163200
    _338_              and3_2                    at 266340,168640

Two of those did all five moves. `_334_` stands at 292560,111520, which
is where ring 9's `g_inv[26]` was; that inverter went down a row into
ring 7's row, and ring 7's three went sideways and down to make room.
`clkbuf_4_10_0_clk` stands at 266340,157760, which is where ring 14's
`g_inv[11]` was.

So the section above, which reasoned its way to the resizer and the
thirty-two crossing nets, was wrong about the cause.

`_334_` is not a resizer cell. It is a netlist gate, one of the ring
enable decoders, and it is inside the box because the soft obstruction
is a density penalty to global placement and not a wall. A decoder whose
one output goes to a ring NAND inside the box is pulled there by that
wire hard enough to sit in the box anyway.

Legalization then ignores the soft box, hands the decoder the ring cell's
site, and moves the ring cell. Three flops spilled the same way, and the
clock tree put its buffers where the flops were.

Eleven is much better than 93, and it is not zero.

The dont-touch regex would have changed nothing. The rule not to pull a
lever before the run names the cause was right by exactly this much.

F06 did not run on 77; that checker is in the next commit. So whether
anything was retyped is still open.

## What would hold it

A hard obstruction, `PL_OBSTRUCTIONS`, that covers the box except the
sites Arm A's own cells and the tap cells stand on. Global placement
treats hard and soft the same, but legalization respects a hard one:
every site in the box is then either blocked or already holding an Arm A
cell, so a decoder that global placement left inside has to go to the
nearest free site outside, and so does a clock buffer. That is the next
change, and it wants two things checked at source before it is written:
how LibreLane 3.0.5 turns the variable into blockages, and what fill
insertion does with blocked sites. Not built today.

## Four pin functions the netlist had never run

Listing what the gate-level job exercises turned up a second gap, smaller
and cheaper. `gl_test` runs `test.py` only, and until today `test.py`
never selected a window other than 256, never read the version bytes,
never set the overflow flag and never picked a dead slot. The E.2
acceptance table does all four, in RTL, and every one of its rows uses
Arm A, which gate level cannot enable.

So on the real netlist the window mux behind `uio[2:1]`, the sticky flag
on `uio[4]`, the version bytes behind `uio[3]` and the two-bit arm decode
for a slot with no oscillator had never once been driven.

Four tests now in `test.py`, so they run in both modes. They land on Arm
B at gate level through `PROTOCOL_ARM`, and they compare windows to each
other rather than to a model, since the absolute count gate level gives
is the one number nobody has a basis for yet.

Window select 1 and 2 have to scale the 256 count by two and by eight,
within a boundary count each end. The 16384 window has to set the flag,
a following 256 run has to leave it set, and only reset may clear it.
`uio[3]` has to return 2 and then 0x1A, and dropping it has to return the
count that was there before. Slot 48, arm bits both high, has to finish
with a count of zero and no macro enabled.

RTL 11 of 11. The same file with the gate-level path forced, handles
gone and the window read off the pin, 11 of 11.

One fault planted against
each of the four, a wrong expected byte, a wrong ratio, the flag expected
clear, the dead slot expected nonzero, and each one fails only its own
test.

## Scope

This checks structure, not frequency, and not that a ring net's
capacitance matches what the extraction reads; those are the SPICE
phase's job and they are only as good as this check says the ring is.
Arm B is a sealed macro and is the physical flow's to check.

The walk
assumes each ring has one NAND named `u_nand` and one tap named `u_buf`;
a ring built differently would need the prefixes and those two names
changed, and nothing else.
