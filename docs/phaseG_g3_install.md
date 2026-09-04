# G.3 steps 1 to 6: freeze, install, document, lint, simulate

4 September 2026. Two days of the runbook's four and a half. The two-arm
design is archived, the three-arm design is installed in `dualarm/src/`,
`info.yaml` and the datasheet describe it, the RTL lints and elaborates, the
old protocol regression passes against it, and the twenty-one row E.2
acceptance table passes. Nothing has been hardened. Steps 7 to 12 need
OpenLane and machine time and are the next chip session.

## Step 1, and what the archive turned out to be for

`chip/archive_baseline.py` copies twelve files into
`dualarm/build_2arm_frozen/` and writes a manifest. Five `dualarm/src`
sources, the same five from the top-level `src/`, and both copies of
`info.yaml`. Eleven checks, eleven planted faults, each firing one check.

The obvious reason to do this is insurance: step 2 is irreversible and after
it the two-arm design exists nowhere. That was the whole of the plan when it
was written on 31 August.

It turns out to be worth more than that. `chip/gen_e2_rtl.py` is a
transformation of the live RTL, not a writer of fresh RTL, and its sixteen
checks include a control that runs them over the untransformed design and
requires seven to fail. After the install there is no untransformed design to
run the control against, and the 31 August plan dealt with that by retiring
the generator's commands from the gate and deleting the drafts they diff.
That would have thrown away sixteen checks, sixteen planted faults and the
control on the exact day they stopped being hypothetical.

So the generator reads `dualarm/build_2arm_frozen/dualarm_src/` when
`dualarm/src` already carries `g_armc`, and the gate keeps every command it
had. What the diffs point at changed: they used to compare a regeneration
against the drafts under `chip/`, and now they compare it against the files
installed in `dualarm/src/`. That is a stronger sentence. It says the design
going to the chip is exactly what transforming the recorded two-arm design
produces, and CI says it again on every run.

`G3_RUNBOOK.json` step 2 carries the revision and the paragraph it replaces.
The runbook was deliberately not frozen on a hash, and this is the case it
was left revisable for.

## The manifest has no date in it

The gate regenerates `MANIFEST.txt` and diffs it, so every line has to be
derivable from what is in the archive. A date is not. Git holds the date.

That is the same shape as `RELEASE_MANIFEST.json` recording its own hash on
31 August and disagreeing with itself on every run. A05 is the guard: no
hash may appear outside the manifest's two tables, and a file recording its
own sum is exactly a hash that belongs to neither.

I got A05 wrong twice before that. The first version looked for the
manifest's own hash inside the manifest, which cannot fire: append a hash and
the text changes, so the hash you appended is no longer the hash of the text.
The second version required every hash in the file to belong to an archived
copy or a recorded raw input, which does fire, and also fires on A04's fault
and A08's fault, because both of those leave a hash that no longer matches
anything. Splitting the file into its two tables and looking at what is left
over separates them cleanly. Three goes for one check.

## The line endings would have broken it in CI

Four of the twelve archived files are CRLF on disk. `.gitattributes` sets
`text eol=lf` for `.v`, `.json` and `.yaml`, so git rewrites them on commit,
and a byte-for-byte copy would have hashed one way on this machine and
another way in a checkout. Every hash in the manifest would have been wrong
in CI and right here, which is the worst way round.

The copies are normalized to LF on the way in and the manifest says so. A11
fails on any archived file carrying a carriage return.

## Step 2, the install

Four files: `chip/ro_armc.v` and the three `e2_*.v` over `ro_puf_core.v`,
`ro_puf.v` and `tt_um_ro_puf.v`. Then `dualarm/src` was resynced to the
top-level `src/`, which had been the June single-arm design since dual-arm v2
landed on 22 July. The archive records what that drift was before it went
away: five of the six paired files differed, `info.yaml` was the same in both
places.

The drafts under `chip/` stayed. The runbook said to delete them, on the
reasoning that the gate would diff them against a regeneration that can no
longer happen. It can happen, so they are kept and diffed against their
installed twins instead. This repository already carries a checked duplicate
of the whole source tree, `src/` against `dualarm/src`, and
`backup_to_repo.sh` has diffed that pair for months. A copy that CI compares
is not drift.

One thing did change in the generated text. The headers used to say the
modules were produced from `dualarm/src/<file>`, which after the install
points at the file itself. They name the frozen baseline now.

## Step 3, and the two consequences the runbook did not name

`info.yaml` gained `ro_armc.v` in `source_files`, a description of three arms,
and eight pin descriptions that were empty strings. Tiles stayed at 2x2 and
the top module name did not move, which are the invariants the step declares.

Then two things broke that the runbook says nothing about.

`chip/observability_spec.py` O05 asks whether the pins E.2 claimed were free
when it claimed them. It read the live `info.yaml`, so filling those pins in
made it fail. Widening the check to accept a named pin would have been
loosening a check to let an edit through, which is what freezing exists to
prevent, so it reads the frozen `info.yaml` from step 1 instead. Same move as
the generator, same reason.

`sim/verify_datasheet.py` failed harder, and it was right to. `docs/info.md`
is the TinyTapeout datasheet, it is rendered on the shuttle page next to
`info.yaml`, and it described a two-arm chip with a fixed 1000-cycle window
and, in as many words, no overflow flag. All three of those are now false.
The runbook's step 3 is called "source_files and pinout" and should have said
"and the datasheet and the firmware", because the datasheet is part of the
submission and the firmware is what drives the chip.

## The window replaces the clock as the knob

