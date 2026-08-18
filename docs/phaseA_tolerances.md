# Phase A tolerances — the numbers A.5 has to hit, written before it runs

Task A.5, 18 August 2026. `extraction/TOLERANCES.json`, sha256
`7f61955a03f2c43331ff4a36c6bca1235af598eec96c3740de246919960408c2`, frozen
before the pipeline of A.3 and A.4 exists and before anything has been predicted
about either foreign target. `extraction/check_tolerances.py` is the only thing
that reads it.

The plan says A.5 is the gate and that "close enough" is not an acceptance
criterion. That is easy to agree with and hard to obey, because the natural time
to decide what counts as close enough is after you have seen how close you got.
So the file exists now, while the honest answer to "will the pipeline pass this"
is that I do not know.

## The conversion everything hangs on

The pipeline will produce capacitance per ring. The claim the paper makes is
about the sign of a frequency difference. Something has to connect them, and on
this build it is a straight line: regressing the full-RC frequency of the
sixteen Arm A rings on their extracted ring capacitance gives -5.1355 MHz/fF,
which is 0.9331 percent of the mean frequency per femtofarad, with R² 0.9909 and
a residual of 0.915 MHz rms. The rings average 14.033 fF.

That residual is not small and I am not going to pretend it is. It is 0.166
percent of the mean frequency, which is roughly a quarter of the margin line
below. Capacitance is not the only thing setting a ring's period — resistance
and the cells themselves matter — so the line is a conversion of scale, not a
model. It is used in two places only: to turn the mismatch estimate into
femtofarads, and to classify margins when a table has no frequency column. Where
both tables carry frequencies, frequency decides, and the residual never enters.

With that, one ring's fabricated mismatch — 0.062 percent of frequency, from
`sim/spice/mc` and section 5.6 of the paper — is 0.0664 fF, or 0.473 percent of a
ring. Two independent rings give 0.0940 fF per pair.

## The checks

| id | check | rule |
|---|---|---|
| T1 | extraction total | within 5% of the SPEF total |
| T2a | per-ring capacitance, worst ring | ≤ 0.066 fF after the median error is removed |
| T2b | per-ring capacitance, population | rms ≤ 0.033 fF |
| T2c | per-ring capacitance, relative | ≤ 1.0% of that ring |
| T7 | systematic scale | reported, not gated |
| T3 | rank | Spearman ≥ 0.98 over the sixteen rings |
| T4b | margin classification | the high-margin set must match exactly |
| T4a | high-margin sign | zero disagreements |
| T5 | topology | zero rings with the wrong cells or the wrong order |
| T6 | abstentions | named before the SPEF signs are read |

## Where the numbers came from

**T2a, 0.066 fF.** One ring's fabricated mismatch, and nothing else. An
extraction error at the limit is then the size of the die-to-die variation the
bit already survives, which is the only bar I can defend without knowing what
the extractor will actually manage.

I nearly wrote a second derivation next to it — that two rings at the limit
spend a fifth of what a high-margin pair holds in reserve — and it is worth
saying why that is not one. Setting T2a equal to sigma_ring makes the pair sigma
2·sigma_ring and the line very nearly 10·sigma_ring, so the worst case of two
rings at the limit is 0.132 fF against a 0.662 fF line and comes out at a fifth
by construction. It would have been a fifth whatever number I had picked. It is
a consequence of the choice, not evidence for it, and root-sum-square instead of
worst case makes it 0.094 fF and a seventh.

The median, not the mean, removes the common mode, so one badly extracted ring
cannot drag the reference under itself. Only an *additive* common mode comes
out. A multiplicative scale stays in, because the factor would have to be fitted
against the very SPEF the check is testing, and fitting a free parameter to the
answer is what the rest of this project spends its time refusing to do. T7
reports the factor instead, so a T2 failure can be read: a scale near 1.03 with
a small residual is a calibration problem, a scale near 1.00 with a large one is
wrong nets.

**k = 5.** Not a round number picked for looking careful. It is the smallest
integer for which the expected count of wrongly-signed high-margin bits across
all of Phase A stays under 0.001. At most 168 pairs across the three designs —
8 here, at most 128 for `tt_um_litneet64_ro_puf`, at most 32 for `tt_um_PUF` —
and 168·Φ(-k) is 2.3e-1 at k=3, 5.3e-3 at k=4, and 4.8e-5 at k=5.

