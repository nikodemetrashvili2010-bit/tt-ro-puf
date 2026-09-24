# Is the layout that ships the one that was analysed, and a new die picture

24 September. Two small things before the push, one of them asked for.

## The identity check

Every prediction in this repository was read off one layout, run 83's, kept
in `dualarm/build_armc`. The chip Tiny Tapeout makes is whatever GDS the last
green build produced when the project is submitted, and every push builds
again. Until today nothing compared the two.

They should be the same.

Over `src`, `dualarm/src`, `macro`, `array`, `test` and `info.yaml`, the diff
from run 83's commit to today touches `info.yaml` alone, and there only its
comments, the description and the text of one pin. The action tag is
`ttsky26d` on both sides and LibreLane is its default, 3.0.14.

But a tag is something Tiny Tapeout can move, and "should be" is not something
I can write under a prediction. This one has moved once since 8 September, on
the evening of the 18th, and only in four lines of the gate-level test action.
The build action is what it was, and so is the tools repository the build
checks out, still `01d5d28` on main, the commit run 83's `commit_id.json`
names.

`sim/release_identity.py` was written on 23 September and held back so that
day's commit stayed a day's size. It compares four files from the run
directory against the archive.

The GDS goes first, with the dates in every BGNLIB and BGNSTR record zeroed,
since those are the time the file was written. Then the DEF, byte for byte,
and if that differs it counts how many components moved and how many nets
were routed differently. The netlist byte for byte, and the SPEF with its
`*DATE` line dropped. Line endings are normalised first.

Its selftest builds a fake run directory and archive and plants the faults it
exists for: a polygon moved in the GDS, a component moved and a net rerouted
in the DEF, each of which has to be named in the report, and an empty run
directory, which has to come out missing.

Two cases have to come out identical: files that differ only in their dates,
and files that differ only in their line endings.

In CI it runs twice. The selftest is in the `archived-evidence` job, 158
commands now.

The real comparison is a step in the `gds` job after "Are the rings still
rings", and for now it only annotates: no `--strict`, and `continue-on-error`
on the step. A wrong path in a check that has never seen a real run directory
should not turn a good build red two months before the deadline. Once a run
has said identical, both come off.

## The die picture

Nikoloz said the chip image in the README looked glitched. The file was fine:
the blob on GitHub has the same hash as the one on disk, git treats it as
binary, and it has no transparency to go wrong in dark mode. It was the
drawing.

`make_floorplan.py` drew every placed cell as its own rectangle, 712 logic
cells and Arm A's 512, with the filler between them left out. At the 627
pixels GitHub gave it in the window I checked, the median logic cell is under
seven pixels wide and five tall, so the top of the die and everything right
of the macros came out as speckle.

The met4 stripes sat under the macros and only showed as stubs in the gaps
between them. It looked like a broken image.

It draws the GDS now, flattened: diffusion, poly, local interconnect and
metal 1 to 4, 115205 shapes on a dark die, the way a layout viewer shows it.
On top go outlines from the same build's DEF, the sixteen Arm B macros, the
box that holds Arm A's 512 cells, and six Arm C blocks. The six are the
sixteen rings' own boxes merged where they touch, and the script prints the
count rather than assuming it.

It regenerates byte for byte, 728 KB against the old 76. `gdstk` 1.0.1 joins
matplotlib and Pillow in `requirements-analysis.txt`. The figure is not in the
gate and was not before.

The README's status paragraph also said that on 20 September TTSKY26d was
still upcoming. On the 24th the shuttle page lists it as open, closing on 30
November, and the app says tiles and boards are not on sale yet. The
paragraph says that now.

## Mistakes

- The first draft of the script's docstring said the old figure failed
  because thousands of cells were under a pixel wide. It was 712 logic
  cells, most of them several pixels across. Measured before it landed.
- The first draft of the workflow comment said nothing had changed in what
  the build reads except comments in `info.yaml`. The description and a pin
  name changed too, so it says wording.

## Not covered

The comparison has never run against a real CI run directory. It reads the
same `runs/wokwi/final/def` and `final/nl` the placement and ring checks
already read, and expects one file ending `.nom.spef` under `final/spef/`,
the name the archived copy has.

The archive itself came out of run 83's submission artifact, whose
`commit_id.json` names the run, so it is also possible that the same layout
comes out of the run directory with different bytes. The first run after the
push says which.

If a build does differ, the annotation says how, but not what to do about
it. Reading the predictions again from the new build and pinning the
submission to an older run are both open, and that one is Nikoloz's call.
