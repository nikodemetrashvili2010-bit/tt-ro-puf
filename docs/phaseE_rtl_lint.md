# The RTL nobody had compiled

2026-09-01. One script, `chip/lint_rtl.py`, and a day spent finding out why
it needed to exist.

The plan for the day was G.3 steps 1 to 4: archive the two-arm build, install
the generated modules into the source tree, edit `info.yaml`, lint. Four
quarter-days, which is what the runbook budgets, and a clean stopping point
before the steps that need the PDK. None of it happened. Step 2 turned out to
be the wrong command pointed at the wrong folder holding the wrong Verilog,
and finding that out took the day.

## What the runbook said, and where it pointed

Step 2 installs `chip/ro_armc.v` and the three `e2_*.v` modules into `src/`.

There are two `src/` directories. `backup_to_repo.sh` has a rule
`dualarm/src::src`, copies `dualarm/src/` into the clone's `src/`, and at line
361 diffs the two to make sure they agree, because `src/` is what TinyTapeout
builds. The top-level `src/` in the working tree is read by none of that.

It is also the June design. All five files differ from their `dualarm/src/`
counterparts, and not by a little:

| file | top-level `src/` | `dualarm/src/` |
|---|---|---|
| `config.json` | 2520 | 4067 |
| `ro_macro.v` | 2438 | 2507 |
| `ro_puf.v` | 1331 | 1605 |
| `ro_puf_core.v` | 3448 | 9026 |
| `tt_um_ro_puf.v` | 2286 | 5407 |

The root `config.json` has no `MACROS` block and no `VERILOG_FILES_BLACKBOX`,
so it does not know Arm B exists. `test/` and `info.yaml` still match their
dualarm copies exactly. `src/` is the one that drifted, and it drifted on
22 July when dual-arm v2 landed and nobody copied it back.

So the literal instruction would have written four files into a folder the
mirror never reads, left `dualarm/src/` untouched, and hardened the two-arm
design while every artefact in `chip/` claimed a third arm. The runbook paths
are corrected. `G3_RUNBOOK.json` now names `dualarm/src/` and
`dualarm/info.yaml` throughout, and step 2 carries a `resync` that copies
`dualarm/src` over the top-level `src` afterwards, which is the arrangement
`test/` has had all along.

## What the modules turned out to be

That was the cheap finding. The expensive one is what would have been
installed.

`gen_e2_rtl.py` opens three files: `OBSERVABILITY.json`, `ARMC_REGIONS.json`
and `e2_acceptance.csv`. It never opens the RTL it is replacing. It writes a
fresh top and a fresh core from the pin specification, which is a reasonable
way to build something that has never existed and a terrible way to replace
something that has. Every decision the live design earned between June and
July is simply absent from the result, because the specification does not
mention any of them.

Four of them, in the order they matter.

**Arm B is gone.** The live top instantiates `ro_macro_hard u_rob0` through
`u_rob15` flat, and its header explains why the names cannot change: they are
the keys of `MACROS.ro_macro_hard.instances` in `config.json`, which is how
the flow pins each copy of the hardened GDS to its spot on the grid. The
draft instantiates none of them. It declares `armb_out`, hands it to
`ro_puf`, and never drives it. Sixteen of sixteen present in the live top,
zero of sixteen in the draft, counted from the config rather than from a
list I typed.

**The ripple counter is clocked through an AND gate again.** The live core
assigns `tff_clk[0] = sel_ro`, and above it sits a paragraph explaining that
an earlier revision used `sel_ro & en_window`, that `en_window` belongs to
the xclk domain and can fall at any phase of a ring running near 570 MHz, and
that the gate could therefore chop the last high pulse into a runt on a clock
net. There is a SPICE phase sweep behind the paragraph. The draft says
`wire gated_ro = sel_ro & en_window;` and clocks the counter off that. This
is not a new bug. It is the old bug, regenerated.

**The count is published before it has settled.** The live core runs a
four-state machine, stops every oscillator, drains a two-flop `async_reg`
sampler, requires three consecutive equal synchronized samples, and only then
assigns `count_out = count_latched`. If the counter does not settle it leaves
`done` low rather than returning a torn word. The draft assigns
`count_out = cnt` straight off the asynchronous ripple counter and raises
`done` on the cycle the window closes.

**Both synchronizers are missing.** The live top runs the seven-bit control
bundle through `ui_meta` and `ui_sync` before anything reads it, because the
board GPIOs are asynchronous to clk, and folds `ena` into the asynchronous
project reset so that pulling it low shuts down a running oscillator even
with the clock stopped. The draft edge-detects `ui_in[0]` directly in the clk
domain and ties `ena` into the `_unused` bundle.

And then the one that would not have failed loudly at all.

**Arm C is not the same ring as Arm A.** Both are an enable NAND and thirty
inverters, and `armc_cost.py` priced them at the same 32 cells, which is
right. The output buffer is not in the same place. `ro_macro.v` taps
`n[N_INV/2]`, halfway down the chain. `ro_armc.v` taps `n[N_INV]`, the
feedback node, which already carries the NAND's B input. So the buffer's
input capacitance sits on a different node in each arm, and the feedback node
in Arm C carries a load the same node in Arm A does not.

Whether that shifts the frequency enough to measure is a SPICE question and I
have not answered it. What I can say without SPICE is that Arm C exists so
that one arm differs from another in placement treatment and in nothing else,
that G.4 preregisters a comparison between them, and that a fixed
difference in the circuit is a confound whichever way the number comes out.
The file's own header says "electrically identical to `src/ro_macro.v`". It
is not, and the header is the part I would have believed.

