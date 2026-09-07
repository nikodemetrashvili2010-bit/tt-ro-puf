# Run 72, and a build whose failure I could not read

7 September 2026. G.3 step 8 begins by reading the run that step 7's change
produced. I read it, it had failed, and then I spent the morning finding out
that I had no way to learn why.

## What the run page says

Run 72, commit `a8b4373`, 3 minutes 45 seconds. Five jobs.

    archived-evidence   success   58s
    gds                 failure   2m41
    precheck            skipped
    gl_test             skipped
    viewer              skipped

The evidence gate passed, so everything I landed on 6 September is signed off
by something other than me. The build did not.

Two notes on reading it, both of which cost me time before they saved me any.
The list page's status column is worthless through a text conversion: it
reported runs 66 to 70 as passed and every one of those is a documented
failure. Durations survive and are the quick tell. And 2m41 is a new shape.
A minute means `archived-evidence`; run 71's successful `gds` took 5m19. So
this one entered the build and stopped about halfway.

## The part I could not do

I wanted the log. The gds job's log needs a signed-in session, and the
`GDS_logs` artifact, 5.65 MB and sitting right there on the run page, needs
an API token to download. The container's proxy allows neither
`api.github.com` nor `codeload`. The browser I have is signed out and the
page says so in as many words.

So the one thing I needed was the one thing behind a login. I tried four
routes and none of them worked, and I am writing that down rather than
quietly presenting the reasoning I fell back on as though it had been the
plan.

## What I could establish without it

The only thing that changed the build between run 71, which reached GDS, and
run 72, which did not, is step 7: `MACRO_PLACEMENT_CFG` in `config.json` and
the 528-line `src/placement.cfg` beside it. Everything else in `a8b4373` is
under `chip/` and `docs/`, which the build never reads. So the failure is
step 17 or something downstream of it.

I pulled LibreLane 3.0.5's own sources again. All three files hash to what
`chip/FLOW_SURFACE.json` recorded on 6 September, which is the first time
that pinned record has been checked by anything other than the run that
wrote it.

`placers.py`, the whole of `manual_macro_placement`, does not require an
instance to be a macro. It walks every instance, matches on the escaped
name, sets the location and the orientation, and exits 1 naming anything left
over. So 512 standard cells in a macro placement file is not by itself the
problem.

Then I checked the file against the DEF it was derived from, because the
generator's own P05 compares what it emitted against that same DEF and a
check that reads one file twice is not a check.

    netlist   \u_puf.u_core.g_ro_bank[0].u_ro.g_inv[10].u_inv
    DEF        u_puf.u_core.g_ro_bank\[0\].u_ro.g_inv\[10\].u_inv
    cfg        u_puf.u_core.g_ro_bank[0].u_ro.g_inv[10].u_inv 276 106.08 N
    DEF                                        PLACED ( 276000 106080 ) N

Three spellings of one instance and the cfg carries the unescaped one, which
is what `escape_verilog_name` wants. 276 microns is 276000 database units and
gridify leaves it alone. `u_rob0` at 3.22 and 20 is 3220 and 20000, which is
what the DEF has. The parser takes exactly four whitespace-separated fields
and every line has four. The orientations are `N` and `FS` and both are in
the map.

I also checked the RTL, because Arm C's install could have renamed Arm A's
hierarchy underneath the cfg and nothing would have caught it. It did not:
`g_ro_bank[i].u_ro` is untouched and Arm C went in beside it as `g_armc[i]`.

So step 17 has no visible reason to fail, which leaves 18 and 19, which is
exactly where step 7 said the risk was: `CutRows` and `TapEndcapInsertion`
run after the FIRM placement, and `dualarm/build_current` did it the other
way round. I read `cut_rows.tcl` and `tapcell.tcl` as well. Neither settles
it, because what they do with a standard cell that is already fixed is
inside OpenROAD and not inside the Tcl.

**That is where the reasoning stops, and I am leaving it stopped.** I have a
strong candidate and no evidence for it. Writing the fallback in on a strong
candidate is how you end up unable to say which of two changes mattered.

## So make the build say it

Three things are readable on a public run page with no account: job names,
durations, and annotations. Only the last can carry text I choose. The job
summary is not on that list; run 72 wrote one and a signed-out reader sees
nothing.

`chip/ci_failure_report.py`, 838 lines, reads the LibreLane run directory
while it still exists and prints the failure into an annotation, plus the
summary and stdout for anyone who does have an account. It diagnoses nothing.
It finds the step the flow stopped in, quotes that step's log and the flow's
`error.log`, and is careful about which step it names.

Which step to name took three goes and all three are in the file.

Sorting the directory names puts `44-openroad-detailedrouting` behind
`9-checker-netlistassignstatements`, so the number orders them. Then
LibreLane creates a step's directory and copies `config.json` into it before
the step runs, so the highest numbered directory can be one that never got
going. Walking back to the last directory holding a log was the second rule,
and it named step 18, which had finished cleanly, whenever step 19 died
without writing anything, and quoted 18's log as though it were the failure.
The rule now is the last step that did not finish and did write something,
falling back to the last that did not finish.

R03 is what survives all of that, and it is the check I like most: if the
step named has a `state_out.json` then every step completed, LibreLane got to
the end, and whatever failed is outside it. Run against the run directory on
my disk, which is a clean June build, it says exactly that.

