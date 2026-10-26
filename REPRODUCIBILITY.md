# Reproducibility

Raw logs and physical artifacts are checked in, but the historical tool
environment that made some of them was not fully recorded. This file
separates what reproduces from a bare clone from what needs an external PDK
and toolchain.

## From a clean clone

The verifiers and architectural models need only the Python standard
library:

```sh
python3 sim/ref_model.py                 # legacy 8-RO arithmetic sanity check
python3 sim/montecarlo.py                # assumed-distribution toy model
python3 sim/h3_audit.py                  # assumed-distribution toy threat model
python3 sim/spice/gono/verify.py
python3 sim/spice/gono/verify_macro.py
python3 sim/spice/gono/verify_dualarm.py
python3 sim/spice/gono/verify_provenance.py
python3 sim/spice/gono/verify_ring_topology.py
python3 sim/spice/gono/verify_build_bundle.py
python3 sim/spice/gono/verify_noise.py
python3 sim/spice/gono/sensitivity.py
python3 sim/spice/gono/compensation.py
python3 sim/spice/gono/predictable_bits.py
python3 sim/spice/gono/compensated_bits.py
python3 sim/spice/gono/build_transfer.py
python3 sim/spice/gono/matched_arm.py
python3 sim/spice/gono/pairing_policy.py
python3 sim/spice/gono/numerical_audit.py
python3 sim/spice/gono/verify_predictability.py
python3 sim/spice/gono/real_world.py     # heat, wire current, supply drop, taps
python3 sim/verify_datasheet.py
python3 sim/spice/gono/analyze_noise.py --selftest
python3 sim/spice/gono/analyze_noise.py
python3 sim/spice/mc/analyze_mc.py sim/spice/mc/mc_out.txt
```

Each verifier exits nonzero on failure. A pass means the headline numbers
match the checked-in raw logs and CSV files; independent replication still
needs a fresh SPICE run against your own PDK install.

Worth knowing which is which. The corner sweep, the sixteen Arm B instances,
the selector sweep, the supply sweep and the macro RC comparison all have their
raw simulator output in the repository, so those verifiers really do re-derive
from logs.

So does everything run on the release build. `sim/spice/gono/rc3/` holds the
128 ring decks of Arms A and C with their logs, `sim/spice/gono/mux3/` the 96
selector decks, `sim/spice/gono/bnd3/` the eight boundary sweeps through B13,
the three through B00 and the screen of all 48 paths,
`sim/spice/gono/armb3/` the Arm B instance decks at ss, tt and ff, and
`sim/spice/gono/real_world/` the power and wire-current decks `real_world.py`
reads. CI rebuilds `rc_validation_3arm.csv`, `rc_validation_armc.csv`,
`mux3/mux3_validation.csv`, the eleven `boundary_validation_*_3arm*.csv` and
`boundary_screen_ff.csv` from those logs and diffs each against the committed
copy, the same way it has done for `mux_validation.csv` since August. The Arm
B logs have no csv;
`analyze_instance.py --build release` reads each corner and
`verify_instance_corners.py --build release` reads all three.
`sim/spice/magic/` holds the 96 ring decks of the second extraction,
magic's, with their logs, and CI rebuilds its `magic_rings.csv` from them
and diffs it the same way.

The boundary waveforms are reduced with `reduce_raw.py --kind bnd`, which keeps
the crossings at half the supply, the last 50 samples and any tail sample of q
inside the forbidden band. That is everything `analyze_boundary_sweep.py` looks
at, with one catch: the share of the tail spent in the band is taken over all
the tail samples, and the reduction drops the ones on a rail, so the share only
survives when it was zero, as it is on every archived deck. Run with `--verify`
it reads both copies of every deck through the real analyzer and fails on any
field that differs, so a deck where it was not zero cannot slip through.

Three do not: the sixteen-ring distributed-RC comparison (`rc_validation.csv`),
the counter-boundary flop sweep, and the seven two-arm boundary sweeps through
the selector (`boundary_validation_A05.csv` and the rest without `3arm` in the
name). For those three the CSV is the primary record and a verifier can only
check that the CSV is self-consistent. All three were run again on 17 September
on a different machine and came back the same, which is a repeat and not a
check against my logs (`docs/phaseG_spice_rerun.md`). The release build's
coarse sweep through B13 had no logs either until 22 September, when it was run
again and kept, along with three finer ones run that day for the first time.

