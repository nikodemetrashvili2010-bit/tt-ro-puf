# Licensing, and one file that deliberately has no licence header

Everything I wrote is Apache 2.0, the same as `LICENSE` at the root of this
repository. This page covers the parts where that sentence is not the whole
answer.

## The PDN recipe is not mine

`dualarm/src/pdn_cfg.tcl`, `dualarm/pdn_cfg.tcl` and `array/pdn_cfg.tcl` are
modified copies of `pdn_cfg.tcl` from
[TinyTapeout/tt06-dffram-example](https://github.com/TinyTapeout/tt06-dffram-example).
That file carries a copyright line for Efabless Corporation, because the recipe
comes from OpenLane's own default, and it is Apache 2.0.

Until 2026-08-09 my copies said "copied from the tt06-dffram-example recipe" and
nothing else. The header was gone. Apache 2.0 section 4(c) says to keep
copyright and attribution notices in a derivative work, and section 4(b) says a
modified file has to carry a notice that it was changed, so both were missing
and Tiny Tapeout's own terms ask for the same thing. All three copies now carry
the upstream header, a link, and a list of what I changed.

I took the copy without recording which commit, so what the files say is that
the upstream was checked again on 2026-08-09 and still carries that header. A
commit I did not write down is not one I am going to reconstruct now.

## Cells and tools

The standard cells are `sky130_fd_sc_hd` from the SkyWater PDK, Apache 2.0, and
they are referenced rather than copied. The flow is LibreLane and OpenROAD, both
open source. None of that code is vendored here.

## The one file with no header, on purpose

`dualarm/src/ro_macro_hard.nl.v` is the gate-level netlist of the hardened
macro. It has no licence header and it is not getting one.

It is listed in `sim/spice/gono/evidence_manifest.json` as archived evidence,
pinned by git blob hash, and `sim/spice/gono/verify_provenance.py` fails if the
file changes at all. The point of that manifest is that the archived bundle is
frozen, so a comment added for tidiness would break the very check that makes
the bundle worth having.

I found this the direct way. I added the header, then went looking for what
reads the file, and the manifest was there. The header came back off. The copy
in `array/` is the same generated file and is left byte-identical to it.

Every other generated build output is left exactly as the flow wrote it, for the
same reason in weaker form: those files are records of a run, and editing a
record of a run makes it a worse record. That covers `dualarm/build_current`,
`build_debug`, `control_wokwi`, `macro/romacro_final`, `array/pdnfix4_final`,
`gds_build` and `sim/spice/gono/first_build`. They are all Apache 2.0 through
this page and the root `LICENSE`, and none of them carries a header.

`sim/verify_macro_provenance.py` checks all of this. It walks the repository,
requires a licence line on every hand-written source file, skips exactly the
files the manifest pins, and fails if the skipped set and the pinned set stop
matching.

## Two scripts that never reach here

`backup_to_repo.sh` and `test_backup_audit.sh` live on my disk and are written
around absolute paths on it. They are not mirrored into this repository, which
is why they have no headers and why the audit ignores them by name.
`REPRODUCIBILITY.md` describes what they do.
