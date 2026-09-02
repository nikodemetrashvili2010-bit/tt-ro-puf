# Phase E.2b: the RTL, transformed from the live design

`chip/gen_e2_rtl.py`, `chip/e2_ro_puf_core.v`, `chip/e2_ro_puf.v`,
`chip/e2_tt_um_ro_puf.v`, `chip/e2_tb_plan.csv`. Written 2026-08-31,
thrown away and rebuilt 2026-09-02.

The first version of this script wrote the three modules from scratch out of
the pin spec. It read `OBSERVABILITY.json`, `ARMC_REGIONS.json` and the
acceptance table, and nothing else. In particular it never read the RTL it
was replacing, and that turned out to be the whole problem. What it produced
did not parse; it put the AND gate back on the counter clock that July
removed; it published the ripple counter before it had settled; it dropped
both clock-domain synchronizers; and it instantiated none of the sixteen Arm
B macros. Every one of those is something the live design had learned since
June, and every one of them was simply absent, because nothing in the
generator had ever looked at it. `chip/lint_rtl.py` found all five on
1 September, ten days after the fact.

So this version does not write RTL at all. It reads the three live files out
of `dualarm/src/` and applies a list of named edits to them.

**Partly simulated now, and say which part.** The rings themselves cannot run
in an event simulator, so the acceptance suite is still G.3's job. What did
run, on 2 September, is the counter, the sticky flag, the readout and the arm
decode, with the three ring modules swapped for behavioural oscillators and
the window driven from the pins. That covers E2-02, E2-09 through E2-13 and
E2-16/17. It does not cover anything about frequency, placement or the real
loop, and structure is still not behaviour.

## An edit, and why an anchor has a count

Each edit carries an id, a sentence saying what it is for, the exact text it
replaces, the text it replaces it with, and the number of times that text is
allowed to appear. If an anchor is missing, or appears a different number of
times, the script stops and names the edit and the file, and no edit in that
file is applied. Half a set of edits leaves RTL that is neither the live
design nor the intended one, which is worse than either.

That is the whole design. When somebody changes `ro_puf_core.v` next month,
this fails loudly instead of quietly reproducing the June version of it.

Twenty-four edits: eleven in the core, three in `ro_puf.v`, ten in the top.

## What the edits add

| | |
|---|---|
| arms | three, so `ro_sel` is six bits and `arm` is two |
| window | two-bit select over 256, 512, 2048 and 16384 cycles |
| overflow | sticky, cleared by reset alone |
| active | the window enable brought out |
| version | two bytes readable on `uo_out` in place of the count |

## What the edits must not disturb

- `assign tff_clk[0] = sel_ro;`, the ungated counter clock, and the paragraph
  above it that explains why, with a SPICE phase sweep behind the paragraph.
- The stopped-ring settle handshake: ST_SETTLE, the two-flop sampler, three
  consecutive equal samples, and `count_out = count_latched`.
- The control synchronizer in the top, which now has four more asynchronous
  pins to carry than it did.
- The sixteen `ro_macro_hard` instances, whose names are the placement keys
  in `config.json`.
- `ena` folded into the asynchronous project reset.

`R15` names those lines and requires them verbatim in the emitted files. The
fault that proves it is an edit that puts `sel_ro & en_window` back on the
counter clock: legal Verilog, no port changed, and nothing but a check that
knows the line is load-bearing can see it.

## The overflow flag, which took two goes

The first version hung the flag straight off `tff_clk[16]`, the carry out of
the top bit, set only and cleared by reset. That reads well and it is wrong
twice over.

The counter is cleared at the start of every measurement by `cnt_rst_n`. If
the previous run finished with bit 15 set, clearing it drives that bit from
one to zero, which is a rising edge on `tff_clk[16]` and looks exactly like a
wrap. A 2048 cycle window at the fast corner counts about 36400, so bit 15 is
set and the false trigger is not a corner case, it is most runs on a fast die.
E2-13 says a safe window never sets the flag and it would have failed on
silicon.

The second problem is the opposite one. Making it a seventeenth toggle bit
fixes the reset edge but toggles on every wrap, and the overflow window wraps
once at the slow corner and four times at the fast one. Four wraps read back
as no wrap at all. E2-11 says the flag is high on every die and every corner.

