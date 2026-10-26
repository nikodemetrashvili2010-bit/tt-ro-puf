# The predictions, archived before any die

26 October 2026. `chip/PREDICTIONS.json` is the archive, and
`chip/archive_predictions.py` writes it and checks it. Its SHA-256 is

    8a7bf09522d1539eaa768340042a9d2ccbe72538b5b4a1b56338623b7bc3af23

and `--freeze-check` holds the file to that number and looks for it here.

## Why it had to be written down

`chip/PREREGISTRATION.json` ends on a promise: the per-pair sign predictions
from the public design database are archived and hashed before any die is
read. The frozen file fixed how a prediction is judged. The first amendment
fixed which arm and which test carry the claim, the second which pairs are
scored.

None of the three wrote a prediction down.

Each one was implied, by four tables the second amendment records by hash
and a rule it states in words. That is enough for me to work a prediction
out, and nowhere near enough for someone holding a die and a CSV.

## What is in it

All twenty-four pairs. For each, the separation the SPEF's table gives and
the one magic's gives, in percent of the arm's mean, whether it is scored as
frozen and as amended, and for the scored ones the bit the die should show.
A bit is 1 when the lower ring of the pair runs faster, and the strings run
pair 0/1 first.

    arm  predicted  SPEF signs  magic signs  scored
    A    xx10x000   11100000    00100000     4/5 6/7 10/11 12/13 14/15
    B    xxxxxxxx   01010111    00101001     none
    C    xx0xxx10   11010110    01010110     4/5 12/13 14/15

An x is an abstention, counted and published and never scored either way.
So on the first die read, ring 4 of Arm A should run faster than ring 5, and
in 6/7, 10/11, 12/13 and 14/15 the odd ring should be the faster one. Five
of five is 1/32. Under the second amendment that is tested at 0.05 only
after M4 has cleared 0.025.

M4 in the two models, for the record: 0.363 from the SPEF and 0.471 from
magic, against the 1 it has to get under.

Arm B has no pair anywhere near the line. Its SPEF signs are separations of
a thousandth of a percent, and they are in the file only so that nothing
about the arm is left out.

The closest call in the whole archive is Arm C's 2/3, 0.6112 percent in the
SPEF's table against a line of 0.6179. It abstains under both rules, and
would whichever way a rounding went, because magic puts it at 0.096.

The archive also carries the hashes of the preregistration, both amendments
and run 83's DEF, SPEF and GDS, and two fields in plain words: what the
tables leave out, and what went public before this file existed.
`chip/hash_stability.py` holds every one of those hashes, so none of the
files can change under the archive without the gate going red.

## What it reads, and what it refuses

It reads the tables the second amendment names, at the paths and columns it
names, and nothing else. Before anything is classified, every one of them
has to hash to the value the amendment recorded. If one does not, the script
stops at C01 and says nothing about the pairs. A table nobody amended
against would give an archive that looked exactly like this one.

The arithmetic is mine and imports nothing from `preregister.py`, which
works the same lists out for its own `--amendment` checks. Two programs that
share no code agree on every list.

## The five checks

    C01  the tables are the ones the second amendment recorded
    C02  the pairs scored as amended are the amendment's own lists
    C03  the pairs over the line in the SPEF's table alone are its
         scored_as_frozen lists
    C04  the SPEF signs of Arms A and C are the strings README.md published
    C05  every prediction in the archive on disk is the sign both tables
         give, and no abstention carries one

`--selftest` plants six faults, each into a copy of the real inputs, and
each trips its one check and no other. A table rewritten with every number
the same trips C01. magic moving pair 4/5 under the line, with the new hash
put into the amendment the way a careless edit would, trips C02. The SPEF
lifting 2/3 over the line trips C03, and turning it round under the line
trips C04. A prediction flipped in the file on disk trips C05, and so does
nothing else.

