# Is the chip ready to manufacture

16 September, the afternoon after Arm C got its placement. The question
asked was whether the whole chip, every part of it, works as intended
and can go to the shuttle without shorting, overheating or doing
anything else it should not. This is what was checked, what it found,
and what only a build can answer.

## The RTL, read end to end

Five files, `tt_um_ro_puf.v`, `ro_puf.v`, `ro_puf_core.v`,
`ro_armc.v` and `ro_macro.v`, plus the macro blackbox and the hardened
macro's own netlist. Read, not skimmed. What follows is what each part
does and why it cannot misbehave in the ways asked about.

Pins. `uio_oe` is `0x31`: bits 0, 4 and 5 drive, and those are exactly
the three the design puts a value on, done, overflow and active. Bits
1, 2 and 3 are read as inputs with their drivers off. Bits 6 and 7 are
neither driven nor read. So no pin is driven from both sides and no
input floats into logic. The unused `uio_in` bits go into a tie-off
wire and nowhere else.

Reset. `rst_n & ena` asserts the project reset asynchronously, so
deselecting the project on the board shuts an oscillator down even if
the reference clock has stopped. Release goes through two clock stages.
Every flop in the clock domain has that reset; the ripple counter and
the wrap flag have their own, held low during `start`.

One ring at a time. Every enable is `en_window & (active_sel == slot)`.
`active_sel` is one register holding one value, so at most one of the
48 enables is high, and `en_window` is low at reset and in every state
but RUN. That is the whole thermal story, below.

The 64:1 selector on the ring outputs. It changes only at `start`, when
every ring is off. A ring that is off rests with its NAND output high
and its buffer, tapped fifteen inversions later, low; the sixteen dead
slots are tied low. So while the select bits move every data input is
0, and an AND-OR mux with all-zero data cannot glitch high whatever its
select does.

The counter sees no edge it should not.

The counter. Clocked straight off the ring, no gate in the clock path,
one toggle flop per bit, wrap flag set-only off the top bit. Cleared
during `start`, quiet through ARM, counting through RUN, then the ring
is stopped and the value crosses into the clock domain through two
stages and has to read the same three times in a row before it is
published. A torn word cannot get out; the worst case is `done` staying
low.

The rings. Arm A and Arm C are node-for-node the same circuit, one NAND
and thirty inverters and a buffer on the middle node, and R08 in the
linter holds them equal. The hardened Arm B netlist is the same ring
with an input and an output buffer added by the hardening flow, both
outside the loop.

What is deliberately there and stays: `arm = 3` selects a dead slot and
finishes with count 0 and `done` high, no error flag. Documented, not
in the datasheet, harmless unless someone selects it.

## Run in the container

    cocotb protocol regression       11 of 11
    cocotb E.2 acceptance table      21 of 21
    lint_rtl                         10 of 10, 10 planted faults isolated
    evidence gate                    130 of 130

Yosys, on the same five files with the sky130 cells as blackboxes the
way the liberty makes them: `check` reports 0 problems before and
after synthesis, no latch inferred, no multiple driver, no undriven
wire. The cell count after synthesis is 32 NAND, 960 inverters, 32
buffers and 16 macros, which is 32 rings and 16 macros with nothing
merged or dropped.

The three Tcl files the flow sources at step 21, run under a real
`tclsh` with the OpenDB calls stubbed: 1024 distinct instance names,
512 Arm A and 512 Arm C, orientations MX and R0 only, status FIRM
only, sourced in order through `[info script]`.

## The frozen build's own numbers

From `dualarm/build_current/metrics.json`, the two-arm build that is
the physical baseline: Magic DRC 0, KLayout DRC 0, XOR 0, LVS 0 on
every count, antenna 0, route DRC 0 after six iterations, power grid
0 violations on both rails, worst IR drop 86 uV, setup and hold 0
violations at all nine corners with 12.05 ns of setup slack at ss and
111 ps of hold at ff.

Signed off already in `SIGNOFF.md`. Re-read today, not re-derived.

