# Second look at the chip, against the tapeout checklist

17 September. The day after run 83 came back green with all three arms held,
the question was asked again, harder: triple check that every arm works as
intended, that the chip works as intended, and that when the order goes in it
will do what it is supposed to.

With it came a list of the things that kill ring-oscillator chips: loops
trimmed by synthesis, metastable readout, injection locking, ground bounce, pad
bandwidth, floating inputs, reset polarity, counter overflow across corners.

This is the second pass over the same chip, done without leaning on the
readiness audit from the 16th. Where I could run something, I ran it here
rather than reading the note that said it had been run. Where I could only
read, I say so.

## What was run today, from a fresh clone of `8f8939a`

    cocotb protocol regression      11 of 11
    cocotb E.2 acceptance table     21 of 21
    lint_rtl                        10 of 10, 10 planted faults isolated
    yosys, five files + blackbox    check clean before and after synth
                                    960 inv_1, 32 buf_1, 50 nand2_1
                                    (32 rings + 18 logic), 16 macros
    hook names vs fresh netlist     1024 of 1024, none missing, none extra
    fixed-cell geometry             0 overlaps in 1024, all on site and
                                    row grid, MX on even rows and R0 on
                                    odd, 0 inside a macro footprint
    corner arithmetic               re-derived, matches the datasheet

The yosys run used the sky130 hd liberty at tt as a blackbox library, `synth
-flatten`, `abc`, `opt_clean -purge`, the same shape as the flow's own script,
on this machine, not in CI.

The point was to see whether a generic synthesis with no special handling
leaves the rings alone. It does: the `keep` attributes and the explicit cell
instances survive, and every ring cell keeps the name the two hook files look
it up by.

The geometry check reads `arma_place.tcl` and `armc_fix.tcl` with its own
regex, puts every cell on a (row, site) grid three sites wide, and asks whether
any site is claimed twice.

None is.

Arm C's sixteen rings come out as 4 rows by 24 sites each, at x 258.98, 284.74
and 310.50 um, rows 10 to 21 below Arm A and 64 to 75 above it, which is the
column layout.

## The list, item by item

### Loops trimmed or merged by synthesis

The rings are not inferred from logic. `ro_macro.v` and `ro_armc.v` instantiate
`sky130_fd_sc_hd__nand2_1`, thirty `inv_1` and one `buf_1` by name, each with
`(* keep *)`, and the Arm C module keeps its wire vector too. Yosys treats
liberty cells as blackboxes, so ABC never sees the loop, and `opt_clean` cannot
remove a cell marked keep. That is what the 960 and 32 and 32 above show on a
plain synthesis.

What synthesis cannot do, the resizer can: `repair_design` may upsize a cell in
place or splice a buffer into a long net, and FIRM does not stop it.
`RSZ_DONT_TOUCH_RX` is unset in this design on purpose, one change at a time,
and instead the build is read after the fact.

Run 83's three annotations say Arm A 512 of 512 at coordinate, orientation and
cell, Arm C 512 of 512 with K17 zero resized, and rings 32 of 32 with every
loop 1 nand + 30 inv + 1 buf and nothing else on it. So on the GDS that exists,
nothing was trimmed, merged, retyped or buffered.

Arm B is a hardened macro and its netlist is on disk. It holds exactly one
nand2_1, thirty inv_1 and one buf_1, plus two `clkdlybuf4s25_1` the hardening
flow added as the input and output buffers, both outside the loop, and 162
decap_3, 18 fillers and 12 taps.

The GDS names the same cells.

One thing to be clear about: until today all three of those CI checks were
annotations. Each exited 0 whatever it found. A push where a cell moved, or a
buffer landed in a ring, would still have ended in a green `gds` job and a
green precheck, and the GDS the shuttle takes is whatever the latest green run
built.

That changed this afternoon; see the last section.

### Metastability in the readout

There is no fast clock domain that gets sampled while it runs. The counter is a
16-bit ripple chain clocked straight off the selected ring tap, and its value
is read only after the ring has been stopped.

At the end of the window `en_window` falls, the NAND holds the loop, the last
edge propagates out of the tap within about one loop traversal, and the ripple
settles a few nanoseconds later. The first sample the core will use is taken
twenty nanoseconds after that.

