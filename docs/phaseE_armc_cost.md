# Phase E.1b: what a third arm costs

`chip/armc_cost.py`, `chip/ARMC_COST.json`. Written 2026-08-26.

E.1's checklist wants area, routing, power, mux and interface cost for Arm C
before anything gets built. The way a study like that goes wrong is by
inventing its unit costs, so none are invented here. The die already carries
sixteen automatically placed rings and sixteen hardened macros wired into one
counter. Every unit cost is measured off them.

Yesterday's number is the budget: 17272.816 um2 of free row area.

## What one ring costs today

| | Arm A, per ring | Arm B, per macro |
|---|---:|---:|
| cells | 32 | 1 black box |
| standard-cell area um2 | 120.1152 | 0, plus 2400 of die |
| signal nets | 33 | 2 |
| routed wire um | 101.811 mean, 77.9 to 128.5 | 150.349 |
| wire capacitance fF | 14.0330 on the ring nodes | 20.6179 |

The Arm B line is the one worth stopping on. A hardened macro costs half
again as much wire per oscillator as an automatically placed ring, because
the sixteen macros are spread across a 240 by 184 um block and their enables
and outputs have to cross it. Hardening buys matched internals and pays for
it in interconnect.

## The spread Arm C exists to remove

The sixteen Arm A rings hold the same 32 cells and the same 120.1152 um2.
What the placer did with them is not the same at all.

| | value |
|---|---:|
| bounding box, smallest | 218.96 um2 |
| bounding box, largest | 382.87 um2 |
| bounding box, mean | 286.99 um2 |
| density, tightest ring | 0.549 |
| density, mean | 0.428 |
| density, loosest ring | 0.314 |
| rows spanned | 4 to 8 |

One ring is 24.84 um across and four rows tall. Another is 13.34 across and
seven rows tall. Same netlist, same cells, and a 75 percent range in
footprint. That is the free placement Arm A is a treatment for, and it is
what Arm C's equalization constraints have to take out.

It also sets the price. Under equalization every ring sits in an identical
fixed region and the region is charged whether cells fill it or not, so the
cost is 120.1152 divided by whatever density the constrained flow reaches.
Arm A's own three densities are the honest bracket.

## Arm C priced

| rings | density | region um2 | region total | plus decode | total um2 | of free |
|---:|---:|---:|---:|---:|---:|---:|
| 8 | 0.549 | 218.95 | 1751.6 | 141.7 | 1893.3 | 10.96% |
| 8 | 0.428 | 280.91 | 2247.2 | 141.7 | 2388.9 | 13.83% |
| 8 | 0.314 | 382.90 | 3063.2 | 141.7 | 3204.9 | 18.55% |
| 12 | 0.549 | 218.95 | 2627.4 | 181.7 | 2809.1 | 16.26% |
| 12 | 0.428 | 280.91 | 3370.9 | 181.7 | 3552.6 | 20.57% |
| 12 | 0.314 | 382.90 | 4594.8 | 181.7 | 4776.5 | 27.65% |
| 16 | 0.549 | 218.95 | 3503.2 | 221.7 | 3724.9 | 21.57% |
| 16 | 0.428 | 280.91 | 4494.5 | 221.7 | 4716.2 | 27.30% |
| 16 | 0.314 | 382.90 | 6126.4 | 221.7 | 6348.1 | 36.75% |

Every row fits. The worst case on the table, sixteen rings at the loosest
density Arm A ever managed, takes 36.75 percent of the free area and leaves
almost eleven thousand square microns behind.

Area is not what decides this.

## The load ladder priced

| rungs | load cells | cells um2 | loads um2 | total um2 | of free | loads as share |
|---:|---:|---:|---:|---:|---:|---:|
| 8 | 28 | 960.9 | 105.1 | 1207.7 | 6.99% | 8.7% |
| 12 | 66 | 1441.4 | 247.7 | 1870.8 | 10.83% | 13.2% |
| 16 | 120 | 1921.8 | 450.4 | 2594.0 | 15.02% | 17.4% |

Rung j carries j load cells, so M rungs need M(M-1)/2 of them. At sixteen
rungs that is 120 inverters, 450.4 um2, and the whole ladder still costs less
than the cheapest sixteen-ring Arm C.

It is cheaper for a reason worth being clear about rather than pleased with.
The ladder needs no placement constraint. Its load increments are
preregistered, so they go into the regression as a known regressor and
placement scatter goes in as residual. Arm C is expensive precisely because
constraining the placement is the treatment.

## Routing, which turns out not to be a constraint

| layer | routed um | capacity um | direction | tracks | pitch um | used |
|---|---:|---:|---|---:|---:|---:|
| met1 | 12736.6 | 222360.3 | horizontal | 664 | 0.340 | 5.73% |
| met2 | 7750.7 | 164353.3 | vertical | 728 | 0.460 | 4.72% |
| met3 | 4460.4 | 111180.2 | horizontal | 332 | 0.680 | 4.01% |
| met4 | 394.4 | 82176.6 | vertical | 364 | 0.920 | 0.48% |

25342.2 um of signal routing over 1110 nets, and the busiest layer is under
six percent used. Sixteen more rings at 101.811 um each is 1629 um, a 6.4
percent increase on the total and about a third of a percentage point on
met1. Routing does not decide this either.

