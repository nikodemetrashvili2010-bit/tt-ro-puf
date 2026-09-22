# B13 down to 0.2 ps, and Arm B on the release routes

22 September. The 21st ended with the fixes to `3b67dff` ready and the PC
asleep before they could be copied across, so the first thing today was putting
them in: `1982c20` "fix numbers in signoff paper and datasheet", 8 files, the
same tree the gate had passed the night before.

Then the two things `SIGNOFF.md` still had down as not run on the release
build, and a handful of small ones.

## The boundary through B13

B13 is the slowest rise of the 48 selector paths, and on the 18th it had the
coarse sweep only, 38 phases 50 ps apart. Every phase settled to a rail, but a
50 ps grid only brackets the threshold, a 68 ps pulse lost and a 104 ps one
kept, and says nothing about how narrow the last pulse gets right at the edge.
On the baseline that question was worth a correction (144 ps turned out to be
80).

The coarse sweep went first, again, as a check on this environment. Its csv
came back byte for byte the 18th's. Then three finer grids, each inside the one
before:

    grid     phases  step at the tap    narrowest pulse at sel_ro
    50 ps      38    68 to 104 ps       253 ps
    5 ps       13    75 to 82 ps        202 ps
    1 ps        6    75 to 77 ps        128 ps
    0.2 ps      6    about 76 ps         80 ps

All 63 phases resolve the flop to 0.000 or 1.950 V, and the count moves by one
edge at most.

The 5 ps grid said 202 ps and I nearly wrote that B13 does not squeeze its last
pulse the way B00 did on the baseline. It does. Every finer grid found a
narrower survivor, because right at the threshold the chain thins the pulse and
the closer the enable falls to that point the thinner it gets. So the narrowest
pulse is a property of the grid, and there is no number to quote as a floor. At
0.2 ps it comes out at 80 ps, which is B00's baseline figure by coincidence,
and the flop still resolves it. That fits what the 17th found from the library
side: the last pulse cannot be kept above a minimum width, and it does not need
to be, because either answer costs one count.

One thing in `docs/hardware_todo.md` did not survive. Item 1 said the threshold
is a property of the ring, about a tenth of the period. B13 drives the same
macro ring as B15 and B00, the same 1122 ps period at ff, and gives up at about
76 ps, 6.8% of it, where B15 gave up near 100 and B00 near 111. The path counts
too.

The selector still adds a fixed time and not a fraction, 170 ps with 4.4 ps
unexplained on the coarse sweep against 67.7 ps for the fraction model.

### Keeping the waveforms

On the release build the boundary sweep was the last selector evidence with
nothing behind its csv. `reduce_raw.py` already shrank the mux waveforms to the
samples `analyze_mux_sweep.py` reads, but the boundary analyzer reads
differently: it crosses at half the supply rather than half the peak, and it
looks at the settle tail, the fraction of the last 2 ns that q spends between
20 and 80% of the supply and the mean of the last 50 samples.

So `reduce_raw.py` has a `--kind bnd` now. It keeps the crossings at half the
supply, the last 50 samples, and any tail sample of q inside the band. Rows on
the rail in the tail go, which leaves the fraction at zero when it was zero and
moves it when it was not, and in that case `--verify` fails instead of passing.
Three new selftest checks, one of them a planted fault: keep only the last
sample instead of the last 50 and the final level moves, and verify sees it. 11
of 11.

264 MB of waveform went to 5.1 MB, 5.6 MB with the decks and the console logs,
and the real analyzer reads every field the same from both copies of all 63
decks. They are in `sim/spice/gono/bnd3/`, one folder per sweep, and CI now
rebuilds all four csvs from them and diffs them against the committed ones.

The 0.2 ps csv has one cosmetic problem. Its `en_fall_ns` column has three
decimals, so its six phases print as 30.105 three times and 30.106 three times.
The exact times are in the decks, and changing the column would change every
boundary csv already committed, so it stays.

## Arm B on the release routes

The macro is the same GDS in both builds. The routes to and from it are not:
run 83 drew every instance's enable and output route again, to the 48-input
selector, so every per-instance number in the repository, 0.0025% at tt and the
rest, belonged to routes the release chip does not have.
`gen_instance_decks.py` already takes the netlist and the top-level SPEF as
arguments, so this was three runs and no new generator.

The routes moved more than I thought they would. On average they got a little
shorter, 5.0 fF of enable route against 6.2 and 12.9 fF of output route against
14.5, but the tail went the other way. The longest output route is 45.4 fF
where the baseline's longest was 29.5, so the worst route delay doubled, 9.1 ps
against 4.5, and the slowest edge arriving at the selector is 468.5 ps at tt
against 318.2.

    corner   sixteen, MHz          peak to peak   baseline   counts
    ss       291.089 each          0.0001%        0.0001%    0.02
    tt       570.629 to 570.648    0.0033%        0.0025%    0.76
    ff       891.350 to 891.367    0.0019%        0.0009%    0.68

The last column is the whole spread in counts at 2048 cycles of 50 MHz, the
window the release firmware uses. All three runs pass `analyze_instance.py`:
the control where every other deck puts it, 18 rings out of 18, every route
handing back the period it was given, and the widths closing.

