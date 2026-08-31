# Phase G.3: the order the Arm C build happens in

`chip/g3_runbook.py`, `chip/G3_RUNBOOK.json`, `chip/G3_RUNBOOK_CHECK.json`.
Written 2026-08-31.

G.3 is the expensive gate. It re-hardens the design with a third arm and
repeats the whole evidence suite, and the plan gives it three to five days
plus machine time. Everything Phase E has produced over the last ten days
exists so that those days get spent building instead of deciding.

What was left was the order. Twelve steps, each naming what it reads, what
it writes, what makes you stop, and whether it can be undone. The plan is in
the JSON; the script checks it against the artefacts that already exist,
which is the only kind of checking a plan can get before anyone runs it.

    1.  archive-baseline           0.25  undo: yes
    2.  install-rtl                0.25  undo: no
    3.  update-infoyaml            0.25  undo: no
    4.  lint                       0.25  undo: yes
    5.  sim-two-arm-regression     0.50  undo: yes
    6.  sim-e2-acceptance          0.50  undo: yes
    7.  place-regions              0.25  undo: yes
    8.  harden                     1.00  undo: yes
    9.  xor-baseline               0.25  undo: yes
    10. extract                    0.25  undo: yes
    11. rerun-evidence             0.50  undo: yes
    12. recut-release              0.25  undo: yes

4.5 days against a budget of 3 to 5, and the one day of that is the harden.

## Why this one is not frozen

`G2_CRITERIA.json` and `PREREGISTRATION.json` are gated on a SHA-256 because
changing either after the fact would change what the result means. A runbook
is not like that. A plan that cannot be revised when a step turns out to be
wrong is only a way of being wrong on schedule.

So it gets a checker rather than a hash, and the release manifest learned a
third category to hold it: written by hand, checked by a script, not frozen.
Two files are frozen, one is authored, twelve are produced. Everything in
`chip/` is now in exactly one of those or is a script.

## What the checks found

The plan as first written did not remake the three STA corner reports.
`B14` caught it. That matters more than it sounds: E.2 sized the counter
windows against a corner span of 276.19 to 888.31 MHz, and that span comes
out of `dualarm_par_ss_out.txt` and `dualarm_par_ff_out.txt`. Build a third
arm, forget to re-run static timing, and every window argument silently
still refers to the two-arm build.

The three reports come out of the harden step, not the extraction step,
which is why writing the plan step by step surfaced it and reading the
manifest never would have.

## Two checks reaching for the same thing

`B01` asks that every file a step reads is either already on disk or written
by some step. `B04` asks that no step reads a file a later step is the first
to write. On the first run a single planted fault tripped both, because the
order walk was also reporting reads of files nothing writes at all.

Day 1 hit this and merged three checks into one, because no fault could
separate them. This one is different: the two properties really are
separate, and the fix was to make the order walk mind its own business.
A read of something that never appears is an accounting problem. A read of
something that appears too late is an ordering problem. They fail for
different reasons and they get fixed in different places.

## The failure that means it worked

Step 11 re-runs the whole evidence gate, and one command in it is expected
to fail: the diff of the regenerated release manifest against the committed
one. The raw inputs are a different build by then, so the recorded hashes
are supposed to have moved. Step 12 is where the new manifest gets cut.

Writing that down as an expected failure with a named resolving step is
better than a stop condition that says "except this one", which is the sort
of soft clause that grows. `B15` requires every declared expected failure to
name a later step that actually writes the file in question, so the excuse
has to point at a fix.

## Fifteen checks

All passing. Fifteen planted faults on the committed runbook plus a direct
test of the order walk against a three-step toy worked by hand.

The fixture here is the real plan rather than a synthetic one, which is a
change from the other scripts in this phase. A fault planted in a made-up
runbook only proves the checks can read a made-up runbook. Using the
committed file means the clean pass at the top of the selftest is a
statement about the thing that ships.

## What this does not settle

Whether the build works. Every step here can be well-formed and the harden
can still come back with a timing violation, or the placer can reject a
region, or the arm decode can elaborate wider than expected. The checks buy
that no step reads a file that does not exist yet, that nothing overwrites
a file that was never archived, and that the re-run at the end covers
everything the gate covers now. They do not buy silicon.

The machine time is also not booked. The one-day estimate on the harden is
an estimate off the two-arm runs, and a third arm with sixteen pinned
regions may well take longer.
