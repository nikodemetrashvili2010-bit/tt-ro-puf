# Phase E.2b: the RTL, generated from the spec rather than typed

`chip/gen_e2_rtl.py`, `chip/e2_ro_puf_core.v`, `chip/e2_ro_puf.v`,
`chip/e2_tt_um_ro_puf.v`, `chip/e2_tb_plan.csv`. Written 2026-08-31.

E.2 settled the pin map, the four window lengths and the acceptance table on
28 August. Arm C settled the sixteen regions and the sixth select bit on the
30th. Neither wrote a line of RTL, because `src/` has been proven unchanged
at the geometry-record level since 7 August and every edit there costs a full
re-verify. This writes the three modules the build installs, beside the
script rather than into `src/`, so the edit happens once inside the Arm C
build and G.3 pays for it once.

**None of it has been simulated.** Say that first, because the rest of this
page is about structure and structure is not behaviour.

## Generated, not transcribed

Every constant comes out of `OBSERVABILITY.json` or `ARMC_REGIONS.json`. The
four window lengths, the `uio_oe` byte, the protocol and build version, the
pin comments at the head of the top module, the select width: none of them is
typed into the Verilog and none is typed into the checker either.

That is the whole point. A spec and an implementation that were written
separately have two places to disagree, and the check that they match is a
comparison against a copy. Here the check reads the spec file and the emitted
text, so if the window table changes tomorrow, the constants change with it
and `R05` compares against what the spec now says rather than what it said
when somebody last looked.

## What the RTL adds

| | |
|---|---|
| arms | three, so `ro_sel` is six bits and `arm` is two |
| window | two-bit select over 256, 512, 2048 and 16384 cycles |
| overflow | sticky, set by the counter's own carry out of bit 15 |
| active | the window enable brought out |
| version | two bytes readable on `uo_out` in place of the count |

The sticky overflow is the piece worth reading closely. The counter is a
sixteen-stage asynchronous ripple, one toggle flip-flop a bit, each clocked
by the previous stage's inverted output. That chain already produces a carry
out of the top bit, `tff_clk[16]`, and its rising edge is exactly the wrap.
So the flag is one more toggle flip-flop clocked by it, set only, cleared by
reset alone. No comparator, no extra counter, and nothing to get wrong about
when a wrap counts.

`active` is `en_window` and nothing else. `R09` checks that it is wired
rather than tied off, because a flag that reads zero forever passes every
test that only looks for the absence of something.

## The stimulus comes from the acceptance table

`chip/e2_tb_plan.csv` is generated from the 21 tests E.2 wrote, one row each,
with the arm, index, window select, version select, byte select and whether a
reset comes first.

`R11` requires exactly one row per test and exactly one test per row, so a
test cannot exist without stimulus or the other way round. `R12` requires the
stimulus to reach every window the spec declares, which is the failure mode
where three of four modes are exercised and the fourth is the one that breaks
on silicon.

## Thirteen checks, and the two that needed fixing

Thirteen checks, all passing. Twelve planted faults on a fixture spec plus
one on the emitter and one on the parser.

Two of the checks were wrong on the first run and both were wrong in the same
direction, which is worth writing down: they were stricter than the design.

`R03` asks that every pin the spec gives a job to is actually read. It failed
on clean output, because the top takes `ro_idx` as a slice, `ui_in[5:2]`, and
the check was only counting bits named on their own. Four pins that are read
were being called unread. A check that is wrong about the design it reads is
worse than no check, so it counts slices now.

`R07` asks that every register a clocked block writes has an asynchronous
reset. The first version walked the module body with a regex that tried to
pair registers with the block that wrote them and got it wrong in both
directions. It splits the body into clocked blocks properly now, skips
combinational ones, and accepts `cnt_rst_n` as well as `rst_n`, because the
ripple counter is cleared through `rst_n & ~start` by design and calling that
unreset would be a false alarm.

One fault needed care. Dropping the `ro_puf` module entirely would have
tripped `R01` and also `R06`, because `SEL_W` is declared inside it, so the
fault renames the module instead and `R06` searches everything emitted rather
than one module. One fault, one check.

## What the build does with these

1. Install `e2_ro_puf_core.v`, `e2_ro_puf.v` and `e2_tt_um_ro_puf.v` into
   `src/` under their proper names, alongside `ro_armc.v` from E.1c.
2. Update `info.yaml`'s `source_files` and pinout to match the pin map at the
   head of the emitted top.
3. Lint, then run the gate-level tests, then work through
   `chip/e2_tb_plan.csv`.
4. Everything above is inside the Arm C build, so G.3 re-verifies the lot
   once.

## What is still open

The emitted RTL is unsimulated and it will have bugs. The arm decode in the
core uses a three-way one-hot built from comparisons against `N_PER_ARM` and
`2 * N_PER_ARM`, which is clear to read and is the kind of expression a
synthesiser can widen unexpectedly; check the elaborated width before
trusting it.

`info.yaml` is not emitted. It carries the tile count, the top module name
and the pinout, and it is the one file where a generated edit could quietly
change what gets manufactured. That edit stays manual and stays reviewed.
