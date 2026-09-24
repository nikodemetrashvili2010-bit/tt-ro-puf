# Stress runs on the release netlist, and a hazard in the selector mux

22 September, evening. The question was whether the chip as built is safe to
make: nothing shorts, nothing burns, the logic does what the datasheet says
under abuse and not only under the eleven polite tests the gate runs. The
physical side (heat, current density, spacing, IR) was done on the 20th in
`phaseG_realworld.md` and I did not redo it. This note is the logic side, on
run 83's netlist in `dualarm/build_armc/`, and it ends with one thing I did not
expect to find.

Everything ran in a fresh container: iverilog 12.0, cocotb 2.0.1, and the
sky130A cell library at the commit `pdk.json` pins
(`8afc8346a57fe1ab7934ba5a6056ea8b43078e71`), the same one the gl_test action
installs. The eleven tests in `test/test.py` pass on the archived netlist there
in six seconds, 11 of 11, the same eleven CI reported green on run 80.

## All 48 rings, simulated

The gate-level job can only drive Arm B. The sky130 functional models give an
inverter no delay, so an enabled Arm A or Arm C ring is a loop that stops
simulated time, and `test.py` says so in its header. That is why nothing at
gate level had ever selected an Arm A ring, or watched two arms at once.

`sim/stress/make_stress_netlist.py` fixes that without touching the design. It
reads the netlist, finds the 32 cells of each ring by their instance names
(`g_ro_bank[i].u_ro.*` and `g_armc[i].u_roc.*`, 1024 cells in the top netlist
plus 32 inside the Arm B macro netlist) and swaps their masters for three
copies of my own with the same ports and an inertial delay of D picoseconds per
stage.

Every other cell, all 142 flops, the decoders, the counter clock mux, the tie
cells and the 419 taps, stays the sky130 model.

Each ring gets its own D so a count names the ring that ran: Arm A 26 + 2i, Arm
C 27 + 2i, Arm B 60 + i, all 48 distinct, half periods 806 to 2325 ps. The
script refuses a netlist where the counts are not 1040 and 32, and its selftest
plants three such.

The frequencies are fictions in the same sense as `ro_armc_sim.v`'s ladder.

What they let me do is predict every count to the count: the tap first rises 17
stage delays after the enable, then every 62, and when the enable falls the
NAND is forced high one stage later so at most one wavefront already past it
still arrives. So a run of W reference cycles on ring D counts n or n + 1 with
n = floor((20000 W - 17 D) / 62 D) + 1.

That bound held on every one of the several thousand runs below, once I had
found what else can add one (the hazard, further down).

`sim/stress/tb_stress.v` wraps the design with monitors on all 48 ring enables,
all 48 ring outputs, `uio[5]` and `uio_oe`, evaluated on every event after the
zero-delay gates of the timestep have settled: a second enable high, an enable
that is X, a ring output moving more than 4 ns after its enable fell, `uio_oe`
leaving 0x31, an enable high while the active pin says idle.

The tests read those counters at the end of every action. A monitor that fires
once anywhere fails the test that owns the time.

## The netlist read cold first

Before running anything I parsed the netlist with a throwaway script and asked
the safety questions structurally. None of this is in the gate yet; the ring
walk covers the loops and nothing covers the rest. That is an open item at the
end.

All 142 flops are `dfrtp_2`, every one with an asynchronous reset. Two (the
reset synchronizer) reset from `async_project_rst_n`, which is an `and2_2` of
the buffered `ena` and `rst_n` pins. Seventeen (the sixteen ripple counter
stages and the wrap flag) reset from `cnt_rst_n`, an `and2_2` of the buffered
project reset and the inverted start pulse. The other 123 reset from the second
synchronizer flop through chains of two to seven `clkdlybuf4s25_1` and `buf`
cells.

So `ena` low alone reaches every flop with no clock, which the first test then
watched happen.

The 48 ring enables are each one `and3_2`. The cone behind all 48 is the same
seven flops and nothing else: `active_sel[5:0]` and `active`, which is
`en_window` under the name the netlist kept. That matters for the power-up
question: whatever the flops come up as, the enable logic has 128 states and a
sweep of the 64 selector values with the window open, plus the window closed,
is all of them.

The counter clock, `sel_ro`, comes out of a 69-net tree whose cone is
`active_sel[5:0]` and the 48 ring outputs. `en_window` is not in it. The RTL
took the gate off the counter clock on purpose in July, because a gate there
could chop the last pulse into a runt, and synthesis did not put one back.

