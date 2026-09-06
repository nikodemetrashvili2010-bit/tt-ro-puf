# G.3 step 7: pinning Arm A, and the region binding that does not exist

`chip/gen_placement_cfg.py`, `chip/FLOW_SURFACE.json`, `chip/placement.cfg`,
`chip/PLACEMENT_CFG.json`. 6 September 2026.

Step 7 of the runbook is "pin Arm A and bind the sixteen Arm C regions".
`gen_armc.py` emitted `chip/armc_place.tcl` for it on 29 August and left the
binding line out on purpose. `docs/phaseE_armc_build.md` says why, under the
heading "The one thing this cannot emit": the command that constrains a cell
group to a region differs between OpenLane and OpenROAD versions, that script
had run neither, and writing an API call you have not executed is inventing
evidence. Fill it in against the flow the build actually uses, it says.

So I went and found out what the flow actually is. That turned out to be the
whole day.

## Which flow

Two facts, from two places.

`gds_build/runs/wokwi/pdk.json` says `LibreLane 3.0.3`, `sky130A`, PDK
`8afc8346`. That directory is a real harden run of this design.
`tt-support-tools` `harden()` passes `--run-tag wokwi --force-run-dir
runs/wokwi` for every project it builds, so the name says nothing about whose
design it is.

`ci/gds.yaml` calls `TinyTapeout/tt-gds-action@ttsky26c` with no
`librelane-version`, and that input's default in the action is `3.0.5`. So the
run on this disk and the run in CI are not the same version, and for a while I
was reading the wrong one.

They agree where it matters. `librelane/steps/odb.py`,
`librelane/steps/openroad.py`, `librelane/scripts/odbpy/placers.py`,
`librelane/scripts/odbpy/reader.py` and `librelane/flows/classic.py` have the
same SHA-256 at both tags. Those five decide every placement question there
is. The hashes are in `chip/FLOW_SURFACE.json` with the URL they came from so
that anybody can check it rather than take my word.

## What the flow will not do

`chip/FLOW_SURFACE.json` is the flow's whole configuration surface, 413
variables and the 72 steps it ran, taken from its own resolved config and its
own log rather than from documentation.

Six of the 413 names carry a word that could mean an area: five
`CTS_*_CLUSTERING_*` and `IO_EXCLUDE_PIN_REGION`. The five cluster clock tree
sinks and macros by distance for buffering. The sixth keeps IO pins out of a
rectangle and cannot address a cell. There is no fence variable, no region
variable, no cell group variable.

Four variables hand the flow a Tcl file: `PDN_CFG`, which the PDN step
sources, `STA_EXTRA_CORNER_TCL_FILE`, `PAD_CFG` for a padring flow this build
does not use, and `IO_PIN_ORDER_CFG`. Not one of them is read by a placement
step.

Which means `chip/armc_place.tcl` cannot be given to this flow in either half.
Not the binding, which was known. The 512 `place_cell` lines above it have
nowhere to be sourced from either, and that was not known. The file is written
against an interface this flow does not have, and it has been sitting there
looking finished since 29 August.

## What the flow will do

Three ways to say where an instance goes, and this design already uses one.

`MACROS` carries a macro's GDS, LEF and netlist and the location of each
instance. `Odb.ManualMacroPlacement` at step 17 turns that into a small cfg
file and places every line FIRM.

`MACRO_PLACEMENT_CFG` is the same step reading a cfg file directly, one
instance per line, name, x, y, orientation. Also FIRM. Deprecated, and it
warns about it.

`MANUAL_GLOBAL_PLACEMENTS` is a dict in the config, read by
`Odb.ManualGlobalPlacement` at step 33, between global placement and detailed
placement. It sets PLACED, not FIRM.

The catch is in the step's own `run()`. It writes its cfg from
`MACRO_PLACEMENT_CFG` **if that is set** and from `MACROS` **otherwise**. An
if and an elif. The moment this design hands the flow a cfg file, the sixteen
hardened macros stop being placed by the `MACROS` block, and a macro that is
not placed does not stay where Arm B needs it.