Known and accepted, not new: 140 max-slew violations at the slow
corner, none on a flop clock, reset, set or gate pin; one max-fanout;
two floating nets; nine disconnected pins, none critical. The thin one
is the last pulse of a ring stopped at exactly the wrong phase, 80 ps
measured against 77.5 ps characterised at ff, which is why the
three-sample handshake exists.

## Heat and shorts

The chip cannot get hot. One ring runs at a time, by the structure
above, not by convention. From the extracted parasitics of the frozen
build a ring's 31 nodes carry 11 to 17 fF of wire between them; add
about 3 fF of pin and drain per node and the ring is about 0.1 pF
switching once per cycle at 1.8 V. At 570 MHz that is 0.2 mW dynamic,
call it 0.3 mW with crowbar current, and under half a milliwatt with
the first counter stages and the selector path toggling behind it. The
fast corner at 890 MHz is about 0.5 mW. If every one of the 48 rings
ran at once, which the RTL cannot do, it would be around 15 mW on a
die shared with the shuttle's other projects.

There is nothing to dissipate.

Shorts. LVS clean means no net is connected to another that the
netlist does not connect. Power-grid connectivity clean means every
cell and all sixteen macros reach VPWR and VGND; the sixteen macro
power hookups are listed one per instance in `config.json` and were
counted. No two macros overlap on the grid (checked from their
coordinates and the 60 by 40 um size), and the sixteen Arm C regions
stand clear of the macros, of Arm A, of every fixed endcap and of the
soft box (K04, K05). Tap cells every 56 sites in every row, put in by
the flow, are what keep latch-up off the table, and Arm C's template
leaves their two sites free (K03).

## The one thing that was wrong

The workflows still pointed at `tt-gds-action@ttsky26c`. That is the
shuttle that closed on 7 September without this build. Every tag is
now `@ttsky26d`, six places across `gds.yaml`, `docs.yaml` and
`fpga.yaml`, which is what the shuttle's own factory-test project uses.

The tag is not only a name. At `ttsky26c` the action installs LibreLane
3.0.5 by default; at `ttsky26d` it installs 3.0.14.

So I fetched both versions and read what differs, file by file, before
accepting it.

Same at both: the PDK hash (`8afc8346`), the OpenROAD commit
(`dcf36133`, 17 February), the nix-eda and ciel locks, so every tool
binary behind the flow is the same. Same bytes: `placers.py`,
`classic.py`, `reader.py`, `pdn.tcl`, `cut_rows.tcl`, `tapcell.tcl`,
`gpl.tcl`, `dpl.tcl`, which is everything that cuts a row, places a
tap, sources `PDN_CFG` or moves a cell.

Different: `odb.py` and `openroad.py`, two and four lines, appending
`PAD_LIBS` to a liberty list, and this design has no pad libraries.
`common/io.tcl`, shims for an OpenSTA 3.1 API that the pinned OpenROAD
does not have, so the new branch is never taken. `pyosys.py` and
`synthesize.py`: the post-synthesis yosys check report now counts
toward `synthesis__check_error__count` alongside the pre-synthesis one,
and `abc` drops `-fast` only on a yosys newer than the pinned one. The
post-synthesis check on this design reports 0 problems here.

All of it is in `chip/FLOW_SURFACE.json` under `ci_version_change`,
hashes at both ends for every file, a reason for every difference, and
P01 now refuses a version move that lacks either. Three smaller
mentions of the old shuttle moved with it: the firmware's `SHUTTLE`
constant, the reproducibility note, the release-body template.

Not changed, by the standing rule that `dualarm/info.yaml` is not
mine to touch: its pinout still calls Arm C "equalized" in two places,
the header comment and `ui[7]`. The words are descriptive only and
the pin map is right, but the datasheet page is built from them and
they describe the treatment dropped on 7 September. One line each.

## What only the build can say

Nothing has run on 3.0.14, and nothing has run with Arm C placed. The
next push is the first of both, which is two changes in one run, and
the tag change was not optional. If Arm C does not hold, the file-level
comparison above is what says the flow version is not the reason.

The gds job will annotate three things: Arm A held N of 512, Arm C
held N of 512, and rings intact.

All three have to read full.

Still open and unchanged by today: the soft box, one run of its own
after this one; Pages, one click; the volunteer collector; the
research-design findings deferred until the chip is done.