`uio_oe` is three `conb_1` HI cells and five LO, 0x31 exactly; `uio_out` bits
1, 2, 3, 6 and 7 are LO tie cells; `uio_in[0]` and `uio_in[4]` to `[7]` drive
nothing, the five disconnected pins the metrics report.

There are exactly 32 combinational loops in the top netlist, each of 31 nets,
the Arm A and Arm C rings; the sixteen Arm B rings are inside the macro. The
ripple counter is what the RTL drew: sixteen T flops, D from an inverter on Q,
each next clock from a second inverter on Q, the wrap flag clocked by the top
stage's inverted Q with D tied to a HI cell.

## Seven tests, four seeds

`sim/stress/stress.py`. About three minutes a seed on two cores. 7 of 7 on
seeds 1 to 4, `STRESS_N=150` random actions each.

**Power-up, deselected, no clock.** Every flop X, `clk` held low, `rst_n` high
(the host has not touched it), `ena` low. After 10 ns all 48 enables are 0 and
not X, all 48 ring outputs are known and do not move for 200 ns, `uio_out` and
`uo_out` are 0, `uio_oe` is 0x31.

Then `ena` high with no clock: nothing changes for 200 ns, because the release
goes through two clock edges. Then `rst_n` low with no clock: the same. Then a
clock, and the first measurement is a good one. So a deselected project draws
nothing and a selected one cannot start on its own.

**Every selector value.** 64 starts on the 256 window. Each real slot raised
exactly its own enable, once, and counted its own ring inside the bound; the
sixteen dead slots raised nothing and counted 0 with `done` rising as it
should. `max_pop` 1 throughout. Given the cone above, that is every state of
the enable logic.

**Random host, seeded.** Eight actions drawn by weight: a normal run on a
random slot and window; the same with the arm, index and byte select bits
wiggled while the run is on; a restart at a random point of a run; `rst_n`
dropped at a random sub-cycle offset mid-run; `ena` dropped the same way.

The other three: random noise on every control pin while idle, with a check
afterwards that nothing started and the stored count did not move; a start
pulse of 0.2 to 6 ns at a random phase, which may or may not be sampled and
must give a whole run or nothing; and version reads with random garbage on the
other bits.

After every action the overflow flag is compared with a model of the sticky
bit, `uio_oe` is 0x31, and the monitors are clean. On a reset or `ena` drop, 5
ns after the pin falls (no clock edge needed) every enable is 0 and both output
ports read 0.

Seeds 1 to 4 checked 87, 80, 100 and 88 completed runs, every count inside the
bound, no monitor offence, and zero delta-cycle events of two enables high, so
not even a zero-time glitch in the decode.

**The window changed under a run.** The window bits are read live by the timer
compare, not latched at start, and nothing in the datasheet says to hold them.

I switched 2048 to 256 with the timer past 600: the run went on until the
16-bit timer wrapped round to 255, `done` came 65197 cycles later, the ring was
on the whole time, the counter wrapped and the flag set, and the next run was
normal.

It ends on its own, which is the point; 1.3 ms of one ring is not a hazard. The
datasheet should say to hold `uio[2:1]` until `done`, one sentence.

**Reference clock at 100 MHz and 12.5 MHz.** The counts follow the model at
both, and the wrap flag comes when the model says: at 12.5 MHz the 2048 window
is 164 us and the fastest ring (D = 26) wraps while slots 31 and 47 do not; at
100 MHz nothing wraps on 2048.

The demo board tops out at 66.5 MHz. STA says the worst path at ss is about
10.8 ns on the 20 ns constraint, so 66.5 MHz leaves about 4 ns of setup there;
a cycle count, not a signoff, the flow only ever timed 50 MHz.

**Soak.** All 48 slots on the 2048 window back to back, then the 16384 window
on eight of them: 56 runs, 56 enable rises, every count in bound, the flag set
by every 16384 run and by no 2048 run.

**Restarts.** Below, because that is where the finding is.

## One extra count, and where it comes from

Seed 1, step 27: a restart landing on slot 41 read 1837 where the model allowed
1835 or 1836. I first put that down to the aborted ring's draining edge and
widened the bound for restarts. Then a directed sweep of 720 restarts (six old
slots, five new, gaps of 1 to 24 cycles) showed the extra count on every
restart onto slot 41 whatever the old slot and the gap, and on none onto 20, 6,
0 or 47 from a different slot. A drain edge does not care which slot comes
next.