## The file

`src/placement.cfg`, 528 lines: sixteen `u_rob*` macros at the coordinates
`config.json` already gives, then 512 Arm A standard cells at the coordinates
the frozen DEF records. `dualarm/src/config.json` gains one key,
`"MACRO_PLACEMENT_CFG": "dir::placement.cfg"`. `dir::` resolves against the
config file's own directory, which is `src/`, so a file handed to the flow has
to live there and not under `chip/`.

FIRM rather than PLACED because step 7's stop condition is that no Arm A
instance ends up anywhere other than where the two-arm build put it, and only
FIRM says that. PLACED is a suggestion detailed placement is free to
reconsider, and it only reports the displacement afterwards.

Names go in unescaped. `placers.py` does not look an instance up by the name
it is handed, it calls `reader.py`'s `escape_verilog_name` first, which puts a
backslash in front of each bus bit character. `g_ro_bank[0]` becomes
`g_ro_bank\[0\]`, which is the DEF spelling. The netlist escapes the whole
identifier behind one leading backslash instead, and Phase E already lost a
day to that difference, so P08 checks the round trip on all 512 names rather
than assuming it.

## What is not checked, and it is the interesting part

`Odb.ManualMacroPlacement` is step 17. `OpenROAD.CutRows` is 18 and
`OpenROAD.TapEndcapInsertion` is 19. So the taps go in around 512 standard
cells that are already FIRM, and in the two-arm build it went the other way
round: taps first, then a placer that worked around them.

The frozen DEF proves a legal arrangement at these exact coordinates exists,
because it is one. It does not prove tap insertion finds it coming from this
direction. Nothing on this machine can answer that. The build answers it, and
if it says no, the declared fallback is `MANUAL_GLOBAL_PLACEMENTS`, which runs
at 33 with the rows already cut and the taps already in. That gives up FIRM,
which is a real cost, and it is the reason it is the fallback and not the
choice. `gen_placement_cfg.py --emit-fallback` renders it and
`PLACEMENT_CFG.json` records its hash without committing the file.

## Arm C, which is not done

There is no region constraint, so there are two things I could have done and
I have done neither.

Leave Arm C to the placer. Sixteen `ro_armc` rings handed to the same
unconstrained flow that placed Arm A is Arm A's treatment under a second name.
Three arms, two treatments.

Place all 512 Arm C cells by hand, each ring an exact copy of one template.
Every ring then has the same bounding box, the same row span and the same
density, which is G.2's build criterion, met exactly and measuring nothing.
The criterion exists to ask whether the tool held the constraint. Answer it by
not using the tool and the answer is worth nothing.

There is a third reading and it is not silly. Arm B is sixteen copies of one
hardened macro, identical down to the metal. A hand placed Arm C would be
identical in placement while each ring's nets are routed separately, in
different neighbourhoods, so the parasitics differ. Placement fixed, routing
free, sitting between the two arms that already exist. That is a defensible
experiment. It is also not the experiment G.2 chose, and swapping it in
because the first one turned out to be unbuildable is the sort of thing that
should happen in the open with the frozen file in front of you.

`chip/G2_CRITERIA.json` was written on 27 August, before either option was
scored, and it already says this:

    "delivery_risk": "high",
    "delivery_risk_basis": "The open flow has no supported way to force
    sixteen identical placements. It is the point of the experiment and it
    is also the thing that might not work."

It did not work. The rule anticipated it, the preference order puts "lower
risk that the flow cannot deliver the treatment at all" third, and the
declared fallback for Arm C is the load ladder. Whether to take that fallback,
take the hand placed version under a rewritten G.2, or drop to two arms is a
decision about the experiment. It goes back through G.2. It does not get made
inside a generator, so `gen_placement_cfg.py` emits no Arm C line and P11
fails if one ever appears.

## Checks and faults