The old datasheet argued about the reference clock, because with a fixed
1000-cycle window the clock was the only thing that traded resolution against
headroom. It declared 50 MHz and recommended 25.

The window is selectable now, so that argument moves. `firmware/measure_puf.py`
asks for 50 MHz, which is what `info.yaml` declares and what the build was
signed off at, and selects the 2048-cycle window. 2048 at 50 MHz is 41
microseconds, against 40 for 1000 at 25, so the numbers barely moved: Arm A's
nominal 540.0 to 570.7 MHz reads 22119 to 23376 counts instead of 21600 to
22830, one count is 43 ppm instead of 44, and the fast corner reads 36385,
55.5 percent of full scale, instead of 35532 at 54.2.

What did change is what happens when a die is faster than the model. The
clock floor at 2048 is 27.8 MHz, so 25 MHz is no longer available at that
window. And `uio[4]` latches on a wrap and holds until reset, so a wrapped
count is now reported rather than inferred from how close to the ceiling it
sits. The firmware records the flag per sample and tells you to drop to the
512 window. The old near-ceiling warning is kept as a second opinion, because
a flag nobody reads is a flag nobody trusts.

The firmware also needed the arm's second bit on `ui[7]`, `uio[2:1]` driven
at all, and 48 selections a round instead of 32. It could not have driven
this chip as it stood.

`verify_datasheet.py` re-derives all of that. Twenty-three checks, and the
window it derives from is no longer a constant in the RTL: it is the RTL's
table of four read at the firmware's selection, so the firmware and the
hardware cannot disagree about which window the arithmetic assumes.

## Step 4, the lint

`chip/lint_rtl.py` had two file sets, live and draft, because they were two
different designs. There is one design now. The live set gained `ro_armc.v`,
which means R08, the check that Arm C is the Arm A ring node for node, stops
reporting `n/a` and starts running on what is going to the chip.

Ten of ten in the session container, E01 and E02 included, with the ten
planted faults isolated. Yosys 0.33 reads the same set, resolves the
hierarchy and passes `check -assert` with no warnings, which is not in the
gate but is worth having, since iverilog elaborating is a weaker claim than a
synthesiser accepting it. `dualarm/build_armc/lint.log` has the run.

Two fixture anchors in the selftest still named the seven-bit control
sampler. The bundle is eleven bits wide now. That is the kind of thing a
selftest catches on the first run after an install and nothing else catches
at all.

## Step 5, the regression

Seven tests, all of which passed on the two-arm build, all passing here. They
cover more than they did: 48 selectors instead of 32, and `uio[5]` compared
against the core's internal window signal on every cycle, so the new pin is
checked rather than assumed.

Arm C needs a behavioural model for the same reason Arm A does. A ring of
real cells is a zero-delay logic loop and an event simulator cannot run it.
`dualarm/src/ro_armc_sim.v` is Arm A's ladder shifted 100 ps faster at every
index. The number is a fiction and the file says so twice. What it has to do
is let the testbench see which arm a selector landed on, and identical models
could not.

The gate-level run is unchanged and still Arm B only, sixteen selectors of
forty-eight rather than of thirty-two. Arm C is in exactly the same position
as Arm A there.

## Step 6, the acceptance table

Twenty-one rows, one cocotb test each, driven from `chip/e2_tb_plan.csv`
rather than from a restatement of it. Each test looks its own row up by id
and fails on the lookup if the row is gone. 21 of 21 pass, 4.7 ms of
simulated time in 53 seconds. `dualarm/build_armc/sim_e2.log` has the run.

The rows worth naming: the 16384-cycle window sets the sticky flag on a
design where a safe window never does (E2-11 against E2-13, and E2-13 is 144
measurements, every safe window on every one of the 48 oscillators); the flag
survives the next measurement and dies on reset (E2-12, E2-02); doubling and
octupling the window multiplies the count by the same factor to within one
percent (E2-09, E2-10); and all three arms answer (E2-19, E2-20, E2-21).

Five of the twenty-one failed the first time and all five for one reason: I
compared the count to the model with `==`. The behavioural ring free-runs
from time zero and the window opens on a clock edge, so whether the last
period lands inside the window is a matter of phase. 512 cycles of a 1640 ps
half period is 3121.95 periods and the chip reports 3122, not the 3121 that
flooring gives. The tolerance is one count either way, the same one `test.py`
has always used, and it is a tolerance on the model of the ring rather than
on the counter, which is exact.

`chip/g3_runbook.py` gained B16: every row of the plan has a test in the
testbench, by name. B08 already checked that the table, the plan and the step
agree on 21, and three files agreeing on a number while nothing runs the rows
is the shape B07 was caught in on 31 August.

B16 also caught me out. Its planted fault passed on the first run while the
real check failed on all twenty-one rows, because the fixture hands the check
a list of ids and never goes near the reader, and the reader's regex did not
know that a cocotb test is `async def`. A fault that never touches the code
under test is not a test of it.

## What is not done

No build. Steps 7 to 12 are place, harden, XOR against the frozen GDS,
extract, re-run the evidence gate and re-cut the release manifest, and they
need OpenLane. `dualarm/build_current/` is untouched and its five raw files
still hash to what `RELEASE_MANIFEST.json` recorded, which is what A01 and
A02 check every time the gate runs.

The evidence gate is 109 commands, up from 100. Four for the archive, four
diffing the drafts against their installed twins, and one comparing `src/`
against `dualarm/src/` now that they agree. 106 of 109 pass in the working
tree; the three that do not are the two provenance checks that only pass
inside the clone and `lint_rtl.py` exiting 2 for want of a compiler on this
machine, all three of them the same as they were yesterday.
