# What is known about the build that produced this macro

`SIGNOFF.md` says this directory has no `commit_id.json`, so the PDK commit
behind the hardened macro is unrecorded. That is true and it stays true. What I
had not done until 2026-08-09 was look at what the build wrote about itself.
Some of it is recoverable, and leaving that unwritten made the gap look larger
than it is.

Everything below comes out of the files in this directory. Nothing here is from
memory, and `sim/verify_macro_provenance.py` reads them again and fails if this
page and the files disagree.

## Recoverable

The SPEF header names the tool and pins its version exactly. `spef/nom/
ro_macro_hard.nom.spef` records OpenROAD, from The OpenROAD Project, at commit
`dcf36133a369abc8f3c5e5738cd4d82e4903c0e0`. A git commit is a stronger record
than a release number, so parasitic extraction, placement and routing for this
macro are pinned to one revision of one tool.

The same header dates the run to 14:48:58 on Monday 22 June 2026. The Magic
layout in `mag/ro_macro_hard.mag` carries a Unix timestamp of 1782139740, which
is 14:49:00 UTC on the same day. Two files written by two different programs,
two seconds apart, so the date is corroborated rather than asserted.

That Magic file also records the technology as `sky130A`, which is the process
name but not a version of it.

`metrics.json` describes what came out: 226 instances over 795.763 square
microns, no unmapped instances, no synthesis errors, and no slew, fanout or
capacitance violations at any of the three timing corners. The instances are all
`sky130_fd_sc_hd` cells, which is checkable against `nl/ro_macro_hard.nl.v`.

## Not recoverable

The sky130A PDK commit. Nothing in these outputs records which open_pdks or
volare revision supplied the cells, and that is the one thing that would let
somebody rebuild this macro bit for bit.

The LibreLane version and the container image tag. Same problem, and neither
leaks into any output file here.

Whether the flow ran locally or in an action. The integrated build recorded that
much in its own `commit_id.json`; this one did not.

## What that costs

Less than it looks, and I want to be exact about why rather than wave it away.

The macro's physical views, the GDS, the LEF, the netlist and the SPEF, are all
in the repository. Every pre-silicon number about Arm B is derived from those
files and not from a rebuild, so nothing in the paper depends on being able to
reproduce this run. The extraction that feeds all of it is pinned to an OpenROAD
commit.

What is lost is the ability to rebuild the macro and get the same GDS. Somebody
repeating the work would have to accept the archived views as given, or rebuild
with a stated PDK version and show their result matches.

The integrated top-level build does record its PDK commit, so the chip as
submitted is reproducible. The gap is one level down and predates the discipline
that fixed it.

## Not fixable after the fact

I could guess the PDK version from the date, since 22 June 2026 narrows it. I am
not going to. A guessed commit in a provenance file is worse than an admitted
gap, because the next reader cannot tell which entries were read off a file and
which were reconstructed.