So I traced the counter clock through the restart edge, and this is what one
timestep, E + 1 ns after the edge that takes a start, looks like in order:

    active_sel   010100 -> 101001      mux now looks at ring 41, static 0
    cnt_rst_n    0 -> 1                the counter's reset is released
    en_vec       ring 20 off
    sel_ro       0 -> 1 -> 0           the mux output pulses
    (1 ns later) counter reads 1

The pulse is the mux tree settling. With every ring output at 0 the tree is a
function of six selector bits that is 0 for all 64 values, but ABC built the
Arm C quarter of it as a product: `_448_` is an `and3_2` whose inputs are
`_191_` (1 for selectors 32 to 43, "Arm C and not index 12 to 15"), `_199_` (1
for 48 values, "not index 4 to 7", with ring data in it) and `_200_` (1 for 32
values, "not index 0 to 3 or 8 to 11").

The three are never all 1 at once, but on a transition the old value of one and
the new value of another can be, and then `_201_` pulses, `_471_` passes it to
`sel_ro`, and the ripple counter's first flop takes it.

`sim/ mux_hazard.py` finds this by evaluating the cone as 64-entry tables over
the selector and asking, for every cell whose output is constant 0, on which of
the 4032 transitions a mix of old and new inputs gives 1. One cell, `_448_`,
exposed on 832 transitions. Its selftest plants a two-cell hazard and a clean
twin and requires the one and not the other.

**23 September: that is wrong, and the script was wrong with it.** It only
looked at cells that are 0 for every selector value. A cell that is 0 at both
ends of one particular change, and 1 for some other selector, can pulse on
that change too, and a pulse can pass through a cell whose inputs are
themselves mid-change. Three-valued simulation of the whole cone catches both:
twelve cells where a pulse can start, `_448_` one of them, and 1728
transitions, not 832. Below, read 1728 where it says 832. The script is
rewritten and `docs/phaseG_hazard.md` has the rest.

Then I asked the same question of ordinary starts, not restarts: finish a run
on slot p, start slot q from idle, read the counter in the quiet cycle before
the window opens.

All 4096 ordered pairs, ten minutes. 192 of them begin the run with the counter
at 1, every one landing on slots 40 to 43 (Arm C, index 8 to 11), from the 48
slots whose index is not 8 to 11. That is the zero-delay simulator's particular
evaluation order picking 192 of the 832 the structure allows; silicon picks its
own by its delays.

In the 720 restarts, 142 began at 1 (129 of those read n + 2, the rest lost the
drain edge instead), and the restart of the same slot picks up the aborted
ring's own draining edge on 6 or 7 gaps of 24, which is the mechanism I first
blamed for all of it.

Why the paths are unequal in silicon is visible in the netlist too. The
selector predecode nets go through the `clkdlybuf4s25_1` fanout buffers the
flow inserted, the family behind the 291 slow-corner slew notes: `net43` is one
buffer from the `and2` of bits 0 and 1, `net42` is two, `net36` and `net37` are
on another branch.

A quarter to half a nanosecond between the three inputs of `_448_` at tt is
enough for a pulse that the flop resolves; the 17 September boundary work found
it counts 80 ps pulses. The reset release goes through `_294_` and then the two
delay buffers `fanout29` and `fanout30`, so it lands roughly 0.7 to 1.2 ns
after the edge, and the mux pulse roughly 0.8 to 1.8 ns after it.

Those are estimates from cell types, not a timed simulation, so the honest
statement is: the hazard is structural, the count it can add is exactly one,
and whether the reset is already released when it arrives is a race the design
does not decide. An SDF or SPICE run of the 69-net tree at three corners would
decide it and is a day of its own.

What it costs if real: one count on some slot transitions, 43 ppm at the 2048
window, about a fourteenth of a mismatch sigma, and deterministic per
transition, so it is a bias on particular rings in a fixed sweep order rather
than noise.

No pair is anywhere near it (the closest is 2.4 sigma) and a constant offset on
the same rings of every die changes no rank between dies, so M1, M2 and M4 do
not move. It is still an error the datasheet does not mention.

And it has a free fix. A second start on the same slot, after `done`, moves no
selector flop and finds the ring drained, so nothing in the tree transitions:
twelve such repeats began at 0 every time, after twelve first starts of which
six began at 1.

