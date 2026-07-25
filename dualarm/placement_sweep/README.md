# Dispersion across nine builds

A single build tells you what the router did once. It does not tell you whether
that number is typical, and for a while I was quoting one build's peak-to-peak
figure as if it were a property of the design. So I ran the flow nine times to
find out what the spread actually looks like.

## What was varied, and what was not

I wanted to vary only the place-and-route seed. LibreLane 3.0.3 does not expose
it. OpenROAD's global placement accepts a `random_seed`, but the flow gives no
config variable for it, and patching the tool would have defeated the purpose of
the experiment, which depends on the toolchain being frozen.

So the knob here is `PL_TARGET_DENSITY_PCT`, swept from 56 to 64 in steps of 1.
Held fixed: the RTL, the sixteen Arm B macro locations, the floorplan size, the
constraints, the PDN, the LibreLane version, and the PDK. Changing the density
target nudges standard-cell placement without altering the design, which moves
the routing capacitance on the Arm A rings, which is the thing that sets the
dispersion.

So this is a placement-sensitivity sweep, not a seed distribution, and I have
tried to describe it that way everywhere it gets cited.

## Result

Nine builds, all hardened, all with their sixteen rings structurally intact.

| statistic | value |
|---|---|
| median dispersion | 5.75% peak-to-peak |
| range | 4.19% to 6.99% |
| standard deviation | 0.80% |
| shipped build (density 60) | 5.53% |

Density on its own barely predicts dispersion (r = 0.32). That is the expected
outcome: the knob perturbs placement, it is not a physical cause of spread. Ring
capacitance spread and frequency spread do track each other across the set, from
4.7 fF and 4.19% at the tightest build to 7.8 fF and 6.99% at the widest.

I wanted to be sure the band was real and not just the flow being noisy. The
density-60 build rebuilds the shipped configuration and came back at 5.53%,
matching `build_current` to the digit, and I ran the whole sweep twice and got
identical numbers both times. The flow is deterministic, so what the band
measures is placement sensitivity.

An earlier build of this design reported 10.5%, which sits well outside this
band. Most of that range came from one oscillator the router had loaded with
24.4 fF while the other fifteen sat between 11.7 and 17.0 fF. Nothing was wrong
with the build and the heavy instance was a genuine routing outcome, but
peak-to-peak over sixteen instances will follow a single unlucky draw like that,
which is the reason I stopped quoting one build.

## Running it

Needs the LibreLane venv active, `PDK_ROOT` and `PDK` exported, and Docker
running. Roughly two hours for nine builds.

    bash dualarm/placement_sweep/run_placement_sweep.sh
    python3 dualarm/placement_sweep/plot_placement_sweep.py

The driver edits only the density value in `src/config.json`, hardens, copies out
the netlist, DEF, and nominal SPEF, checks ring topology, regenerates the
lumped-C decks, simulates, and appends one row to
`placement_sweep_results.csv`. It restores the original density when it
finishes. Per-build artifacts go to `~/placement_sweep_runs` rather than into the
repository; override with `SWEEP_ARCH`, and point at a different build directory
with `TT_BUILD_DIR`.

`plot_placement_sweep.py` prints the summary and writes `placement_sweep.png`.
It reports the density-60 point against the shipped figure as an explicit
determinism check.