Twelve checks, twelve planted faults, each tripping exactly one, and the first
version of the fixture isolated eight of them.

P07 and P08 pass on real data without meeting anything. Every orientation in
this design is `N` or `FS`, 273 and 255, so the other six LEF orientations are
never exercised, and no emitted name carries a backslash so the escaping check
never has anything to strip. Both are faulted from the fixture so they are
known to work on the day a design uses `FW` or a generator forgets to
unescape.

P05 turned out to be the check holding all the others up, and not by design.
See below.

## Where I got it wrong

**The DEF parser found one component.** A DEF component record is indented
before its dash, so splitting the section on a bare `"\n-"` matches nothing
and hands the whole section back as a single record. That parses. It produces
exactly one instance, called `-`, and then every check that counts something
passes because there is nothing to count. Eleven of twelve green, and the
twelfth was P05 saying "0 in the DEF, 0 emitted, 0 duplicated, 0 moved",
which is the only reason I noticed. P05 requires exactly 512 on the real
design and only tolerates a smaller number on the fixture, by name. That
number is what the suite rests on.

**I wrote a width recovery and then took it out.** The first P09 asked whether
the pinned cells overlap anything, which needs cell widths, which are not in a
LEF anywhere in this repository and come out of the row packing instead, the
way `tile_budget.py` does it. The planted fault moved a cell to make it
overlap its neighbour. It never fired: moving the cell shrank the gap it was
recovered from, so the width came out smaller and nothing overlapped after
all. Adding a clean row the fault could not reach did not help either, because
the recovery takes the smallest abutment anywhere and the faulted row still
supplied it. The property is `tile_budget.py`'s T06 and it already holds it
for the whole die. P09 asks the narrower question this file needs, which is
whether every pinned cell stands on a row, and the writeup says which part is
checked here and which part is checked there.

**P07 and P08 both fired on P05 for a while.** Two fixtures were sloppy in the
same way: the fault changed what was emitted, and P05 compares what was
emitted against the DEF, so of course it fired too. P07 reads its orientations
from the inputs now rather than from the emission, and P05 looks names up
unescaped so that escaping is P08's business alone. Same lesson as 19 August
and I did not recognise it until the third one.

## What else moved

`chip/hash_stability.py` has a sixth check. `FLOW_SURFACE.json` records the
SHA-256 of five files that live in another repository and `PLACEMENT_CFG.json`
records one of a file deliberately not committed, and H02 fired on all nine of
them, correctly: it says every recorded hash belongs to a file in the tree.
The ways out were to stop recording the hashes, which loses the evidence, or
to stop running the check, which is worse. Instead an artefact may declare
`_hashes_not_in_this_tree`, a hash to a reason, and H02 accepts a hash that no
file answers to only when the artefact recording it says so in that block.
H06 is what stops the block being a hiding place: it fails if a declared hash
does turn out to match a file here. The docstring's refusal to walk a schema
now has exactly one exception and it is written down.

There is no second half to H06 about a declaration nothing uses.
`collect_recorded` reads each artefact as text, so a declaration records its
own hashes just by existing, and a check that cannot fail does not go in the
suite.

`G3_RUNBOOK.json` step 7 is revised, with the paragraph it replaces kept in
its notes. That is the second step to be revised since the runbook was written
and the reason it was never frozen on a hash.

The gate is 116 commands, up from 111. Five: the selftest, the run, and three
diffs, one for the artefact, one for the emitted cfg against the copy under
`chip/`, one for that copy against what is installed in `dualarm/src/`. Same
arrangement the emitted RTL has had since 4 September. 113 of 116 pass in the
working tree and the three are the usual ones.

## What the next session sees

The push carries `"MACRO_PLACEMENT_CFG": "dir::placement.cfg"`, so run 72's
`gds` job is the experiment. Either the build log says 528 instances placed
and DRC, LVS and antenna come back clean, or tap insertion has something to
say about 512 FIRM cells, and either way it is a fact instead of a guess.
Reading that log is the first thing step 8 does.