## The reason none of this was caught

The gate ran ninety-seven commands and every one of them passed. Six of those
commands regenerate the drafts and diff them against the committed copies,
which proves the generator is deterministic. Not one command compiled a `.v`
file. The drafts are not merely wrong, they do not parse:

    e2_ro_puf_core.v:72: syntax error
    e2_ro_puf_core.v:72: error: Invalid port connection expression.
    e2_ro_puf_core.v:76: error: Syntax error in continuous assignment

Lines 72 and 76 both apply a part-select to a parenthesised expression,
`(i + 2 * N_PER_ARM)[SEL_W-1:0]`, which is not legal in Verilog-2001 or 2005.
The live core does the same arithmetic the legal way, through a
`localparam integer SB` it can then part-select. A compiler would have said
so on day seven.

## What the script does

`chip/lint_rtl.py`, 843 lines. Two halves, and they are deliberately
different kinds of check.

The compiler half is `iverilog -g2005 -Wall` over a file set with the
standard cells stubbed out. E01 is elaboration, E02 is width warnings, which
is what the runbook's lint step names as its stop condition. The stubs are
built from the pin names the design itself uses, gathered from its own
instantiations, because a hand-written table of sky130 pin names is exactly
the habit A.1 was corrected for and `armc_cost.py` still carries. Every stub
port is declared `inout`. That means the elaboration checks names and arity
and deliberately does not check pin direction, and direction is one more
thing waiting on `extraction/cell_library.py`.

The structural half needs no compiler and is where the real value is, because
findings two through five are all legal Verilog:

| | |
|---|---|
| R01 | no part-select applied to a parenthesised expression |
| R02 | the ripple counter's first stage is clocked by an ungated ring output |
| R03 | `count_out` is published from a register |
| R04 | the stopped-ring settle handshake is present |
| R05 | the top synchronizes `ui_in` through two `async_reg` stages |
| R06 | every macro instance named in `config.json` is instantiated in the top |
| R07 | `ena` takes part in the project reset |
| R08 | the Arm C ring matches the Arm A ring node for node |

Both halves run against two file sets. The live design is required to pass
and does, nine checks with R08 not applicable because there is no Arm C in
it. The drafts fail nine of ten; E02 is the only one they pass, and only
because a file that will not parse produces no width warnings.

A check that does not apply reports `n/a` and is counted separately from the
passes. On 31 August `B07` in the runbook read an empty gate list inside the
clone and reported green, and that is a worse failure than a missing check,
so nothing here is allowed to pass by finding nothing.

The drafts are reported and not enforced. `RTL_LINT.json` records their
state and the gate diffs it, so the state cannot change without the diff
moving, which is the same arrangement the release manifest uses for the CI
actions still pinned to tags. What the exit code enforces is the live design.

## Three things I got wrong while writing it

**R08 reported a difference that does not exist.** The first version compared
the two ring modules as text. `ro_macro.v` writes its inverter chain as
`for (i = 1; i <= N_INV)` with `.A(n[i-1])`, and `ro_armc.v` writes the same
chain as `for (i = 0; i < N_INV)` with `.A(n[i])`. Those elaborate to
identical netlists and the check called them different, which buries the real
finding under a false one. It expands the generate loop now and compares
elaborated nets, and it reports the one line that matters:
`sky130_fd_sc_hd__buf_1 pin A is n[15] in Arm A and n[30] in Arm C`. The
fixture that proves R08 can pass is deliberately written with the opposite
loop bounds, so a regression to text comparison fails the selftest.

**`RTL_LINT.json` could not diff clean against itself.** The temp directory
that iverilog compiles in is different every run and its name landed in every
recorded message, so two consecutive runs disagreed and the gate would have
gone red forever for a reason with nothing to do with the RTL. Same shape as
`RELEASE_MANIFEST.json` recording its own hash on 31 August. The path is
stripped now, and I ran it twice and diffed before wiring it in rather than
assuming.

**The recorded file depended on the machine.** Once the paths were stripped it
still differed between a machine with iverilog and one without, because it
recorded whether the compiler ran and which checks had therefore failed. That
is a fact about the machine and not about the design, and the gate diffs the
file. Only the structural checks are recorded now. The compiler half is
enforced through the exit code instead, and the exit code separates the two
cases: 1 means the RTL failed, 2 means nothing was compiled. The bridge VM has
no iverilog, so 2 is what a session gets, and it should not be allowed to read
the same as success.

## What is checked by code and what I checked by hand

Everything in the table above is a check with a planted fault behind it. Nine
faults, each asserted to trip exactly its own check, plus two controls: the
untouched live design passes everything, and a matching Arm C ring passes
R08. One fault trips two checks on purpose, the part-select, because R01 and
E01 are the same fault seen with and without a compiler and the selftest names
both rather than pretending it is one.

What I have not checked by code: that the tap difference in Arm C actually
moves the frequency. That wants SPICE and it is not in this script. The claim
here is only that the two rings are not the same netlist, which R08 does check
and which the file's header denies.

## What this does to G.3

Step 2 is blocked. The drafts have to be rebuilt from the live RTL rather than
from the pin specification, which means `gen_e2_rtl.py` has to read
`dualarm/src/` and transform it, and that is a day's work on its own and
probably more. G.3's twelve steps and 4.5 days assumed the modules were ready.
They are not, and the runbook now says so in step 2's stop condition:
`chip/RTL_LINT.json` has to report the drafts installable before anything is
copied.

The gate is a hundred commands now, up from ninety-seven.