The sixth is the one I care about most. The README is wrapped at 79
columns, so its sentences are matched with whitespace collapsed, and a
pattern that matches nothing would pass everything. C04 counts its matches
first. A README that lost Arm C's sentence fails it.

The freeze check has three cases in the selftest of its own: archive and
write-up agreeing, a prediction changed, a write-up without the hash.

## What went public first

The preregistration also says nothing about a prediction goes public before
it is archived. That was not kept, and the archive says so in its own field.
Arm A's eight SPEF signs were in `docs/phaseG_g3_extract.md` in `796b776` on
19 September, and `README.md` carried them with Arm C's in `1987e6c` the next
day. Both are pushed.

Both came after the layout was final and long before any die existed, so
nothing could have been fitted to anything, and if anything a README pushed
in September is evidence of what was predicted and when, which is the job an
archive does, only done by a branch a force push can rewrite, on a host that
can take it down, with nothing outside the repository to say what it held on
the day. That is why it is not the archive the preregistration meant.

What can be done now is make sure the two never part. They are the
`spef_signs` strings in the archive, unchanged, and C04 holds the README to
them.

## Found on the way: M1 names no cell

Writing the voltage and temperature line of the archive, I had put that the
preregistration scores each pair at the nominal cell. It does not. M1's
definition is "the number whose measured sign matches the sign predicted",
and no cell is named for the measured sign, in the frozen file or in either
amendment. `chip/primary_tests.py` takes n and k and never sees a cell.

M2 and M4 do say "at the nominal cell", and the nominal cell is not defined
anywhere either. Voltage and temperature are easy to read off as 1.80 V and
25 C. The window is not. Three windows are safe, 256, 512 and 2048 cycles,
and they give the same frequency at three resolutions.

The predictions are the typical corner, and the SPEF's signs for Arms A and C
are the same at ss, tt and ff, so the gap is unlikely to move a scored bit.
It is still a choice that has to be made before the first die and not after.
Not amended here. Decisions on the preregistration are Nikoloz's, and this
one goes on the open list beside the M4 secondary's interval and M2's
shuffles.

## Depositing it

The archive is on GitHub after the next push and that is not the archive the
plan asks for either: "a signed Git tag plus an immutable timestamped archive
such as Zenodo or OSF". The route that needs nothing new installed:

1. push, so the commit holding `chip/PREDICTIONS.json` is on GitHub
2. on zenodo.org, Log in with GitHub and authorise it, open the GitHub page
   in Zenodo, and switch `tt-ro-puf` on
3. on GitHub, make a release on that commit. A tag name like
   `predictions-2026-10` will do
4. Zenodo copies the whole repository at the release and gives it a DOI

The DOI goes into the vault and the README in a later commit. Never into
`PREDICTIONS.json`, whose hash is frozen.

Nothing here waits on the resubmission in the Tiny Tapeout app. That rebuilds
the same layout, which `sim/release_identity.py` checks on every push, and
draws the decap swap again, which is in neither table.

## Mistakes on the way

The README fault in the selftest first looked for `Its bits, ` on one line.
The README breaks that sentence after "Its". The fixture's edit helper
refuses an anchor it does not find exactly once, so it stopped with a count
of zero rather than plant nothing and report the check as passing.

The voltage line, above. Caught by reading the four definitions before the
hash was taken, which is the only reason the archive does not say it.

The decap swap line first said no pair over the line comes within 28 percent
of its margin. That was `OPEN.md`'s wording carried over. The 20 October note
says 28 percent was the largest share of a scored pair's separation, on 0/1,
which is no longer scored, and that no bit over the line can turn. The
archive says the second thing only.

## Not settled

- the deposit, which is Nikoloz's to make with his own accounts
- M1's cell and the nominal cell's window, before the first die
- whether SKY 26d fills inside the tile. All three of Arm C's scored pairs
  depend on the answer, and none of Arm A's five
- the TT07 predictions for Phase B are a different archive with a different
  freeze, not this one
