# Triage of the flow's warning classes

`SIGNOFF.md` lists six classes of warning that the dual-arm build raises and
says each one needs per-net triage against the design before I order silicon.
Until now they were only counts. A count like "nine disconnected pins" is
something I can neither act on nor defend, because it does not say whether the
nine are chip pins I chose not to use or nine internal nets that lost their
connection during routing. Those two cases need completely different responses.

This is the triage. Every number below is re-derived from the shipped build by
`sim/spice/gono/triage_warnings.py`, which reads the DEF, the SPEF, the gate
netlist and `metrics.json` and refuses to agree with itself: each thing it
derives is compared against the number the flow recorded, and it exits non-zero
if any pair disagrees. It needs no ngspice, no PDK and no network, so a stranger
with a clone can run it. Fourteen checks, fourteen pass.

The important part is not that they pass. It is that most of these rules were
tested against a second build that returns different numbers, so a rule fitted
to one build would have shown up. More on that at the end.

## The nine disconnected pins

They are `ui_in[7]` and `uio_in[7:0]`. Nothing else.

Every one is a chip input that this design does not use, which matches
`info.yaml`, where `ui[7]` and `uio[1:7]` are blank and `uio[0]` is `done`,
an output. Not one of them is an internal net. The flow agrees on this from its
own side, since `design__critical_disconnected_pin__count` is 0.

The rule the script uses is that a DEF net whose only connection is a top-level
PIN reaches no instance. That gives nine on the shipped build. On the older
one-tile build in `dualarm/control_wokwi/` the same rule gives ten, and that
build's metrics record ten, and the extra one is `ena`, which the old design
left unconnected and the current one buffers through `input1`. Two builds, two
different answers, both matching. So this is not a rule I bent until it fit.

Unused inputs on a Tiny Tapeout project are harmless because the harness drives
every input pin. There is nothing to fix here and nothing to change.

## The one max-fanout violation

It is `clknet_0_clk`, the root of the clock tree, at a fanout of 16 against a
limit of 10. Its driver is a `sky130_fd_sc_hd__clkbuf_16`, the largest clock
buffer in the library.

What convinced me this is the tool describing its own work rather than a defect
is the fanout histogram. Twenty nets sit at exactly 10 and not one ordinary net
sits above it, because the resizer inserts repair buffers to hold them there.
Those buffers are even named for it: `fanout10`, `fanout12`, `fanout16` and so
on. Clock nets are built by CTS, which does its own sizing and is not subject to
that repair pass, so the one net that exceeds the limit is the one net the
repair pass never looked at.

The control matters here too. The wokwi build has no fanout violation at all,
and the script derives zero for it and metrics records zero. A rule that always
reported a violation would have reported one there.

I am leaving this alone. Raising the limit would hide it, and inserting a buffer
into a clock root to satisfy a constraint that CTS already handled would add
skew for nothing.

## The two floating timing nets

This one turned out not to be about my design at all.

`timing__drv__floating__nets` is 2 in the shipped build. It is also 2 in the
hardened macro, which has 226 instances. It is 2 in the standalone array at
3616, in the wokwi build at 4325, and in the old debug snapshot at 7319. Six
builds, spanning a bare oscillator to a full dual-arm block, three of which have
no disconnected pins and no unannotated nets whatsoever. The count never moves.

A number that does not depend on the design is not a property of the design. The
DEF says what it is: the SPECIALNETS section holds exactly two nets, `VGND` and
`VPWR`. Power and ground have no driver pin in the timing graph, so static
timing analysis counts them as floating in every build it will ever run.

Against that, `timing__drv__floating__pins` is 0, and the netlist has no net at
all that lacks a driver or lacks a load. I checked both directions separately.

## The 25 unannotated timing nets, and where I got this wrong

The nets that genuinely carry no parasitic annotation are the same nine as
above. The SPEF holds 1101 entries against the DEF's 1110, and the nine
missing ones are `ui_in[7]` and `uio_in[7:0]`. An unused input has no wire, so
there is nothing to extract.

The tool's own count is 25, which is sixteen higher, and my first explanation of
that gap was wrong in a way I want to keep in the record. I noticed the design
has sixteen black-boxed Arm B macros, wrote that 9 + 16 = 25, checked it against
`build_debug` where 10 + 16 = 26, and treated two agreements as a mechanism.

The wokwi build killed it. That build has zero macro instances, all 32 of its
oscillators are flat standard cells, and its offset is also exactly 16. So the
sixteen cannot be the macros. It is a constant of the flow that I have not
identified, and the script now reports it as an unexplained offset instead of
pretending to account for it.

