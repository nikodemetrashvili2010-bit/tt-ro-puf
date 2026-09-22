# The writing pass, and the release build under the gate

21 September. The 18th showed that the Arm A bits every document quoted belong
to the two-arm baseline and not to the chip, and yesterday fixed the README.
What was left was `SIGNOFF.md`, the datasheet and the paper, the writing pass
my notes have been carrying since the 18th. Plus the one thing yesterday's note
said had to go in before a push: `real_world.py` in the gate.

The gate came first because it was the small one. It was not.

## The gate

Yesterday's note said adding `real_world.py` moves three things: the gate
count, B07's covers list in `chip/G3_RUNBOOK.json`, and the manifest. Two of
those are right. B07 only collects `python3 chip/...` lines from the gate, so a
script under `sim/` never reaches it, and `G3_RUNBOOK_CHECK.json` comes back
unchanged. The manifest does count every command.

Reading the gate for that turned up the bigger gap. It ran the bundle, ring,
placement and warning checks on `build_current`, and `build_armc`, the build
that is actually going to the shuttle, it only hashed. The one script reading
its logs was `verify_predictability.py`. So the bundle, ring, placement and
warning checks now run against the release build's archive as well, and the
tables made yesterday are regenerated from their logs. The analysis scripts,
noise, compensation, pairing and the Arm B instances, still read only the
baseline, which is where they were measured:

    verify_ring_topology.py --arms AC, release netlist       32 of 32 rings
    verify_build_bundle.py --dir dualarm/build_armc           8 of 8
    placement_fidelity.py --strict, release DEF              Arm A 512 of 512
    gen_armc_fix.py --verify-def, release DEF                Arm C 512 of 512
    triage_warnings.py --build dualarm/build_armc             14 of 14
    analyze_mux_sweep.py on mux3/, diffed                    byte for byte
    analyze_rc.py on rc3/armA and rc3/armC, both diffed      byte for byte
    real_world.py --selftest, then real_world.py             8, then 20

Thirteen commands, 143 in all. `chip/RELEASE_MANIFEST.json` was regenerated
last and the only field that moved is `gate_commands`, 130 to 143. In a fresh
full clone of `1987e6c` with today's files over it the gate is 143 of 143, in
47 seconds. The real job has not seen it yet; that is the next push.

## The datasheet

`docs/info.md` becomes the Tiny Tapeout project page, so it is the one document
someone holding the chip reads. It was quoting the baseline in four places: the
5.53% spread, Arm A at 540.0 to 570.7 MHz and the counts made from that, a
fast-corner ring at 888.3 MHz with the clock floor worked out from it, and the
80 ps paragraph. `sim/verify_datasheet.py` re-derived every one of those from
`build_current`, so it passed on a datasheet for a chip nobody is making.

It reads `build_armc` now. Arm A becomes 538.4 to 570.0 MHz, 22052 to 23347
counts, a spread of 1295.

The part worth keeping is the fast corner. The fastest ring on this chip is
not in Arm A. Arm C's rings carry two thirds of the load, and at ff its ring 10
runs at 911.1 MHz. Arm A's fastest is 887.2 in the go/no-go decks and 891.7 in
the decks the Arm C figure comes from, and Arm B's is 891.4. So
at the 2048-cycle window the clock floor is 28.5 MHz and not 27.7, and at
50 MHz that ring reads 37318, 56.9% of full scale. Still a little over half and
nothing to change. But the number had been taken from Arm A alone, and Arm A
was not the fastest even on the baseline, where Arm B's instances reached 891.4
against Arm A's 888.3. Nothing would have said so, because the verifier only
ever looked at Arm A's decks.

It takes the maximum over all three arms now and checks that the datasheet
names Arm C as the one setting the floor. 26 checks. Six planted edits to a
copy of the datasheet, among them putting 888.3 back and naming Arm A, each
fail the one check they should.

The 80 ps paragraph keeps 80 ps as the working figure, since B13's sweep on the
release build stepped 50 ps at a time and never landed on the threshold, and
it says what the 17th found about the 77.5 ps instead of calling it a margin.

Arm B's 0.0025% is labelled as the baseline's routes.

## SIGNOFF.md

Rewritten around run 83. Two tables now. The release build's comes first and
every row in it was read from `build_armc` or from a log made from it. The
baseline's follows with a column saying whether each result still holds, since
some of it does (the macro, the flop at the ring boundary, the method of the
supply sweep) and some of it plainly does not (Arm A's bits, the 32-to-1
selector).

Two rows say "not run": the fine boundary sweep through B13, and Arm B's
sixteen instances on the new routes. The first is marked "before final trust",
the way the old file marked the 29 unswept selector paths.

The warning notes are the release build's own: 473 lint warnings, 291 slews on
30 nets that the placement repair split with `clkdlybuf4s25_1` buffers, two max
cap violations on two of those buffers, `clknet_0_clk` at fanout 16, `VPWR` and
`VGND` floating as in every build, five disconnected pins. All from
`docs/phaseG_g3_extract.md` and the triage script, nothing new measured today.

The "What is left" section lost the paragraphs about archiving and the 29
paths, which are done or superseded, and gained the bench from yesterday.

## The paper

Not rewritten. Brought far enough that nobody reads the baseline as the chip:

