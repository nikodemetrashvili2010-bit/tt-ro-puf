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

The chip image in the README looked glitched. The file was fine: the blob on
GitHub has the same hash as the one on disk, git treats it as binary, and it
has no transparency to go wrong in dark mode. It was the drawing.

`make_floorplan.py` drew every placed cell as its own rectangle, 712 logic
cells and Arm A's 512, with the filler between them left out. At the 627
pixels GitHub gave it in the window I checked, the median logic cell is under
seven pixels wide and five tall, so the top of the die and everything right
of the macros came out as speckle.

The met4 stripes sat under the macros and only showed as stubs in the gaps
between them. It looked like a broken image.

It draws the GDS now, flattened: diffusion, poly, local interconnect and
metal 1 to 4, 115205 shapes on a dark die, the way a layout viewer shows it.
On top go outlines from the same build's DEF: the sixteen Arm B macros, the
box that holds Arm A's sixteen rings, and each of Arm C's sixteen rings.

That is the second go. The first went up in `229f766` and still looked off.
Arm C was six boxes, the rings merged where they touch, under a label that
said sixteen rings. Every outline had a dark edge drawn under it, meant to
lift it off the layout, and at README size it read as a double line.

Now each ring has its own box and the edges are plain. The met4 stripes are
dimmer, the caption is a title over the plot instead of text squeezed inside
it, and a legend under the die counts A and C the same way, in rings.

It regenerates byte for byte, 647 KB against the old 76. `gdstk` 1.0.1 joins
matplotlib and Pillow in `requirements-analysis.txt`. The figure is not in the
gate and was not before.

The README's status paragraph also said that on 20 September TTSKY26d was
still upcoming. On the 24th the shuttle page lists it as open, closing on 30
November, and the app says tiles and boards are not on sale yet. The
paragraph says that now.

## What the first run said

Run 88 is `229f766`, the first build with the check in it. Archived
evidence, gds, precheck and the gate-level test green, the viewer red for
Pages as before. The annotation said the build was not the analysed layout,
and gave one reason, `gds differs sha256 ee3f557c4723 against 1608884203ce`.

It named the GDS and nothing else. The DEF, the netlist and the SPEF came
out identical to run 83's, so every cell sits where it sat, every wire runs
where it ran, and the extraction of it agrees to the last digit.

Magic writes the final GDS from that database, and the order it puts
structures and shapes out in is its own business. I had only zeroed the
dates.

So when the bytes differ, the check now compares the GDS again, structure by
structure, with the shapes inside each structure taken as a set. On run 83's
own GDS shuffled by hand, all 69 structures and every shape inside them put
in a random order, it says same layout. Move one point by 5 nm in that
shuffled copy and it names the cell the point is in.

Whether run 88's difference is only order is what the next run says. If it
is, the check reports identical and gives the reason. If not, it names the
structures that differ.

## Mistakes

- The first draft of the script's docstring said the old figure failed
  because thousands of cells were under a pixel wide. It was 712 logic
  cells, most of them several pixels across. Measured before it landed.
- The first draft of the workflow comment said nothing had changed in what
  the build reads except comments in `info.yaml`. The description and a pin
  name changed too, so it says wording.
- I wrote the GDS comparison on bytes with the dates zeroed and expected the
  first run to say identical. Run 88 disagreed on the GDS alone. With the
  DEF, netlist and SPEF identical, the question was always whether the
  layout matched, not whether the file did.
- This note said the archive came out of run 83's submission artifact. It
  did not: the archive's GDS and DEF are byte for byte `final/gds` and
  `final/def` from run 83's run directory, which I keep on my PC, and the
  submission artifact has no DEF in it at all.
- The picture's first layout version, the six merged blocks and the double
  lines, above.

## Not covered

The structure-by-structure comparison has not seen a real run directory
yet. Run 88 only ran the byte comparison.

If a build does differ in layout, the annotation says where, but not what to
do about it. Reading the predictions again from the new build and pinning the
submission to an older run are both open, and I have not decided which.
