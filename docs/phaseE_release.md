# Phase G.5: which script wrote which number, and from what

`chip/release_manifest.py`, `chip/RELEASE_MANIFEST.json`. Written
2026-08-31.

Phase E published a lot of figures. The free row area, the per-ring cost,
the corner span, the region geometry, the acceptance table. Each one came
out of a script that read some files, and each of those scripts has a
selftest that passed on the day it ran. None of that is the same as being
able to say, six months from now, where a number came from.

That is what this is. For every artefact the phase produced: which file
holds it, which script wrote it, which raw inputs that script read, and
whether those inputs are still the same files. If any link in the chain
cannot be named, the number is unsupported no matter how many checks passed
when it was written.

## What it says

Twelve produced artefacts across six generators. Two files frozen by hash
and deliberately without a producer. One file written by hand and checked by
a script but not hash-gated, which is the runbook and is its own category.
Ten raw inputs from `dualarm/build_current`, hashed.

    chip/      24 files, 9 scripts, 14 produced, 2 frozen
    gate       97 commands, 3 freeze checks
    raw inputs 10 hashed from dualarm/build_current
    actions    7, 0 pinned to a commit

## It failed on the first run, which was the point

Three checks came back red and all three were correct.

`S05` said four scripts were not in the evidence gate: `gen_e2_rtl.py`,
`preregister.py`, `release_manifest.py` and `g3_runbook.py`. True. Days 7
through 10 had been written and landed but the CI job had not caught up, so
four days of work were sitting in the repo with nothing running them.

`S09` said there were two freeze checks for two frozen files plus the A.5
one, and there should be three. True. `preregister.py --freeze-check` had
been written on the 31st and never wired in, so the hash gate on the
preregistration was a hash gate nobody was checking.

`S04` found `PREREGISTRATION_CHECK.json`, a scratch output from the day
before that had no business being committed.

None of those would have been noticed by any of the other nine scripts.
Every one of them checks its own subject carefully and none of them looks at
whether the thing that runs them all is complete.

## The bug that only shows up on the second run

The first run wrote the manifest, and the manifest included its own SHA-256,
taken from the copy on disk before the write. Run it again and it reads the
new file, records that hash instead, and produces a different manifest.
Every run disagrees with the one before, forever, and the `diff` in the gate
would fail for a reason that has nothing to do with the design.

A file cannot carry its own hash. The entry is recorded as null now, with
the reason in the source, and the manifest's integrity comes from the gate
regenerating it and diffing, which is the same guarantee one level up.
Regenerating twice now produces byte-identical output, which is a thing
worth testing rather than assuming.

There was also a plain mistake in `S03`. It iterated the artefact record
looking for producers and got the record's keys instead, so every artefact
looked like it had two. The clean fixture failed on the first selftest run,
which is exactly when you want to find that.

## What it will not say

The actions are not pinned. Seven `uses:` lines in the workflow and every
one of them points at a tag or a branch, `TinyTapeout/tt-gds-action@ttsky26c`
among them. A tag can move. The manifest reports this as a fact rather than
failing on it, because pinning the TinyTapeout action to a commit is a
decision about the shuttle relationship and not something to do quietly
inside a manifest script. It is written down so it is a choice rather than
an oversight.

Two of the ten raw inputs are not build outputs at all. `ro_macro_hard.lef`
is Arm B's hardened macro, which is an input to the build by design, and
`ARMC_COST.json` is this phase's own artefact that `gen_armc.py` reads.
Both are hashed because they feed results, and both are marked as carried
forward rather than regenerated.

## Twelve checks

All passing now. Ten planted faults on a fixture plus one direct test of the
gate parser against prose it has to ignore, and one on the commit-versus-tag
test.

The fixture is synthetic here rather than the real tree, because the thing
being tested is the accounting rather than any particular file, and a fault
planted in the real chip directory would mean deleting real work to see a
check fire.
