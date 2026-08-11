# The supply sweep and the slow-corner rerun

*One of the run notes indexed in [`run_steps.md`](run_steps.md), which says what
they are and what they are not evidence of. Paths are left as they were run.*

Run 2026-08-05. This closes item 5 and fixes the ss boundary sweep that passed
without testing anything on 08-04.

## The bug that ate the first attempt

The current column read exactly 0.0 uA, which cannot be right when the deck also
reports 0.0995 V across 1000 ohm. I assumed twice that ngspice wanted a different
spelling for a voltage source's branch current, and wrote a second spelling next
to the first so that one run would settle it. Both failed, because spelling was
never the problem.

A deck carrying a `.save` line keeps only the vectors that line names. Neither
save line named a current, so `vdd#branch` was not in the plot and no spelling
could find it. Adding `i(Vdd)` to both save lines fixed it.

The check that proved it, on the 1000 ohm deck alone before running the other
fifteen: 99.46 uA through 1000 ohm is 0.09946 V, and 1.8 minus that is 1.700536,
which is what `vlocal` reads to the digit. Two separate measurements agreeing.

`analyze_supply.py` now rejects a zero current at the door instead of averaging
it into a verdict, and its selftest feeds it a log with that exact fault.

## What ran

    export PDK_ROOT=/home/pc/pdks && export PDK=sky130A
    cd "/mnt/d/silicon/silicon chip/sim/spice/gono"
    python3 gen_supply_decks.py --output-dir /tmp/supply
    cd /tmp/supply
    for f in supply_*.spice; do python3 "/mnt/d/silicon/silicon chip/sim/spice/run_ngspice.py" $f --log ${f%.spice}_out.txt > /dev/null; done
    cd "/mnt/d/silicon/silicon chip/sim/spice/gono" && python3 analyze_supply.py --dir /tmp/supply

12 of 12. The sixteen logs are now archived in `sim/spice/gono/supply/`, so
`python3 analyze_supply.py --dir supply` reproduces the verdict from a clone with
no ngspice and no PDK. That is the first sweep in this project to be
re-derivable, and I want the rest to follow.

Then the slow corner, which needs 76 steps because 38 x 50 ps spans 1.9 ns and
the ss period is 3439 ps:

    python3 gen_boundary_sweep.py --corner ss --osc B15 --steps 76 --output-dir /tmp/bndss
    cd /tmp/bndss
    for f in bnd_*.spice; do python3 "/mnt/d/silicon/silicon chip/sim/spice/run_ngspice.py" $f --log ${f%.spice}_out.txt > /dev/null; done
    cd "/mnt/d/silicon/silicon chip/sim/spice/gono" && python3 analyze_boundary_sweep.py /tmp/bndss --vdd 1.6 --csv boundary_validation_B15_ss.csv

`--vdd 1.6` matters. The analyzer defaults to 1.95 for the fast corner, and
without it every ss phase would look like it stopped short of the rail. The decks
have to run from their own directory, since ngspice drops each `raw.txt` into the
directory it runs in.

Then the library's opinion of the narrowest captures:

    python3 check_pulse_width.py --corner ss --narrowest 810
    python3 check_pulse_width.py --corner tt --narrowest 484

## Pushing it

### 1. Copy the working tree into the clone

    cd "/mnt/d/silicon/silicon chip" && bash backup_to_repo.sh

Ends with `DONE. Now commit and push in GitHub Desktop.` and lists nothing over
20 MB. The supply logs are 64 KB in total, so nothing here is large.

### 2. Two commits in GitHub Desktop

**Commit 1, the measurements.** `sim/spice/gono/gen_supply_decks.py`,
`analyze_supply.py`, the sixteen logs in `sim/spice/gono/supply/`,
`boundary_validation_B15_ss.csv`, and `.github/workflows/gds.yaml`.

    Measure the supply confound across four decades, and sweep ss properly

**Commit 2, the writing.** `docs/hardware_todo.md`, `SIGNOFF.md`,
`sim/spice/gono/README.md`.

    Write up items 3, 5 and 8, and correct the narrowest-pulse claim

### 3. One push, then watch the gds action

The evidence job now runs `analyze_supply.py --selftest`, `verify_instance.py`
and the archived supply sweep itself, so a red there is real and not the usual
`gl_test` noise.