Rerunning them is the only way to check them, and the decks regenerate
deterministically so that is possible. The provenance check binds the archived
source and evidence blobs to a reachable historical commit. The bundle check is
narrower and asks one question: did the DEF, netlist, SPEF and metrics in an
archived build folder come from the same flow run. It says nothing about
whether that run was any good.

Figures regenerate with the pinned packages in `requirements-analysis.txt`:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-analysis.txt
python3 sim/spice/gono/analyze.py
python3 docs/figures/make_block_diagram.py
python3 docs/figures/make_block_diagram.py --arms 3
python3 docs/figures/make_floorplan.py
python3 sim/spice/gono/make_figures.py
python3 sim/spice/gono/make_dualarm_figure.py
python3 sim/spice/gono/make_bits_figure.py
```

The paper builds with pandoc and LibreOffice: `sh docs/build_paper.sh`. PNG
bytes can still differ across operating systems because fonts and renderer
libraries are not locked, so compare the derived numbers rather than the
image bytes.

## SPICE deck generation and execution

Set `PDK_ROOT` to the directory containing the PDK and `PDK` to its
directory name (default `sky130A`). The historical SKY130 PDK commit was not
recorded, so note your installed PDK revision next to any reproduced result.

```sh
export PDK_ROOT=/absolute/path/to/pdks
export PDK=sky130A
export FRESH_SPEF=/absolute/path/to/final/tt_um_nikodemetrashvili20_ro_puf.nom.spef
export FRESH_DEF=/absolute/path/to/final/tt_um_nikodemetrashvili20_ro_puf.def
export FRESH_OUT=/tmp/tt-ro-puf-dualarm
python3 sim/spice/gono/gen_dualarm_decks.py \
  --spef "$FRESH_SPEF" --def "$FRESH_DEF" --output-dir "$FRESH_OUT"
python3 sim/spice/run_ngspice.py \
  "$FRESH_OUT/dualarm_ctrl.spice" --log "$FRESH_OUT/dualarm_ctrl_out.txt"
python3 sim/spice/run_ngspice.py \
  "$FRESH_OUT/dualarm_par.spice" --log "$FRESH_OUT/dualarm_par_out.txt"
python3 sim/spice/gono/verify_dualarm.py \
  --spef "$FRESH_SPEF" \
  --ctrl "$FRESH_OUT/dualarm_ctrl_out.txt" \
  --par "$FRESH_OUT/dualarm_par_out.txt"

# The archived 32-oscillator deck can be run without regenerating it.
python3 sim/spice/run_ngspice.py \
  sim/spice/gono/ro_all_par.spice --log /tmp/ro_all_par.txt
python3 sim/spice/run_ngspice.py \
  sim/spice/mc/mc_matched.spice --log /tmp/mc_out.txt