Starting each slot twice and keeping the second read costs a second 41 us per
slot and needs nothing from the chip.

The RTL fix would be a second quiet cycle, with the counter held in reset
through the first one and the enable raised after the second; it is small, but
it is a rebuild, a new gl_test, and a change to the E.2 acceptance table, for a
fourteenth of a sigma. I would not, and it is not mine to decide. Nothing here
is a safety matter: the pulse is 100 ps on a clock net that carries 570 MHz all
day.

`test_restart_carries_one_count` pins all of it: the counter in the quiet cycle
is 0 or 1 and never more, the count is n, n + 1 or n + 2 and never more, and
the repeated start begins at 0. If a rebuild changes the tree, that test and
`mux_hazard.py --expect-sites 1` say so. (That option is `--expect 1728` since
the 23rd.)

## Current, once more, with the one-hot proof in hand

The 20th measured one ring at the fast corner at 0.405 mW and a whole
measurement, ring plus selector plus first flop, at 0.688 mW, which is 0.38 mA
from 1.8 V. The rails carried 0.13 mA/um against 2.8 and the worst via cut 10
uA against 290.

The question a stress test has to ask is what happens if more than one ring
runs. Forty-eight at once would be 19.4 mW, 10.8 mA, and the worst rail segment
would carry 3.0 mA, 6.3 mA/um, over the DC limit.

So the rails are sized for one ring and the design relies on the enables being
one-hot. Above is why that is safe to rely on: the enable logic depends on
seven flops, all 128 of their states were driven, at most one enable was ever
high, and not for a delta cycle was a second one seen.

The most the mux hazard can do is add a pulse to the counter clock; it cannot
enable a ring. Tiny Tapeout publishes no per-project current limit that I could
find on the FAQ, specs, clock or PCB pages today, and 0.38 mA would not test
one if it did.

## Mistakes

- The quiet-cycle probe started watching after the start pulse was dropped.
  With the hold at 3 cycles that is just in time; with the random hold of up to
  8 the window was already open and the probe read 0 whatever the counter held.
  Seed 1, step 76 caught it, a plain start on slot 42 reading n + 2 with a
  clean probe. The watch now begins before the start is driven.
- The monitor counters live in the testbench and cocotb does not reset them
  between tests, so the soak test saw 148 enable rises for 56 runs. `setup()`
  zeroes them now.
- I wrote the restart bound as "the aborted ring's draining edge" and widened
  it for restarts only. The 4096-pair map showed idle starts do it too. The
  write-up above keeps both.
- The first netlist transform dropped the `en,` off the macro's module header
  and elaboration failed on all sixteen instances.
- Reflowing the testbench to 79 columns dropped the `cnt_rst_probe` line; seed
  4 caught it before anything was written to the tree.
- The Makefile put my netlist rule before the cocotb include, which made it the
  default target, and `make` reported the netlist up to date and ran nothing.
- One `await ReadOnly()` after an action that had already left the simulator in
  the read-only phase: cocotb refuses that, and the fuzz test died on it the
  first time through.
- The first draft of this note said `done` came 65191 cycles later, that the
  reset chains were one to five cells, and that CI had run the eleven tests on
  run 83. The log says 65197, a count of the chains says two to seven, and I
  have no log of 83's gl_test. Found re-deriving the numbers before the commit.

## Not covered, and open

Functional models with a 1 ns flop delay and zero-delay gates, no SDF, no setup
or hold checks: the counts prove logic and order, never timing. The ring
frequencies are chosen numbers. Arm B's macro is its netlist with the same
delayed cells, not a transistor model.

Random power-up values cannot be planted in these models, so the power-up test
starts from X, which is stricter for the reset chain and silent on what a flop
that came up at 1 would do before the first reset; the enable sweep is the
answer to that.

Open: wire `sim/stress` into the gl_test job after the action's own `make`,
with `NETLIST=../test/gate_level_netlist.v`; turn the structural checks of the
second section into a gate script with planted faults; the datasheet sentence
on holding the window bits; the firmware's second start per slot, or the RTL's
second quiet cycle, still to decide; a timed run of the mux tree to say whether
the hazard reaches the counter on this silicon.

23 September: the datasheet sentence and the second start are done, the
firmware's rather than the RTL's, which is the one I picked. The timed run
is `docs/phaseG_hazard.md`'s next part.