The mistake is the same shape as the one item 2 recorded: an arithmetic
coincidence that survives because I only ever tested it on cases that agreed. I
have added a selftest for it, and the fix that mattered was running a control
whose design differs in the exact way the hypothesis depended on.

What lets me leave this open is that
`timing__unannotated_net_filtered__count` is 0 at all nine corners in every
build. The tool applies its own filter for nets it expects to be unannotated,
and after that filter nothing remains.

## The 140 max-slew violations

These are entirely a slow-corner effect.

    corner view          violations
    max_ff_n40C_1v95              0
    min_ff_n40C_1v95              0
    nom_ff_n40C_1v95              0
    min_tt_025C_1v80             22
    max_tt_025C_1v80             44
    nom_tt_025C_1v80             44
    min_ss_100C_1v60             93
    nom_ss_100C_1v60            117
    max_ss_100C_1v60            140

Zero at every fast view, and the count rises as the corner slows. That is what
weaker drive under slow silicon looks like. A routing or connectivity defect
would not switch itself off at the fast corner. The 140 that `SIGNOFF.md`
quotes is the worst single view, `max_ss`, not a sum.

The question I actually care about is whether any of this touches the
measurement. It does not. The heaviest nets in the design are the clock tree and
the reset and enable distribution, 81.24 fF on `net32` off a `clkbuf_8`, 75.04
on `_105_`, 66.99 on `net33`, and so on down. Every one of the top five is a
repair-buffered net sitting at fanout 10. The 496 Arm A ring nets, which are the
thing this chip exists to measure, carry between 0.107 and 1.838 fF. The
heaviest ring net is 44 times lighter than the heaviest net in the design. The
same holds in the wokwi build, where the ring nets reach 4.748 fF against 28.68.

Slew on those nets is also not what sets the frequency. The SPICE work measures
the rings against their extracted parasitics directly, at all three corners, and
that is where the frequency numbers come from. Static timing analysis has no
clock defined on a free-running ring, so its opinion about transition times on
those nets was never load-bearing.

What I cannot say is which 140 pins they are. That needs the per-corner timing
reports, which are not in the archived bundle, only in my local run directory.
Pulling them across is the one piece of this triage still owed, and it is
mechanical.

## The 461 lint warnings

Zero lint errors and zero timing constructs, so nothing here blocks anything.
The 461 is a warning count from Verilator.

`src/config.json` sets `LINTER_INCLUDE_PDK_MODELS` to 1, which is Tiny Tapeout's
default and one of the values the file explicitly tells you not to change. With
that on, the linter reads the PDK's own cell models alongside my RTL.

The wokwi build reports 461 as well. That build is a different design: one tile
instead of four, 32 flat oscillators instead of sixteen flat and sixteen
hardened, 4325 instances instead of 6477, no macro at all. Two designs that
share almost nothing above the cell level, and an identical warning count. The
debug snapshot gives 462. So the count barely responds to my RTL, which points
at the PDK models as the source.

That is an inference from a control, not a proof. Naming the 461 needs the
linter log, which lives in the same local run directory as the timing reports.

## What this ran against, and one side result

Every rule above was checked on the shipped build and on at least one build that
returns a different answer for it. The wokwi build gives ten disconnected pins
instead of nine and zero fanout violations instead of one, and the script
matches its metrics on both. That is the part that makes me trust the rules,
rather than the fourteen passes on their own.

The full wokwi run is 119 MB and stays out of the repository, so the four files
the triage actually reads are archived in `dualarm/control_wokwi/`, 2.1 MB, and
CI runs against those. They should never be updated. A control that tracks the
shipped build has stopped being a control.

`triage_warnings.py --selftest` plants eleven faults and all eleven are caught.
Three are worth naming. One plants routing coordinates where connections belong,
which is the bug that inflated every fanout in my first version of the parser
before I noticed the clock net at 219 sinks. One plants a capacitance unit
error, because a SPEF read as femtofarads when it says picofarads is off by a
thousand and still looks like a number. One plants a net missing from the SPEF
that is not an unused input, which is the case that would have caught the
unannotated mistake earlier.

The side result is that `dualarm/build_debug` fails three of the fourteen
checks. Its DEF has 25 nets with no SPEF entry, and its fanout derives as 9
against a recorded 1. `SIGNOFF.md` already says that snapshot is not a coherent
bundle, on the strength of `verify_build_bundle.py` finding its DEF and netlist
describe different checkpoints. This reaches the same conclusion from a
different direction, without being told to look for it.

Tool and record: `sim/spice/gono/triage_warnings.py`, with the full derivation
in `sim/spice/gono/triage_warnings.json`.
