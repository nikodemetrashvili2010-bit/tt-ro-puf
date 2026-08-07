# The control build for the warning triage

Four files out of an early one-tile build, kept here so that
`sim/spice/gono/triage_warnings.py` has something to disagree with.

The triage rules are all of the form "this recorded count equals this thing I
derived from the layout". A rule like that is easy to fit to one build without
noticing, because there is nothing to contradict it. This build contradicts it
in the right places. It returns ten disconnected pins where the shipped build
returns nine, and zero max-fanout violations where the shipped build returns
one, and the script matches both against their own `metrics.json`. That is what
makes me believe the rules rather than the passes.

It is a genuinely different design, not an earlier revision of the same one.
One tile of 161 by 111.52 um instead of four, 32 flat oscillators instead of
sixteen flat and sixteen hardened, no macro anywhere in it, 4325 instances
against 6477. It is also what killed my first explanation of the 25 unannotated
nets, which charged them to the sixteen black-boxed macros: this build has no
macro and the same offset of 16.

The full run lives in `gds_build/runs/wokwi/`, which is 119 MB and stays out of
the repository. These four files are the ones the triage reads, and they come to
2.1 MB.

    tt_um_nikodemetrashvili20_ro_puf.def        placement and connectivity
    tt_um_nikodemetrashvili20_ro_puf.nl.v       gate-level netlist
    tt_um_nikodemetrashvili20_ro_puf.nom.spef   nominal extraction
    metrics.json                                what the flow recorded

Run it with:

    python3 sim/spice/gono/triage_warnings.py --build dualarm/control_wokwi

Thirteen checks. The shipped build gets fourteen, the extra one being the
max-fanout violator's identity, which this build does not have because it has no
violation.

Do not update these files. The moment they track the shipped build they stop
being a control.