The crossing itself is two `async_reg` stages, `cnt_meta` then `cnt_sync`,
seventeen bits wide because the wrap flag rides along as bit 16, and the value
is published only when `cnt_sync` reads equal to its previous value three times
in a row. Counting it through: the window closes at edge E0, E1 and E2 are the
two forced settle cycles, E3 compares against a sample that may still be the
running-ring garbage from E0 and usually fails, E4, E5 and E6 agree, `done`
rises at E6. About 120 ns after the window at 50 MHz.

A torn word cannot get through; the failure mode is `done` staying low, and the
firmware has a 200 ms timeout for that.

The control path the other way is the same shape: `ui_in[7:0]` and
`uio_in[3:1]` go through `ui_meta` and `ui_sync`, eleven bits, and start is
edge-detected after the second stage. Reset release goes through two stages of
its own. Assert is asynchronous, which is what lets `ena` falling stop an
oscillator with the clock gone.

What remains is the one place metastability can still happen: the last ring
pulse before the stop, which can be any width, hits the first counter flop. The
flop either counts it or does not, so the reading is ambiguous by one count out
of about 23000. The signoff records 252 phases of SPICE through the real
selector and flop at ff, and B15 again at tt and ss, all resolving to a rail
with the count moving by at most one.

I re-read the number that sits under that. `SIGNOFF.md` puts the narrowest
pulse delivered at 80 ps against 77.5 ps characterised at `ff_n40C_1v95`,
margin 2.5 ps. The liberty says 77.5 ps for the high pulse of `dfrtp_2` at a 10
ps clock slew; the low pulse is 99.5 ps at the same slew, and both climb to 833
ps at a 500 ps slew.

At a realistic slew out of an `o21a_2` the characterised minimum is well above
80 ps.

So the 2.5 ps is not really a margin. It also does not need to be one. The
pulse is the last one, the flop's response to it is simulated at transistor
level rather than looked up, and whichever way it resolves the count moves by
one.

A metastable first stage that resolves through the inverter to the second stage
could in principle cost two counts instead of one, once in a very long while;
still nothing a stability handshake has to do anything about, and far inside
the 620 ppm per-ring sigma against 43 ppm a count.

### Injection locking between oscillators

Only one oscillator runs at a time, and that is structure, not protocol. Every
enable is `en_window & (active_sel == slot)`. `active_sel` is one six-bit
register, so at most one of the 48 compares is true, and `en_window` is a
single flop that is low in every state but RUN. The other 47 rings sit with
their NAND output held high, tap low, drawing leakage. Arm B's sixteen enables
come off the same register. The regression test that steps through every
selector checks the macro enables are one-hot on every cycle.

So the mechanism the checklist describes, adjacent free-running rings pulling
each other to one frequency through a shared supply, has no two rings to act
on. What does share the supply with the running ring is the 50 MHz reference
and its clock tree, and in principle a harmonic of that near 570 MHz could tug
the ring. It is the same for all 48 rings, the count averages 2048 clock
periods of it, and the PUF bit is a difference between two rings measured the
same way.

Not a threat to the entropy.

### Ground bounce and decoupling

The fill step runs with `sky130_fd_sc_hd__decap_3` ahead of `fill_2` and
`fill_1`, which is the flow's list for this PDK (read out of the June run's
resolved config; the design sets neither).

In the frozen two-arm DEF the Arm A box alone holds 947 fillers of which 706
are decap_3; run 83 reports 1137 fillers in the same box now. Each Arm B macro
carries 162 decap_3 inside its own 60 by 40 um. Endcaps are decap_3 as well.

Against that, the load: one ring of 31 gates switching at 570 MHz, about 0.1 pF
a cycle from the extracted parasitics, 0.2 to 0.3 mW, half a milliwatt at the
fast corner with the counter's first stages behind it. The static IR analysis
on the two-arm build puts the worst drop at 86 microvolts on VGND and 66 on
VPWR with the grid reporting zero violations on both rails. There is no
simultaneous-switching event on this die bigger than one inverter chain.

### Pad bandwidth

