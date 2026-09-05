# The gate had been red for five pushes

5 September 2026. Today was supposed to be G.3 step 7, the placement
constraints, and it is not. Before touching that I looked at what GitHub
thought of the 4 September push, and GitHub thought it had failed. So had the
four before it.

One hash, one file, and a rule about line endings that this repo already knew
about and applied in one place and not the other.

## What the runs say

`gds` is five jobs. `archived-evidence` runs the evidence commands and every
other job needs it. Run 65, on 20 August, is the last one where anything was
built:

| run | pushed | archived-evidence | gds |
|---:|---|---|---|
| 65 | 20 Aug 10:36 | pass, 25s | 4m 44s |
| 66 | 31 Aug 17:48 | FAIL, 38s | skipped |
| 67 | 31 Aug 18:21 | FAIL, 41s | skipped |
| 68 | 1 Sep 19:31 | FAIL, 54s | skipped |
| 69 | 2 Sep | FAIL, 53s | skipped |
| 70 | 4 Sep 17:50 | FAIL, 1m 5s | skipped |

Every one of those five says `Process completed with exit code 1`. So the
last GDS CI has built is the two-arm design from 20 August, and Phase E, the
RTL transform, the lint work and the three-arm install have all landed on a
repository whose gate was refusing them.

Run 65 was not clean either, for unrelated reasons that are still open. Its
`gl_test` exited 2 after 36 seconds and its `viewer` returned 404 because
Pages is not enabled. Neither is today's problem and neither is fixed here.
Both are written down at the end.

## Reproducing it

The failure does not happen on this machine and it does not happen in the
local clone. It happens in a checkout. So: clone the repository into the
session container, install iverilog the way the workflow does, pull the
`archived-evidence` command list out of `.github/workflows/gds.yaml` and run
all 109 of them in a loop that reports every line instead of stopping at the
first red one.

Three failed:

    diff /tmp/tile_budget.json chip/TILE_BUDGET.json
    python3 chip/release_manifest.py --json /tmp/release.json
    diff /tmp/release.json chip/RELEASE_MANIFEST.json

and the diff was one line:

    "macro_lef": "1c7442880aca9290..."   recomputed in the checkout
    "macro_lef": "8cf8660c57c44e90..."   recorded in the artefact

The other two are downstream. `release_manifest.py` S07 asks whether every
recorded input hash still matches the file, the answer is no, and the
manifest it writes carries the failure, so the manifest diff fails too. One
cause, three red lines.

## The cause

`dualarm/src/ro_macro_hard.lef` is 1387 bytes here and 1325 bytes in a
checkout. The difference is 62 carriage returns. `.gitattributes` opens with
`* text=auto`, so git stores the file with LF endings, and every checkout of
it, on any platform, is the shorter one.

`chip/tile_budget.py` hashed the bytes on disk. So `TILE_BUDGET.json` has
carried a number since 31 August that exists nowhere except on this computer.

The file has four copies in the tree, `array/`, `dualarm/src/`, `src/` and
`macro/romacro_final/lef/`, and all four are the same bytes, so there was no
disagreement to notice. Nothing else in the repo was affected: every other
file whose hash any artefact records is LF on disk already.

`dualarm/build_2arm_frozen/MANIFEST.txt` says, in its own header, written on
4 September:

> Copies are stored with LF endings. Four of the twelve originals are CRLF on
> disk and .gitattributes rewrites them on commit, so a copy kept byte for
> byte would hash one way here and another way in a checkout, and every hash
> below would be wrong in CI and right on this machine.

That is the same paragraph, one week later, about a different file. The
archive got the rule and the tile budget did not.

## Why nothing here disagreed

This is the part worth keeping. The gate is run in two places before a push:
the working tree and the local clone. Both sit on the same disk and both hold
the same CRLF file, so both recompute the same wrong number and both agree
with the artefact. The only machine that sees the LF copy is the one nobody
was reading.

The check did its job on 31 August. What failed is that its verdict lived in
a browser tab.

## The fix in the producers

`sha256_file` in the six chip scripts that hash files now hashes the bytes a
checkout produces:

    with open(path, "rb") as fh:
        blob = fh.read()
    if b"\x00" in blob[:8000] or blob.count(b"\r") != blob.count(b"\r\n"):
        return hashlib.sha256(blob).hexdigest()
    return hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()

The six are `tile_budget.py`, `release_manifest.py`, `archive_baseline.py`,
`g2_decision.py`, `preregister.py` and `verify_phaseE.py`. `armc_cost.py` and
`gen_armc.py` call `tile_budget.sha256_file` rather than defining their own,
so they came along.

The `extraction/` scripts keep raw hashing on purpose and are not touched.
They pin third-party bytes under `extraction/inputs/`, which is gitignored and
never committed, and those hashes have to match what was downloaded from
upstream, not what git would have stored. A rule that is right for one half of
the repository is wrong for the other half, so it is stated in both places
rather than applied everywhere.

Every artefact was regenerated after the change. `TILE_BUDGET.json` moved by
that one line and **nothing else moved at all**, which is the result to want:
if a second artefact had shifted, the change would have been doing something
besides what it says.

## chip/hash_stability.py