Wider than the baseline at tt and ff, but not because of the routes. At tt both
ends of the spread are instances whose routes delay by under a picosecond, and
at ff most of it is instance 14, 0.1 ps of route, 16 ppm under the reference
where the rest sit within 5. The baseline's logs also came from ngspice 45.2
where these came from 42. Route delay tracks output capacitance at +0.915 and
the edge at the selector at +1.000, as before. Frequency does not: -0.114 at tt
and +0.300 at ff, and at ss the spread is only nine times the log's own
resolution, too close for a correlation to mean anything. The sign wanders,
which is what noise does, and the baseline's one nominally significant corner,
ff at t = 2.40, is t = 1.18 here. So what the two runs agree on is the size, 1
to 33 ppm, still under the 0.01% written down before the first run and under
one count at every corner.

The ff control read 993.987 MHz against the archived 987.948, 0.61% off, and
for a minute that looked like something. It is not the routes, since the
control carries none, and the baseline run of the same deck read 993.990. It is
inside the 1% the analyzer allows.

Both checkers held every run against the baseline's Arm A, 5.84% at tt, which
is the wrong die for these logs. `analyze_instance.py` takes `--build release`
now and uses the release build's Arm A instead, 5.88% distributed at tt and
5.63% and 5.83% lumped at ss and ff, the figures `verify_predictability.py`
prints. One new selftest case: a 5.55% spread fails against the baseline's ss
and only flags against the release's. 15 of 15. `verify_instance_corners.py`
got the same switch and the release window, and one of its checks, ff reaching
significance, was a statement about the baseline's routes, so on the release it
prints as a note. With `--build release` it reads `armb3/` unless told
otherwise, and its selftest now runs the release logs too, clean and with a
planted fault. 35 checks on `armb3/`, all pass, and its output on the baseline
logs is the same as before apart from a header line. One passes narrowly: at
ff, taking the capacitance correlation at face value, the whole span of output
routes would buy 0.196 of a count, and the check allows 0.2.

`verify_datasheet.py` took Arm B's fastest ff instance from the baseline log.
It reads `armb3/` now, and gets the same 891.4 MHz. It also checks the three
spreads `docs/info.md` quotes against those logs to the fourth decimal, 27
checks now, and a changed digit or a reworded sentence both fail it.

One claim did not survive the rewrite. The baseline text said the chip cannot
tell the sixteen apart "even in principle", because the spread was 0.57 of a
count. That was never quite right. The count depends on the reference clock as
well as the window, and the clock is set on the bench: slow it to the edge of
wrapping and one count is about 15 ppm, so a 25 ppm spread is more than one.
What the runs show is narrower, that one reading at the setting the firmware
uses cannot tell them apart. The paper and `docs/info.md` say that now.
`hardware_todo.md` keeps the old sentence and says so in the new section under
item 8.

Not redone: Section 8.2 of the paper, whether anything in the design database
predicts the leftover and what it is worth in bits. Its first test is cheap on
the new logs, since a passive route can only slow a ring down, and 10 of 16
still read faster than the reference at tt and 12 at ff. The rest needs
`matched_arm.py` to take its positions from the release DEF, and it reads the
baseline's by name.

## Smaller things

- `make_release_manifest.py` still hashed `build_current`, the two-arm
  baseline, for the release notes. It hashes `build_armc` now, and prints the
  workflow run when `commit_id.json` has one.
- `verify_datasheet.py` stopped with an AttributeError whenever a sentence it
  quotes had been reworded, which is a red job with no reason on it. Every
  lookup goes through one helper now that records a FAIL naming the sentence. I
  tried it by deleting phrases from a copy of `info.md`: a clean FAIL each
  time, no traceback. 26 checks at that point.
- "Shipped" meant the two-arm baseline in six documents, and that is the build
  that is not shipping. 25 edits, `docs/warning_triage.md` and
  `docs/gono_results_writeup.md` among them. The wokwi control README now says
  the release build has five disconnected pins where the baseline has nine,
  which `metrics.json` in both folders agrees with. The scripts still use the
  word in comments and printouts, and I left those.
- `reduce_raw.py --selftest` left two scratch folders in `/tmp` every time it
  ran, one from before today and one from the new boundary checks. Both are
  removed at the end now.
- The 149 decks archived on the 20th, `rc3/` and `real_world/`, carried the PDK
  install path of the machine that generated them in their two library lines.
  They carry `/home/pc/pdks` now, like `mux3/`, `bnd3/` and most of the older
  decks. `run_ngspice.py` swaps those two lines for the local PDK on every run,
  so no log and no number moves, and its docstring, which called those paths
  provenance, now says which decks that no longer holds for. The `armb3/` decks
  went in the same way.

## The gate

143 commands at the start of the day, 155 now: eight for the four boundary
csvs, one per corner for Arm B, and the corner verifier on `armb3/`.
`RELEASE_MANIFEST.json` regenerated last. The whole list in a fresh clone of
the tree being committed: 155 of 155.

## Mistakes

- The 202 ps above. The 5 ps grid made B13 look like a path that does not
  squeeze its last pulse, and it took two finer grids to show it does.
- The first ss run for Arm B died at 30 minutes, on a timeout in my own run
  script. The generator's own help warns that a real run can take an hour.
  Restarted with two hours; it needed 34 minutes.
- "Even in principle", from August, above.
- The PDK path in the 149 decks. I archived them on the 20th without reading
  their headers.

## Not done

- The stopping boundary through the other 47 selector paths. B13 is the slowest
  rise, and the rest have only the steady sweep behind them.
- Section 8.2 on the release routes, `matched_arm.py`, above.
- `verify_instance.py`, the tt check that re-reads the SPEF and the netlist
  with its own parsers, still points at the baseline. The corner verifier
  covers the logs on the release routes, not that.
- The build with only the soft obstruction around Arm A changed.