What is there now is a set-only flop in the ring domain, cleared with the
counter by `cnt_rst_n`, whose D is tied high so no data edge can catch it.
It rides into the xclk domain as bit 16 of the counter sampler, through the
same two `async_reg` stages and the same three-equal-samples rule as the
count, and the sticky part is one line in the settle branch that sets
`overflow` and is cleared only by `rst_n`. So the flag survives the next
measurement, which is E2-12, and a reset clears it, which is E2-02.

## The stimulus comes from the acceptance table

`chip/e2_tb_plan.csv` is generated from the 21 tests E.2 wrote, one row each,
with the arm, index, window select, version select, byte select and whether a
reset comes first. `R11` requires exactly one row per test and one test per
row. `R12` requires the stimulus to reach every window and every arm, which
is the failure mode where three of four modes are exercised and the fourth is
the one that breaks on silicon.

## Sixteen checks, one control, sixteen faults

The control is the one worth describing. Run the checks over the live design
with no edits applied at all, and R03, R04, R05, R06, R08, R09 and R10 have
to fail, because those are the checks that are about E.2 and Arm C and the
live design is neither. A check that passes on the design it was written to
reject is decorative, which is the lesson `G10` in the G.2 rule taught.
The rest pass, which is the other half of the same control: the preservation
checks say nothing bad about an untouched source tree.

`R14` is the anchor count. Its fault moves a line in the live file, and when
it fires the remaining checks do not run and the output says so, rather than
reporting fifteen consequences of one cause.

Two things worth not rediscovering:

- The R11 fault first dropped the last stimulus row. The last row is E2-21,
  the only one that exercises Arm C, so it tripped R12 as well and stopped
  saying which check had caught it. It drops a row by name now.
- `sampler_rhs` first took the first assignment to `ui_meta` it found, which
  is the reset value `11'b0`, and reported the whole control bundle as
  unsynchronized. The top has three `async_reg` registers and the first of
  them is the reset synchronizer, so the sampler is found by which register
  names `ui_in`, not by which comes first.

## The transformation is one-shot

G.3 step 2 copies these modules over `dualarm/src/`, which destroys this
script's own input. From that moment the live design is the three-arm design
and every anchor here points at text that no longer exists.

So the script checks for that first and says it plainly, rather than
reporting twenty-four anchor misses. And step 2 of the runbook now carries
the other half: in the same commit as the install, the four `gen_e2_rtl.py`
lines come out of `ci/gds.yaml` and the three `e2_*.v` drafts are deleted.
The gate diffs those drafts against a regeneration that can no longer happen,
so leaving them in would turn a finished job into a permanently red build.

`chip/lint_rtl.py` stays. Its live set becomes the three-arm design and its
draft set goes away, which is what it was written for.

## What the simulation said

Behavioural rings, `ro_macro`, `ro_armc` and `ro_macro_hard` replaced by
toggling models, half period chosen so a 2048 cycle window lands on 40000
counts. That is 0x9C40, bit 15 set and no wrap, which is the case the first
overflow design got wrong.

    win 2048 arm A -> count 40000 overflow 0
    win 2048 arm A -> count 40000 overflow 0     <- the second run is the test
    win  256 arm A -> count  5000 overflow 0
    win  512 arm B -> count 10000 overflow 0
    win  512 arm C -> count 10000 overflow 0
    win 16384      -> count 57856 overflow 1     <- four wraps
    win  256 arm A -> count  5000 overflow 1     <- sticky through the next run
    reset          ->              overflow 0
    version bytes  -> 2 and 0x1A

5000, 10000 and 40000 are exactly 1:2:8, which is what E2-09 and E2-10 ask
for, and 57856 is 320000 mod 65536 by hand. All three arms answer.

**Both rejected designs were rebuilt and both fail.** The naive flag, hung
straight off the carry and cleared by reset alone, reads 0 after the first
2048 run and **1 after the second**, from nothing but the counter clear, and
stays set forever: E2-13 dead. The toggle-bit version reads **0 after the
16384 window**, because four wraps toggle back to where they started: E2-11
dead. Neither of those was an argument I had to be talked out of; they are
both a line of output.

## Where it stands

All sixteen checks pass and all ten of `lint_rtl.py`'s do too, elaboration
and width warnings included. Yosys 0.33 reads the set, resolves the
hierarchy and passes `check -assert` with no warnings, which is more than
iverilog proves on its own. The testbench above is throwaway and is not in
the repo; writing the real one against `e2_tb_plan.csv` is G.3 step 4.

`info.yaml` is not emitted. It carries the tile count, the top module name
and the pinout, and it is the one file where a generated edit could quietly
change what gets manufactured. That edit stays manual and stays reviewed.