A producer that computes its own hash cannot audit itself, so the new check
comes at the question from the other side. It reads every SHA-256 written into
`chip/*.json` and `dualarm/build_2arm_frozen/MANIFEST.txt` as text, not as
JSON, because a hash is a hash wherever in a structure it sits and a reader
that walks the schema has to be taught every shape a producer invents. Then it
hashes every file in the tree three ways, as it sits on disk, as a checkout
would store it, and as it would look if somebody stripped carriage returns
without asking whether it was text, and asks which of the three the recorded
number matches.

    H01  every recorded hash is of the bytes a checkout produces
    H02  every recorded hash belongs to a file in the tree
    H03  every recorded file's extension is declared in .gitattributes
    H04  every explicit .gitattributes rule agrees with git's own reading
    H05  no recorded file sits somewhere .gitignore excludes

Five checks, seven planted faults, 556 lines. It runs first among the chip
commands in the gate, ahead of `tile_budget.py`, so when this class of thing
happens again the first red line names the file instead of the fourth red line
naming a diff.

The three indexes are the diagnosis. On this machine the bug reads as H01,
`8cf8660c57c4 is the disk copy of dualarm/src/ro_macro_hard.lef`. In a
checkout the same bug reads as H02, that hash belongs to no file at all,
because the CRLF copy does not exist there. Same fault, two sentences, and
each one is the sentence that is true where it is read.

H01 carries two faults rather than one. A hash of the disk copy and a hash of
a binary file with its carriage returns stripped are the same property seen
twice and they resolve through different indexes, so the check names which of
the two it found instead of splitting into H01a and H01b. That is the `T06`
call from the tile budget, made the same way.

## The mistake, and what caught it

H03 wanted every recorded file's extension spelled out in `.gitattributes`
instead of resting on the `text=auto` guess. Six were missing: `.csv`, `.def`,
`.lef`, `.spef`, `.tcl`, `.txt`. I added six lines and ran the gate in the
checkout again, and `sim/spice/gono/verify_provenance.py` went red with

    archived evidence changed without a new manifest:
    sim/spice/gono/ctrl2.txt, sim/spice/gono/par2.txt

A NUL byte in the first 8000 is only half of git's rule for what it will not
convert. The other half is a carriage return with no line feed behind it, and
those two files are ngspice logs with 1521 and 1644 bare carriage returns and
not one NUL. Git has always stored them verbatim under `text=auto`. Writing
`*.txt text eol=lf` overrides the guess, which told git these are text after
all, which would have moved two blobs that hold archived evidence.

So `.gitattributes` carries `ctrl2.txt -text` and `par2.txt -text` under the
`*.txt` line, git's last-match-wins is what makes that work, and H04 knows
both halves of the rule now and has a second planted fault for the second
half. A sweep of the whole tree finds 29 files with a bare carriage return in
them and 27 of those also hold a NUL and are already declared binary. These
two are the only ones where the two halves of the rule disagree.

The verifier that caught it was written on 12 August for a different reason
entirely, and it caught a hole in a check written today to close a hole. That
is the argument for keeping old verifiers running after the thing they were
written for has stopped being interesting.

## The invariant

`sha256_file` reads no attributes. It applies git's heuristic and nothing
else, which is only correct while no explicit rule contradicts the heuristic.
H03 requires an explicit rule for every recorded file and H04 requires the
rule to agree with the heuristic, so the short version inside the producers is
the right version exactly as long as those two pass. That is written into the
docstring rather than left as something a reader has to work out.

## What this does not cover

`extraction/INPUT_MANIFEST.json` is out of scope for the reasons above, and
`spef_census.py --verify-archive` is what holds that side.

H05 reads `.gitignore` as plain names and directory names only. Five patterns
in the working tree and five in the clone use wildcards, and the script prints
them rather than pretending it judged them.

**Nothing in the repository reads the CI verdict.** That is the actual failure
here and no script inside the repository can fix it, because the verdict is on
a server the gate cannot see. What is checked in is the part that can be:
after today the same bug goes red on this machine as well as on GitHub, which
is the difference between a check nobody read and a check that fails where
somebody is looking.

## Numbers

Re-derived with throwaway code that imports none of the above, on the working
tree and again on a fresh clone.

    on disk    1387 bytes, 62 carriage returns, sha256 8cf8660c57c44e90
    checkout   1325 bytes,  0 carriage returns, sha256 1c7442880aca9290
    difference 62 bytes, one per CRLF

    12 artefacts read, 51 distinct hashes, 75 files they resolve to
    539 files covered by an explicit .gitattributes rule
    130 text files are CRLF on this disk, 11 of them with a recorded hash
    29 files in the tree carry a bare carriage return, 27 of them binary

    gate 109 commands before, 111 after
    111 of 111 pass in a fresh clone with iverilog
    108 of 111 pass in the working tree: lint_rtl exits 2 for want of a
    compiler, verify_provenance wants the published history, and
    verify_macro_provenance flags third-party files under extraction/inputs/

## Still open, found on the way

`gl_test` exited 2 in 36 seconds on run 65 and has not run since, because
`archived-evidence` has been failing ahead of it. `viewer` returned 404 on the
same run because Pages is not enabled on the repository. Both will run again
on the next push and both want looking at then, on a fresh result rather than
a fortnight-old one.