Each layer's direction is measured, not assumed. met1 carries 12343.1 um
horizontally and 393.4 um vertically, met2 carries 97.7 horizontally and
7653.1 vertically, and so on down. The check requires at least ninety percent
of a layer's length in one direction and requires the DEF to declare tracks
running that way. Capacity is that track count times the die span the wires
run along. It is a ceiling nobody reaches, not a router's own congestion
estimate, so treat five percent as "there is room" rather than as a routed
result.

## Power, which is a rounding error

Leakage over the whole placed design is 2.66e-08 W, which is 0.4068 pW per
square micron. A sixteen-ring Arm C at mean density adds 4716.2 um2 and
therefore about 1.9e-09 W. Total design power is 5.58e-04 W.

Dynamic power does not move at all. One oscillator runs at a time, gated by
the window and the select decode, so a third arm adds oscillators that are
switched off whenever they are not the one being measured.

These figures are the clocked logic only. A ring oscillator is a
combinational loop, static timing analysis breaks it, and nothing in
`metrics.json` has ever seen one switch. The oscillator power is in the SPICE
work under `sim/spice/gono/` and it is not what this section is about.

## The mux, and the pin that two things want

The enable decode is 52 cells and 420.40 um2 today: one `and3_2` for each of
the 32 oscillators, plus 20 shared cells that predecode the five select bits
and the window enable. That cone was found by walking the transitive fanin of
all 32 enables back to `active_sel[4:0]` and `en_window`, and the walk is
required to stop there and nowhere else.

A third arm of sixteen makes 48 oscillators, which needs six select bits
instead of five. The per-oscillator gate grows from `and3_2` to `and4_2` and
there are sixteen more of them. The decode goes from 420.40 to 642.15 um2.
That is 221.75 um2, or 1.3 percent of the free area, and it is the same for
Arm C and for the ladder.

The interface cost is one input pin, and it collides with Phase E.2.

`info.yaml` has exactly one free input, `ui[7]`, and seven free
bidirectionals, `uio[1:7]`. The sixth select bit needs one pin. E.2 also
wants pins, for the window-length select, the sticky overflow flag, the
measurement-active flag and the protocol version. Both cannot have `ui[7]`.

The resolution is not difficult, and it is E.2's to make: the select bit
should take `ui[7]` because it is an input and it is on the critical decode
path, and E.2's additions should take the bidirectionals, which are free and
which mostly want to be outputs anyway. What matters here is that the
collision is on the record before either side designs around a pin the other
one has already spent. `ui[7]` was checked and is genuinely unconnected: it
is the one `ui_in` bit that never appears in the netlist.

## What this leaves open

One number. How many femtofarads a single load cell adds to a ring node.

The SPEF is written with `PIN_CAP NONE`, which the script reads out of the
header rather than assuming, so it carries wire capacitance and no gate
capacitance. The build has no file with the missing half. So the ladder's
rung spacing cannot be set from these files, and the honest bracket is what
the wire side already says: the ring nodes average 0.4527 fF of wire each,
the sixteen rings scatter over 10.86 to 17.04 fF with a standard deviation of
1.9155 fF, and the frequency slope on record is 4.94 MHz/fF. A rung spacing
has to be large enough that the ladder's top rung clears that 1.92 fF of
natural scatter by a wide margin, and 1 fF increments over sixteen rungs
would give a 15 fF span, which more than doubles a ring's node capacitance.

That is a SPICE question, `sim/spice/gono/gen_instance_decks.py` already has
the machinery for it, and it is a build-time number. It does not change any
area on this page and it does not block G.2.

The other limit is stated in one sentence because it matters: the density
bracket comes from what an unconstrained placer did to Arm A, and a
constrained flow could do worse than 0.314. If it does, the answer is a trial
build, not another spreadsheet.

## Checks and faults

Twelve checks, all passing. Nine planted faults on a fixture, each naming the
one check it must trip, plus three on the pricing model itself and one parser
refusal.

The one worth explaining is `C01`. This script needs to know which pin of a
cell drives its net, and it uses a stated table of sky130 output pin names.
A.1 was corrected in August for exactly that habit, so the table is not left
standing on its own: under it, every net in the design must have exactly one
driver, and the only nets with none must be the top-level input ports. Both
hold. 1110 nets, no net with two drivers, and ten undriven nets which are
`clk`, `ena`, `rst_n` and `ui_in[0]` through `ui_in[6]`. The absence of
`ui_in[7]` from that list is how we know the pin is free.

That is a global consistency argument, not a derivation. The derivation
exists: `extraction/ring_topology.py` reads each cell's own functional view
and works the directions out from the truth table, and it belongs in
`extraction/cell_library.py` once that module is split out. When it is, this
script should import it and the table should go.

`C04` and `C05` count sixteen rings and the fixture has one, so they are the
two checks the clean fixture is expected to fail. They are exercised by their
own faults instead, which is stated in the selftest output rather than left
for a reader to notice.

This script imports `tile_budget` for the DEF component parse and the width
recovery, which is one job and does not want two implementations. The
independent re-derivation of every number on this page is
`chip/verify_phaseE.py`, which shares no code with either.