```

`run_ngspice.py` replaces only the SKY130 model-library and standard-cell
include paths, in a temporary copy of the deck; it never mutates the tracked
deck. The generators use the same environment variables and fail when the model
files are missing. `gen_dualarm_decks.py` needs all Arm A ring nets in the SPEF
and placement centroids for all 16 oscillators in a matching DEF from the same
final run.

Its defaults point at the coherent `dualarm/build_current/` bundle; the older
`dualarm/build_debug/` snapshot is a mixed-stage checkpoint that the generator
rejects if given. Keep regenerated files outside the evidence directories and
inspect `git diff` before accepting any regenerated data.

The verifiers accept `--ctrl`, `--par`, `--log-5p`, `--log-1p`, `--csv`,
`--spef`, and related path options (see `--help`), so a fresh run can be
checked without touching the archived logs.

The distributed-RC comparison on the release build has its logs in
`sim/spice/gono/rc3/`, and that folder's README gives the commands for both
arms and all three corners. `gen_rc_decks.py --arm C` writes Arm C's decks;
Arm C numbers its inverters from 0 where Arm A's rings number them from 1, and
the generator carries that difference so the caller does not have to.

The same comparison on the baseline, behind Section 5.5 of the paper and item 7
of `docs/hardware_todo.md`, has no archived logs, so it is regenerated like
this:

```sh
for i in $(seq 0 15); do python3 sim/spice/gono/gen_rc_decks.py --ro $i --output-dir /tmp/rc16; done
for f in /tmp/rc16/*.spice; do ngspice -b $f -o ${f%.spice}_out.txt; done
python3 sim/spice/gono/analyze_rc.py --dir /tmp/rc16 --ro $(seq 0 15)
```

Each `_rc.spice` line of the generator output ends with the number of second
listings it dropped, 21 to 36 depending on the ring. That number is worth
reading. A coupling capacitor is recorded under both of the nets it joins, so a
generator that writes out every listing builds each internal coupling twice, and
mine did until 2026-07-30. The lumped frequencies are unaffected by that fix, so
they double as a check on the environment: they should come back matching the
`lumped_MHz` column of `sim/spice/gono/rc_validation.csv`, which holds the
frequencies from the corrected run.

The fast-corner selector sweep behind item 2 of `docs/hardware_todo.md` had no
archived logs until 2026-08-07, and this section was four days late saying so.
`sim/spice/gono/mux/` holds 192 files: a deck, a console log and a reduced
waveform for each of the 32 decks and 32 blocked controls. CI regenerates
`mux_validation.csv` from that folder and diffs it byte for byte against the
committed copy, and `verify_mux_archive.py` checks the archive for what
archiving gets wrong: a CSV row with no run behind it, a log filed under the
wrong oscillator, a missing control.

So the commands below are no longer the only way to get these numbers back. They
are still the way to get them from a fresh simulator rather than from my logs,
which is the stronger check, and they are what produced the archive:

```sh
python3 sim/spice/gono/gen_mux_sweep.py --output-dir /tmp/muxsweep --corner ff --control
cd /tmp/muxsweep && for f in mux_*.spice; do python3 <repo>/sim/spice/run_ngspice.py "$f" --log "${f%.spice}.log"; done
python3 <repo>/sim/spice/gono/analyze_mux_sweep.py /tmp/muxsweep --csv <repo>/sim/spice/gono/mux_validation.csv
```

Sixty-four decks at roughly twelve seconds each. The generator prints the cell
chain of every path, and those chains should match the `chain` column of the
committed `mux_validation.csv` exactly, since both come from the same routed
netlist. If they do not, the build in `dualarm/build_current/` is not the one the
csv was made from.

Since 2026-10-10 those commands do not write the archive's decks exactly. The
generator now ties one `o21a_2` the way the netlist does, which changes the
sixteen Arm B decks by one line each, and every deck of the B00 and B15
boundary sweeps below the same way. A fresh run would move those rows. On the
release build the same swap moved four paths by 4 or 5 ps at ff; the two-arm
ones have not been run with it. The archive is kept as it ran, and
`docs/phaseG_selector_tt_ss.md` has the reason.

The release build's sweep is the same three commands with
`--build dualarm/build_armc` and `--corner ff`, `tt` or `ss`, into
`sim/spice/gono/mux3/`, `mux3_tt/` and `mux3_ss/`. All 288 decks there are
what the generator writes now, and CI rebuilds each folder's csv from its
waveforms.

That csv changed shape on 2026-08-02.

It used to carry a single `narrowest_ps` column, which mixed high levels and
low levels together and was the source of the error described in item 2 of
`docs/hardware_todo.md`. It now carries the rise delay, the fall delay and the
two polarities separately. The rise delays are unchanged from the earlier run,
to the picosecond, so an older clone can be checked against a newer one on that
column.

The boundary sweeps behind item 1 have no archived logs either. Each takes about
eight minutes:

```sh
python3 sim/spice/gono/gen_boundary_sweep.py --output-dir /tmp/bndsweep --corner ff --osc B15
cd /tmp/bndsweep && for f in bnd_*.spice; do python3 <repo>/sim/spice/run_ngspice.py "$f" --log "${f%.spice}.log"; done
python3 <repo>/sim/spice/gono/analyze_boundary_sweep.py /tmp/bndsweep --vdd 1.95 --csv <repo>/sim/spice/gono/boundary_validation_B15.csv
```

Swap `--osc A05` and the matching csv name for the other bracket. The fine sweep
that located the surviving width adds three arguments and runs thirteen decks:

```sh
python3 sim/spice/gono/gen_boundary_sweep.py --output-dir /tmp/bndfine --corner ff --osc B15 --base-ns 30.10 --step-ps 5 --steps 13
```

The release build's sweeps through B13 keep their decks, logs and reduced
waveforms in `sim/spice/gono/bnd3/`: at ff on four grids since 22 September,
at tt and ss since 18 October, and CI rebuilds every csv from them. The tt and
ss decks come from the same generator:

```sh
python3 sim/spice/gono/gen_boundary_sweep.py --build dualarm/build_armc --osc B13 --corner tt --output-dir /tmp/bnd_tt
python3 sim/spice/gono/gen_boundary_sweep.py --build dualarm/build_armc --osc B13 --corner ss --steps 76 --output-dir /tmp/bnd_ss
python3 sim/spice/gono/gen_boundary_sweep.py --build dualarm/build_armc --osc B13 --corner tt --base-ns 30.15 --step-ps 5 --steps 13 --output-dir /tmp/bnd_tt5
python3 sim/spice/gono/gen_boundary_sweep.py --build dualarm/build_armc --osc B13 --corner ss --base-ns 33.20 --step-ps 5 --steps 13 --output-dir /tmp/bnd_ss5
```

The slow corner needs the 76 steps for its longer ring period. The two 5 ps
grids start at the last coarse phase that lost the pulse and run 60 ps on.
On a two-core machine run the decks one at a time; two at once took three
times as long each on 18 October.

The screen of 26 October puts every path through four phases on B13's grid,
one folder a path in `bnd3/screen_ff/`, and B00, the path that lost all four,
has three sweeps of its own beside it. Each folder holds the decks the line
below writes, the logs, and the waveforms reduced with `reduce_raw.py --kind
bnd`:

```sh
for d in sim/spice/gono/bnd3/screen_ff/*/; do osc=$(basename $d); python3 sim/spice/gono/gen_boundary_sweep.py --build dualarm/build_armc --osc $osc --corner ff --base-ns 30.080 --step-ps 10 --steps 4 --output-dir /tmp/screen/$osc; done
python3 sim/spice/gono/gen_boundary_sweep.py --build dualarm/build_armc --osc B00 --corner ff --base-ns 30.100 --step-ps 5 --steps 13 --output-dir /tmp/bnd_b00_5
python3 sim/spice/gono/gen_boundary_sweep.py --build dualarm/build_armc --osc B00 --corner ff --base-ns 30.110 --step-ps 1 --steps 6 --output-dir /tmp/bnd_b00_1
python3 sim/spice/gono/gen_boundary_sweep.py --build dualarm/build_armc --osc B00 --corner ff --base-ns 30.111 --step-ps 0.2 --steps 6 --output-dir /tmp/bnd_b00_02
python3 sim/spice/gono/boundary_screen.py sim/spice/gono/bnd3/screen_ff --control sim/spice/gono/boundary_validation_B13_3arm_5ps.csv --csv /tmp/screen_ff.csv
```

192 decks for the screen and 25 for B00, about 33 s each here.

Both analyzers carry planted-fault checks that need no PDK and no ngspice, so the
analysis can be exercised on any machine before the decks are run:

```sh
python3 sim/spice/gono/analyze_mux_sweep.py --selftest
python3 sim/spice/gono/analyze_boundary_sweep.py --selftest
```

The archived decks use nominal TT models at 1.8 V and transfer only SPEF
`*D_NET` total capacitance as lumped loads. Distributed resistance, coupling
topology, mismatch, PVT sweeps, and supply noise are out of scope here; the
paper's limitations section says what that means for the claims.

## Tiny Tapeout's own sources

`sim/tt_fit.py` reads three of Tiny Tapeout's repositories and wants them at
the commits it was written against, with `pip install gdstk klayout pyyaml`:

```sh
git clone https://github.com/TinyTapeout/tt-support-tools
git -C tt-support-tools checkout 01d5d2814fa9dd61e9d211e0b235a4a592a9316a
git clone https://github.com/TinyTapeout/tt-multiplexer
git -C tt-multiplexer checkout 885086c91ebbe5e636559f540c23a492a7d1284a
git clone https://github.com/TinyTapeout/tt-micropython-firmware
git -C tt-micropython-firmware checkout d485c7a9986336024e35d790568fca33be1c5665
python3 sim/tt_fit.py --tools tt-support-tools --mux tt-multiplexer \
    --sdk tt-micropython-firmware --final <run 83>/runs/wokwi/final