No oscillator signal reaches a pin. The tap goes to the selector, the selector
to the counter flop, and what leaves the chip is `count_latched` a byte at a
time on `uo[7:0]`, plus `done`, `overflow` and `active` on `uio[0]`, `uio[4]`
and `uio[5]`.

`active` is `en_window`, a 50 MHz domain flop. The fastest thing on any pad is
the reference clock coming in.

There is no divider because there is nothing to divide.

### Floating inputs and reset polarity

On the chip. `uio_oe` is a constant `0x31`, bits 0, 4 and 5 drive, and those
are the three the design puts a value on. `uio_in[0]` and `uio_in[7:4]` are
read into a tie-off wire and nothing else; in the two-arm netlist I parsed
every instance pin and every port and found no net with a load and no driver,
and the nine "disconnected pins" the flow counts are exactly the nine input
ports nothing reads. The three-arm design reads four more of them. Reset is
`rst_n`, active low, the TT polarity, ANDed with `ena` so deselecting the
project resets it, with the assert path asynchronous and the release
synchronised. Every flop in the clock domain has that reset; the ripple counter
and the wrap flag have `rst_n & ~start`.

On the board. This is the one real fault today, and it is in the firmware, not
the silicon. `measure_puf.py` writes the window select into `tt.uio_in` and
never sets `tt.uio_oe_pico`. In the TT SDK the RP2040 side of every
bidirectional pin comes up as an input with no pull (`RPMode.SAFE`),
`proj.enable()` with no project config sets `uio_oe_pico` to 0, and
`write_uio_byte` only takes effect on pins already configured as outputs. I
read all three in the SDK source.

So on the bench as written, `uio[1]`, `uio[2]` and `uio[3]` would have been
left high-impedance from the board side, the chip's window and version inputs
would have floated, and the first measurement would have used whatever window
those pins happened to read as. The fix is one line after `proj.enable()`,
`tt.uio_oe_pico.value = 0b0000_1110`, bits 1 to 3 out from the board, 0, 4 and
5 left as inputs because the chip drives them.

Applied, with a comment, and a sentence in the firmware README, which also
still said 32 oscillators in two places.

### Counter width across corners

Sixteen bits, ceiling 65535. Re-derived from the archived corner frequencies
(ss 276.19, tt 540.0 to 570.7, ff 888.31 MHz) at 50 MHz:

    window     us      ss     tt low   tt high      ff    ff wraps
      256     5.12    1414     2765      2922     4548     no
      512    10.24    2828     5530      5844     9096     no
     2048    40.96   11313    22118     23376    36385     no, 55%
    16384   327.68   90502   176947    187007   291081     4.4 times

Numbers agree with `docs/info.md` to the rounding of one count. The largest
window that never wraps at ff and 50 MHz is 3688 cycles, so 2048 is the right
data window, and at 2048 the clock can fall to 27.76 MHz before the fastest
ring at the fastest corner wraps once.

Below that, or on the 16384 window, the wrap sets `uio[4]` and it holds until
reset. It is set-only and ring-domain, so a die that wraps four times reads as
wrapped and not as clean, which is why it is not a seventeenth toggle bit.

The firmware reads the flag with every sample and warns.

## Things found that were not on the list

**The deadline moved.** `tinytapeout.com/chips/` today lists TTSKY26d under
future shuttles with a submission deadline of "Nov 2026" and delivery "Jun
2027". On 9 September the same page said December.

Still not open.