The selftest found a real bug in the first version. `read_text` read the
first two megabytes of a log. Detailed routing writes tens of megabytes and
puts the reason it stopped on the last line, so that version would have
quoted the opening banner of the longest log in the flow and called it the
error. It reads backwards now, and says when what it read was not the whole
file.

Two checks earn their planted fault in a way worth naming rather than
counting. R06, that the annotation fits, cannot fail on real input because
the renderer trims until it does; the fixture turns the trimmer off so the
check is known to work. R05 asks the filesystem which quoted files are over
the read limit and requires the report to have said so about exactly those,
and no fixture can make that disagree from the input side, because both
sides come from the same file. What the selftest plants for R05 instead is
the bug it was written for: an error past the limit at the end of a long log,
and the assertion is that the quote carries it.

The first two versions of R03 and R05 both passed on every fixture including
the ones planted to break them, which is the 31 August shape again. A
selection rule tested by a check means writing the selection twice and
comparing it with itself. Three of them are direct assertions on what the
rule selects now, and only the properties that survive that are checks.

## What the gate said about the new script

Six failures on the first run, three of them mine.

`g3_runbook.py` B07 wants every gate script named in step 11's `covers` list.
`release_manifest.py` counts the gate at 117 now, up from 116. Both fixed by
declaring the thing rather than by loosening anything.

The third is better. The documented way to extract the gate command list is

    sed -n '/archived-evidence/,/^  gds:/p' .github/workflows/gds.yaml

and line 147 of that file is `needs: archived-evidence`, inside the `gds`
job. A sed range restarts, so it opened a second range there and ran to the
end of the file. Until today nothing after line 147 matched the command
pattern, so it never mattered and nobody would have noticed. My gl_test
reporter has a `grep` and a `python3` in it and both got swept into the gate
list. Anchoring the start fixes it:

    sed -n '/^  archived-evidence:/,/^  gds:/p'

`release_manifest.py` was right all along; its own regex is non-greedy and
anchored, and it counted 117 while my sed counted 119. The script and the
instructions for humans had drifted apart and only the humans were wrong.

Working tree now reads 114 of 117, the usual three.

## gl_test and viewer

Both have been failing since 20 August with nothing learned in between, and
both got as far as an answer today.

`viewer` is settled. `https://nikodemetrashvili2010-bit.github.io/tt-ro-puf/`
returns 404, so Pages has never been enabled on the repository. That is a
setting on the repository and not something in this tree, and it is one
click: Settings, Pages, source GitHub Actions. It has been the same failure
on runs 65 and 71 and it will be the same on the next one until somebody
clicks it.

`gl_test` is not settled and I want to say why rather than leave a guess in
place of a finding. It exits 2 in about forty seconds, twice, two weeks
apart, and the test harness changed between those two runs while the failure
did not, which points at the machinery rather than at the design. Make exits
2 when it errors, which is the best candidate, and `jq` also exits 2 on a
missing file, which is the second. I checked the second: the artifact carries
`tt_submission/pdk.json` with all three keys the action reads, and exactly
one `.v` file, so the `cp` into `gate_level_netlist.v` cannot be the one
either.

`test/requirements.txt` pins cocotb 2.0.1 and the Makefile uses
`COCOTB_TOPLEVEL` and `COCOTB_TEST_MODULES`, which are the 2.x names, so the
harness and the pin agree. If `cocotb-config --makefiles` returned nothing on
the runner the include would fail and make would exit 2, and that is a guess
I am not going to dress up.

So gl_test got the same treatment as the build: a step that runs only on
failure and puts the cocotb version, the makefiles path, the iverilog
version, what is in `PDK_ROOT`, what is in `test/`, and the tail of anything
under `sim_build/gl/` into an annotation. It is eleven lines of shell rather
than a script, it cannot fail the job, and I ran it under `bash -eo pipefail`
against an empty directory to confirm it still emits a well formed annotation
and exits 0 when nothing it looks for exists.

An independent thing fell out of that reading. `_audit_tt_submission` is a
downloaded submission artifact from an earlier run and its `pdk.json` says
`FLOW_VERSION 3.0.5`. `FLOW_SURFACE.json` concluded 3.0.5 from the action's
default input value, which is an inference from a default. This is the flow
saying its own version in its own output, and it agrees.

## Where this leaves step 8

Step 8 is not done and the next run is what does it. Nothing about the build
changed today on purpose: a push carrying only the reporter reproduces run
72's failure exactly and explains it, and a push carrying a fix as well would
leave me unable to say which of the two mattered. The fallback,
`MANUAL_GLOBAL_PLACEMENTS` at step 33, is already written and
`gen_placement_cfg.py --emit-fallback` renders it, so if the answer is that
this flow will not hold standard cells FIRM, that is one config change and
not a day.

One consequence worth writing down before it surprises anybody. The Arm C
amendment decided today picks the hand placed arm, and hand placing Arm C
means 512 more cells pinned FIRM through the same mechanism that run 72 may
have just failed on. So run 72's cause does not only decide Arm A's pinning.
It decides whether the third arm has a second option at all. See
`docs/phaseG_g2_amendment.md`.