python3 sim/tt_fit.py ... --selftest
```

`--final` is the `runs/wokwi/final` folder of the build the GDS came from,
for its LEF and powered netlist; neither is archived here. Seven lines of
`ok`, and the selftest ends "all 11 caught". The power switch's three decks
are in `sim/spice/pg/` and run with `sim/spice/run_ngspice.py` like any other.

## Recorded development environment

The devcontainer includes ngspice and pins the revisions that are actually
known:

- base distribution: Ubuntu 24.04 devcontainer image tag;
- TinyTapeout support tools: `d65690eeb1d4afd26aef795c805a23d9d9daf9d1`;
- LibreLane: `2.4.2`;
- Verible: `v0.0-4023-gc1271a00`;
- cocotb: `2.0.1`; pytest: `8.4.2`; matplotlib: `3.10.8`.

APT packages, the base-image digest, transitive Python dependencies, the
SKY130 PDK, and the `ttsky26d` GitHub Action tag are not immutably locked by
the historical repository. For a publishable rerun, record `python
--version`, `ngspice --version`, `iverilog -V`, the container image digest,
the PDK commit, the source commit, and the resolved action SHAs.

The post-start helper links `./tt` to the exact image checkout. It never
performs an implicit `git pull` and leaves an existing non-symlink `tt`
directory unchanged.

## Which file is which

The repository keeps failed and superseded builds as provenance, so here is
the short answer to "which one is current":

- Tapeout candidate GDS and its checks: `dualarm/build_armc/`, run 83's
  three-arm build. The README's figures for Arm A and Arm C come from its
  `.nom.spef`, through the six Arm A decks stored beside it and the ring decks
  in `sim/spice/gono/rc3/`.
- The two-arm baseline: `dualarm/build_current/`, frozen. This is what the
  paper's 5.53% and most of its other numbers come from, via its `.nom.spef`
  and the go/no-go logs in `sim/spice/gono/`. The nine-build dispersion band
  around it lives in `dualarm/placement_sweep/`.
- Figures 2 and 3 come from the earlier 32-oscillator build under
  `sim/spice/gono/first_build/`; Figure 4 comes from `dualarm/build_current/`.
- Everything under `dualarm/build_debug/`, `array/`, and
  `macro/romacro_final/` is historical or component evidence, not the tapeout
  chip. `build_debug` in particular is an older, incomplete snapshot kept only
  for contrast.

## How this repository gets updated, and what went wrong with it

I do not work inside this repository. I work in a folder on my own disk and
copy it across with a script before every commit. That script had a defect, and
an outside reviewer hit the symptom before I found the cause. It copied and it
never pruned. Files I deleted in the working folder stayed here for good, and
the reviewer read four of them as current: a positions CSV full of `nan`, two
experimental configuration files, and a mangled author name. None of the four
existed on my side. He was reading things I thought I had deleted months ago.

The script now keeps every copy rule in one table and reads the same table
backwards, so it can ask where any file here came from. If a file has no source
in my working folder it stops and prints the list rather than committing.

It also runs `git diff --no-index src dualarm/src`, the comparison
TinyTapeout's own workflow runs, and refuses if those two trees disagree. That
check would have caught the older bug directly: the prune list deleted one
experimental config from `src/` and left its twin under `dualarm/src/`, which
is why the stock test workflow has been red. The script itself stays on my
machine because it is written around absolute paths on my disk. Its checks are
tested against a throwaway pair of trees rather than against this repository.

## Freezing the final release

Provenance today binds the archived analysis bundle, not a locked tapeout
release. See the note in `sim/spice/gono/verify_provenance.py` for what that
check does and does not cover. Before I order silicon I will cut one tagged
release where everything lines up: source commit, TinyTapeout config, the macro
and top GDS, the DEF and SPEF, the metrics, the DRC/LVS/XOR reports, the deck
generators, the raw logs, and the paper numbers.

The same tag records the parts that can still move today. That means the
resolved SHAs behind `actions/checkout` and `TinyTapeout/tt-gds-action`, the
SKY130 PDK commit, the LibreLane and OpenROAD revisions, the container image
digest, `pip freeze`, and the tool versions listed above. After that the tag is
the artifact, not a branch that keeps moving.

## Physical evidence

See [SIGNOFF.md](SIGNOFF.md) for the per-artifact status.
