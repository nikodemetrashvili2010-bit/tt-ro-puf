# Re-running the archived SPICE, on a different machine

`SIGNOFF.md` lists three things under "what is left" as having no run
behind them in the repository: the distributed-RC comparison over the
sixteen Arm A rings, the boundary flop sweep, and the seven boundary
sweeps through the selector. Each leaves a csv anyone with the
repository can read, and none of them can be recomputed without
ngspice and the PDK, neither of which CI has.

So for those three, the csv is the evidence and nothing checks it.
That is the same shape as a recorded number that cannot change without
someone noticing, which this project has spent weeks removing
everywhere else.

All three are reproduced now, on a machine that has never seen this
project, and all three come back the same.

## The environment, and why it is not the same one

The archived logs were produced on the Windows PC under WSL with
ngspice 45.2 and an open_pdks install at `/home/pc/pdks/sky130A`.

What ran here is ngspice 42 out of Ubuntu's archive, against a
`sky130A` tree assembled by hand, because `ciel` cannot reach its
release host through this container's proxy. The device models come
from `fossi-foundation/skywater-pdk-libs-sky130_fd_pr` at `403964d`,
which is the commit open_pdks pins in its own `sky130.json`, and the
standard cells from `efabless/skywater-pdk-libs-sky130_fd_sc_hd` at
`5a42fd0`.

Two things had to be patched to make that tree usable. Both are
recorded because they are exactly the sort of thing that quietly
changes an answer.

The google mirror of the primitive library has no
`cells/special_nfet_01v8` and no `cells/special_pfet_01v8_hvt` at all,
and 209 of the hd cells instantiate the first one. A deck built
against it dies at the first `mux4_2` with "unknown subckt". The
fossi-foundation repository has them and is the one open_pdks actually
downloads, so the tree was rebuilt from that.

`sky130_fd_pr__nfet_05v0_nvt.pm3.spice` carries a bare `include "..."`
with no leading dot, which is Spectre syntax and ngspice refuses it
outright. Commented out. Nothing in this design uses a 5 V device.

So the comparison below crosses two ngspice versions, two PDK installs
and two operating systems. That is a stronger test than re-running on
the same machine would have been, and it is also why a difference
would have been hard to attribute to anything.

## The frequency decks

**The nominal sixteen-ring deck**, `dualarm_par.spice`, the one the
whole go/no-go rests on. All sixteen frequencies match
`dualarm_par_out.txt` to every printed digit, 541.5340 through
570.7080 MHz.

**Both corner decks**, reproducing `docs/hardware_todo.md` item 6
exactly:

    corner     min      mean      max     p-p
    ss       276.2     283.6    291.7    5.46 %
    ff       840.3     863.1    888.3    5.56 %

## The seven boundary sweeps

Same method on each: regenerate the decks with
`gen_boundary_sweep.py`, run every deck, analyse with
`analyze_boundary_sweep.py`, then diff the csv against the archive
column by column rather than eyeballing the verdict line.

    sweep       phases  cols  result      edge swallowed on
    B15 ff          38    12  identical   2 phases
    A05 ff          38    12  identical   1
    B00 ff          38    12  identical   3
    B15 fine        13    12  identical   the step, below
    B00 fine        11    12  identical   the step
    B15 tt          38    12  identical   corner repeat
    B15 ss          76    12  identical   corner repeat

252 phases in all, which is the number `SIGNOFF.md` quotes. Every one
passes its own verdict: the flop resolves to a rail at every phase and
the count never moves by more than one edge.

The fitted selector behaviour comes back too, and that is the part
worth keeping. On each path the high level grows by a fixed number of
picoseconds rather than a fixed fraction: B15 +175 ps with 17.5 ps of
residual spread against 59.4 ps for the fraction fit, A05 +101 ps with
1.8 ps against 48.9 ps. That is a delay asymmetry moving a trailing
edge, not a path that scales a pulse, which is why the selector hands
the counter's rising-edge flop more margin than the tap had rather
than less. It is item 2's correction in `SIGNOFF.md`, arrived at from
the other end.

## The step, which is the number worth having

The two fine sweeps are the reason the others exist, and they come
back to the picosecond. B15 at the fast corner, 5 ps apart:

    phase  tap high   at sel_ro   final edge   toggles
      0      71 ps      -          swallowed     25
      4      97 ps      -          swallowed     25
      5     102 ps    144 ps       arrived       26
      6     108 ps    206 ps       arrived       26
     12     139 ps    288 ps       arrived       26

Nothing lands between 97 and 102 ps at the tap. Below it the last
pulse is a bump that never reaches the rail and the counter loses the
edge. Above it the pulse survives the selector and arrives 42 ps wider
than it left. B00 has the same shape one step later, swallowed up to
111 ps and arriving from 116 ps.

**The safety claim is on both sides of that step, not only above it.**
At 97 ps, edge swallowed, the flop still settles to 1.950 V with
nothing in the forbidden band. Being below the threshold costs one
count, which is what the settle handshake already absorbs, and not a
hung or torn output. That is why a sharp step here is tolerable rather
than alarming.