- a revision note under the date, saying which build is which
- the abstract leads with the release build, 0.07 bits and 7.99 called, keeps
  the baseline's 0.46 and 7.91 next to it, and has a paragraph on Arm C
- every "shipped build" and "candidate build" that meant the two-arm one says
  "baseline build"
- Section 3 describes the third arm and the bigger selector, with the
  three-arm diagram as Figure 1b so nothing else had to be renumbered
- Section 5.4's wrap paragraph now describes the selectable window and the
  flag, with the Arm C ring as the fastest; 5.7 notes the window moved from 40
  to 41 us
- a new Section 7.4 scores the release build, the table of eight pairs and
  then Arm C
- Section 9's prediction is made for the release build, `11100000` and
  `11010110`
- a limitation saying most of the paper is the baseline's
- the conclusion leads with the release build and then says the rest is the
  baseline

The table in 7.4 is `predictable_bits.py --par ... --rc rc_validation_3arm.csv`
output, and its totals, its two closest pairs and the Arm C figures are ones
`verify_predictability.py` already holds. The lumped 2.3 sigma for Arm C and
the 0.71 rank correlation between the builds' loads are not in any verifier;
they come from `rc_validation_armc.csv` and the 18th's extraction note. The
docx and PDF are rebuilt with `docs/build_paper.sh`, 35 pages from 33, in the
container with pandoc 3.1.3 and LibreOffice 24.2. See the mistakes for why
there.

## Also

`REPRODUCIBILITY.md` still called `build_current` the tapeout candidate. It
points at `build_armc` now, says which release-build logs are in the tree and
which CI rebuilds, and the figure commands include `--arms 3` and the
floorplan.
`dualarm/README.md` still opened with "the dual-arm integration candidate" and
did not mention either build; it has a list of the build folders now. The
README had two sentences saying SIGNOFF and the paper were still to do.

## Mistakes

Seven, kept.

B07, above. Yesterday's note and `PENDING_PUSH.md` both say the covers list
has to move. It did not, and I only found out because I opened
`g3_runbook.py` to see what the list was checked against before editing the
JSON.

I reworded the datasheet's fast-corner sentence and broke the phrase the
verifier searches for, "same ring reads". It died with an `AttributeError`
rather than printing a FAIL. Every phrase lookup in that file behaves the same
way, so I left it alone today, but a missing phrase should fail, not crash.

The first SIGNOFF draft put all 291 slews at the slow corners and said none
anywhere else. The tt corners have 51 to 69. It says worst slow corner, fewer
at tt, none at ff now.

The same draft counted the KLayout spacing check among `real_world.py`'s 20.
It is not one of them. It needs `klayout`, it is not in the gate, and it has
its own row.

The first draft of 7.4 said the router "answers the same placement differently
each time it is asked". That contradicts Section 5.3, where the flow is
deterministic and a second pass of the whole sweep reproduced all nine builds.
The routes changed because the rest of the die changed, and that is what it
says now.

I built the paper on my own machine first, in the Linux VM, because I thought
that was where the last PDF came from. Its pandoc is 2.9 and its LibreOffice is
26.2, and the PDF it made dropped every table in the paper to its first column.
Nothing failed and nothing warned, and the text around the tables looked fine.
The committed PDF says LibreOffice 24.2 in its own metadata, which is the
container's, and the container rebuilds the old draft to the same page text
line for line. So both files come from there now, and I looked at the 7.4
table on the page before copying them anywhere.

And the last one is a batch. With everything committed and before pushing, I
read all of today's text again against the files, slowly, and it had six more
wrong things in it. They are fixed in a second commit on top of the first:

- the paper and SIGNOFF said the two builds differ only in wire. True of Arm A,
  not of the die, which gained Arm C and a bigger selector
- "pairs 0 and 4 flip", in a paper whose new table names pairs by their rings.
  It is 0/1 and 8/9
- the baseline's nine disconnected pins, explained by three inputs coming into
  use. It was four; `ui_in[7]` became the second arm-select bit
- B13's step bracketed as 4 to 104 ps, copied from the 18th's note. Phase 2 of
  the same sweep already lost a 68 ps pulse, so it is 68 to 104
- Arm C's 911.1 MHz set against Arm A's 887.2, which come from two different
  deck generators. On the same generator Arm A's fastest is 891.7. Arm C is
  still the fastest either way
- "everything" that runs on the baseline's archive now running on the release
  build's. The bundle, ring, placement and warning checks do; the analysis
  scripts do not

And a few that were loose rather than wrong: SIGNOFF quoted the supply drop as
0.28 to 0.58 mV, which is Arm A's worst feed alone, and says "at most 0.58 mV"
now; the paper's revision note and its limitation said no section but the
abstract and 7.4 had release numbers, when 5.4, 5.7, 9 and 11 do too; and a
comment in the verifier said Arm C runs 2% faster, which is fastest against
fastest. Ring for ring it is about 4%.

## Not done

- the fine boundary sweep on B13
- Arm B's instances on the release routes
- the soft box run
- `sim/make_release_manifest.py` still hashes `build_current` as the shipped
  views. It writes the body of the tagged release and the tag has not been
  cut, so it is harmless until then, but it has to point at `build_armc` first
- the READMEs inside `dualarm/floorplan_trials/` and `dualarm/control_wokwi/`
  still say "shipped build" for the baseline
- a missing phrase in `verify_datasheet.py` crashes instead of failing