The pair sigma it multiplies is 0.1324 fF, not 0.0940. The extraction is charged
its own tolerance as a second independent source of ring-to-ring error, so a
pipeline sitting at the T2a limit does not also get to keep the margin it has
already spent. That puts the line at 0.6622 fF, or 0.6179 percent of the mean
frequency, which on this build is 3.40 MHz.

**T3, 0.98.** Derived, not chosen. At 0.066 fF per ring, only rings whose
capacitances differ by less than 0.132 fF can change places. Sorted, this build
has three such blocks — two pairs and one run of three — and the worst
rearrangement reachable inside them gives a summed squared rank displacement of
12, so a correlation of 0.9824. Rounded down to 0.98.

Which makes T3 implied by T2 here, and I kept it anyway for two reasons.
`analyze_rc.py` already learned that demanding an identical ordering is the
wrong test, because near-tied rings reorder while telling you nothing, and the
number that replaced it was rank correlation; and on a target whose rings are a
different size, the absolute threshold stops transferring and this one does not.

## What the frozen file already says about this build

Applying the margin rule to the SPEF, before any pipeline exists, splits the
eight pairs six and two: 2/3 and 4/5 abstain, the other six are scored. That is
the same six the paper's section 9 already predicts, which is reassuring and is
not evidence — the rule was built out of the same mismatch figure the paper
uses, so it would have been strange if they disagreed.

The inconvenient part is pair 12/13. Its separation is 0.690 percent of the mean
frequency against a line at 0.6179, so it clears by 11.7 percent and nothing
else is anywhere near. If the extraction moves it across, the answer is to fix
the extraction or to reclassify 12/13 as an abstention and say so. The line does
not move. That is written into the file so that it cannot be decided later by
whoever is looking at a failing run at the time.

And it is closer than it sounds. One of the planted faults in the selftest is an
alternating ±0.050 fF per-ring error — inside T2a, which allows 0.066 — and it
is enough to push 12/13 under the line. So T4b will bind before T2 does, on this
build, for this pair. An alternating sign pattern is the worst case rather than
a likely one, but it means the classification check is doing real work rather
than following from the others.

## The checker

`check_tolerances.py` is stdlib, reads every threshold out of the JSON, and
refuses to report a pass if the JSON no longer hashes to the frozen value. Give
it two CSVs of per-ring capacitance — the trusted one from the SPEF, the
candidate one from the pipeline — and it returns pass or fail per check with the
number that decided it. A `freq_MHz` column, when both sides have it, takes over
the margin classification, since the bit is a frequency sign and not a
capacitance sign.

`--selftest` needs no inputs and no network. Ten cases: eight planted faults,
each declaring in advance which checks it must trip, and two that must trip
nothing.

    clean copy                         none
    common mode +0.50 fF               none
    global scale +6 percent            T1,T2a,T2b,T2c
    one ring +0.10 fF                  T2a
    alternating +/-0.050 fF            T2b,T4b
    rings 8 and 13 swapped             T2a,T2b,T2c,T3,T4b
    pair 0/1 reversed, frequency only  T4a
    scrambled assignment               T2a,T2b,T2c,T3,T4a,T4b
    pair 12/13 pushed below the line   T4b
    ring 9 missing                     T1,T2a,T2b,T2c,T3,T4a,T4b,T5

Two of those are worth a sentence. The common-mode case is a control: every ring
heavier by the same half femtofarad is a calibration difference and has to fail
nothing, which is what says the median removal works rather than hides. And the
scrambled assignment is the same control `build_transfer.py` uses — the right
multiset of capacitances on the wrong rings — because that is the failure that
would leave a pipeline looking accurate in aggregate and useless per bit.

The clean copy also has to have evaluated all nine numeric checks and to have
produced exactly the abstentions 2/3 and 4/5, so the suite cannot pass by
evaluating nothing.

## Freeze

The hash is recorded here, in `PLAN_TO_DECEMBER.md` and inside the script.
`check_tolerances.py --freeze-check` runs in the `archived-evidence` job. If a
tolerance has to change it becomes a new dated file with a stated reason and
this one stays in the repository; there is no path where a threshold quietly
moves after a run.

Scope. Every number here is derived from one build of one design with sixteen
rings, and the mismatch figure underneath all of them is a first-order estimate
with a sampling interval running from 0.051 to 0.080 percent, which is nearly
half as wide as the figure itself. The scaling rule in the file says how the
thresholds transfer to a target with a different ring size, and that rule is
frozen; the numbers it produces per target are not the numbers above. None of
this is validated against silicon, and nothing in it can be until a die is
measured.