## The flop sweep, and a check that did not check

`gen_flop_sweep.py --corner ff`, 38 phases: the ring stopped across a
phase grid with a real `dfrtp_2` wired as a toggle stage off the tap.
Same verdict as the archive.

    counted toggles across phases: min 25, max 27, spread 2
    per-step changes: +0, +1
    monotonic in unit steps: yes
    PASS

**But it passed the first time on 36 of 38.**

Two decks, phases 18 and 19, had been killed mid-run by a batch
timeout and left a log with no results in it. `analyze_flop_sweep.py`
read the 36 `.raw.txt` files that did exist, found every one settled,
and printed PASS without mentioning a number. Nothing in its output
says how many phases it expected or how many it got.

It was caught because the deck count was being watched for an
unrelated reason, which is not a check.

This is the same family as `B07` reading an empty gate list in the
clone and reporting green, and the tap regex on 12 September that
matched nothing and pronounced on an empty set. An analyser that does
not state its own N can pass on a subset forever, and a subset of a
phase sweep is where a swallowed edge would hide: the two missing
phases sat in the middle of the grid, which is the narrow end.

Re-run, 38 of 38, still PASS. The finding is not that the answer
changed. It is that the tool could not have told me if it had.

`analyze_boundary_sweep.py` is better by accident, printing "across 38
phases" in its summary so a reader can see the count. It does not fail
on a short set either, and printing a number is not the same as
failing on it.

**Both are fixed.** Each now counts the deck files in the sweep
directory, which is the expected N and does not require the script to
know the grid, and fails naming the phases that have no result. The
planted fault is the real one: delete phases 18 and 19 from a complete
sweep and both scripts go from PASS to `FAIL: 2 of 38 phases have no
result: bnd_18, bnd_19`, exit 1. On a complete sweep both still pass,
`analyze_boundary_sweep.py --selftest` is still green, and the csv it
writes is byte-identical to the one written before the patch, so
nothing in the numbers above depends on the change.

The two files are in `analyzer_fix/` next to this note, 38 lines added
across them, and nothing else in the repository is touched.

## The distributed-RC comparison

The third of the three, and the one that mattered most to get back,
because it is the check on the lumped model the whole go/no-go uses.
`gen_rc_decks.py` for each of the sixteen Arm A rings, two decks
apiece: one with the SPEF's node capacitance lumped, one with its
resistors and coupling caps wired as extracted.

All 32 reproduce `rc_validation.csv` to the two decimals it records,
and `analyze_rc.py` returns the same verdict:

    spread: lumped 5.55%, RC 5.84% (ratio 1.05)
    per-ring shift: -1.34% to -0.66% (all slower)
    rank correlation lumped vs RC: 0.994
    fastest RO7 both models, slowest RO14 both models
    0 of 8 adjacent-pair bits reverse under the fuller model

The fuller model slows every ring and widens the spread slightly, and
the ordering does not move. None of the eight response bits flips.
That is the claim the lumped decks were standing on.

## What identical does and does not mean here

The boundary csv holds picoseconds as integers and voltages to four
decimals, and `rc_validation.csv` holds two decimals of a megahertz.
Any difference below those rounds away before the comparison sees it.
Two ngspice versions agreeing to the printed digit is not the same
claim as agreeing bit for bit, and this does not establish that.

What it does establish is the thing the gap was about. These numbers
are not an artifact of one machine, one ngspice build or one PDK
install, and a reader who wants to check them can rebuild the
environment from public pins and get the same files back.

## Not reproduced, on purpose

`gen_flop_sweep.py` at tt and ss. Only the ff flop sweep has an
archived result, so running the other two would be new data rather
than a check on the archive, and the point was the archive.

## Mistakes

Three, kept.

Two batch runners got started by mistake, and four simulations on two
cores pushed every deck past its own 300 second timeout, so decks were
killed and retried forever. Eleven minutes of zero progress with both
cores pinned is what that looks like from outside, and I read it as
slowness before I read it as failure. The timeout is 900 s now and a
failure prints into the runner's log rather than vanishing.

I ran the RC decks with `--log ro00_rc.log` and then watched
`analyze_rc.py` report every one of the sixteen rings missing, because
it looks for `ro00_rc_out.txt`. Not a repository problem:
`gen_rc_decks.py` documents `_out.txt` in its own usage block, and I
had not read it.

The first PDK tree was built from the google mirror, which cost about
forty minutes before the missing `special_nfet_01v8` explained itself
at the first `mux4_2`.

## What this cannot reach

Nothing here touches the three-arm build. Every deck above is Arm A of
the frozen two-arm design, because that is what the archived decks
were built from and the comparison is against those archives.

The run 83 artifacts are on the Windows machine and it is switched
off, so the three-arm netlist, DEF and SPEF are out of reach until it
is back. Staging them into this container while the machine was still
up was the obvious move and I did not make it.