**The shuttle tag is a moving target, and so is the tools branch.**
`tt-gds-action@ttsky26d` resolves today to `b0b19a5` (8 September, "bump
default librelane version to 3.0.14"), the commit run 83 built with.

The action's `tools-ref` input defaults to `main` of `tt-support-tools` and the
workflow does not override it, so every build takes that repository at whatever
its head is that day. Neither is a problem for the chip as long as the
annotations are read on the run the submission points at.

**A restart during a window can cost a count.** `active_sel` changes on
`start`, and in the normal protocol every ring is off by then. If a second
`start` arrives mid-window, the old ring is still stopping while the selector
moves and the counter reset releases, and a glitch through the selector could
count. The datasheet protocol waits for `done`, the firmware waits for `done`,
so it does not arise; noting it so nobody "optimises" the wait away.

**The 140 slew violations are still unnamed.** `SIGNOFF.md` owes the list. The
count is 140 at ss, 44 at tt and 0 at ff, on a design with 79 hold buffers and
17 clock buffers, and the class that fits is the `dlygate4sd3` outputs on flop
D pins, which only add delay that STA already counts.

Not a risk to function with 12 ns of setup slack, but still a number in the
signoff without names behind it.

**`dualarm/info.yaml`** still said "equalized" for Arm C, and not in two places
but four: the header comment, the project description, the comment over
`source_files` and the `ui[7]` line. The description and the pin line are what
the datasheet page is built from. Nikoloz said to change them, so all four now
read hand-placed, in `dualarm/info.yaml`, the top-level copy the mirror makes
from it, and the clone, one hash for the three. The same words in the firmware
header went with them. `docs/info.md` and the README were already clean.

## Mistakes today

Three, kept.

My first walk back from the counter clock followed the selector's select inputs
into the state machine and the clock tree and produced 3800 lines that said
nothing.

The forward walk from each ring output, stopping at the first flop, is the one
that showed the tree: three to five cells of `a221o_2`, `a22o_2`, `a21o_2`,
`a211o_2`, `mux4_2` into one `o21a_2`, and the loads on every ring net exactly
one except the tapped node.

Yosys here mapped the ripple stages to negative-edge flops on Q, having folded
the inverter into the clock. For a moment that looked like a difference from
the design. The flow's own netlist uses `dfrtp_2` with an explicit `inv_2`
between stages, which is what the RTL says; the difference is a mapping choice
on a machine without `dfflibmap`, not a difference in the chip.

I took "80 ps against 77.5 ps, margin 2.5 ps" at face value for an hour before
opening the liberty table it comes from. The number is real and the comparison
is not a margin at any realistic slew, see above.

The conclusion did not change; the reason for it did, which is the rule about
reading a binding before repeating what it says.

## What this does not settle

Nothing here saw the three-arm netlist or DEF: those are in the run 83 artifact
behind the GitHub login, and every statement about them comes from the
annotations. No STA was re-run and no SPICE was re-run; the timing numbers are
the frozen two-arm build's metrics read again, and the min-pulse figures are
the library's. The gate-level test that ran in CI enables Arm B only.

## What changed in the gate, after the review

The three post-build checks can fail the job now. Nikoloz chose that when
asked, and it went into `ci/gds.yaml` in the working tree and the clone's
`.github/workflows/gds.yaml`, same bytes. Both placement scripts already took
`--strict`; the ring walk exits non-zero without `--annotate`, so it is called
twice, once for the run page and once for the verdict:

    python3 chip/placement_fidelity.py --def "runs/wokwi/final/def/*.def" --annotate --strict
    python3 chip/gen_armc_fix.py --verify-def "runs/wokwi/final/def/*.def" --annotate --strict
    python3 sim/spice/gono/verify_ring_topology.py --arms AC --netlist "runs/wokwi/final/nl/*.nl.v" --annotate
    python3 sim/spice/gono/verify_ring_topology.py --arms AC --netlist "runs/wokwi/final/nl/*.nl.v"

The yaml's own comment gave the reason they were left soft: a moved cell is a
result, and precheck and gl_test behind the job are worth having anyway. That
was right while the mechanism was unproven. With runs 80 and 83 behind it, a
moved cell or a spliced buffer is a build that must not ship, and a red job is
the only thing that stops the shuttle taking it. The comments in the file now
say both halves of that.

Exercised against the frozen two-arm build before landing, because a check
that cannot go red is the thing this project keeps finding. Arm A on the
frozen DEF: 512 held, exit 0. Arm C on the same DEF, where it does not exist:
K13 0 of 512, exit 1. Rings with `--arms AC` on the two-arm netlist: exit 1
plain, exit 0 with `--annotate`, which is why the second call is there;
`--arms A` on the same netlist, 16 of 16, exit 0.

The gate count is untouched: the sed range that counts it stops at `gds:`,
130 before and after, and all 130 ran green in the container with the new
workflow in place. Precheck and gl_test still depend on `gds`, so on a build
where an arm moves they will not run; that is the trade, and it is the right
one now.
