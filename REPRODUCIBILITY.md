# Reproducibility

The repository contains raw logs and physical artifacts, but the historical
environment that created every artifact was not fully recorded. This guide
separates checks that are reproducible from a clone from runs that require an
external PDK/toolchain. It does not assign a made-up revision to old evidence.

## From a clean clone

The numerical verifiers and architectural demonstrations use only the Python
standard library:

```sh
python3 sim/ref_model.py                 # legacy 8-RO arithmetic sanity check
python3 sim/montecarlo.py                # assumed-distribution toy model
python3 sim/h3_audit.py                  # assumed-distribution toy threat model
python3 sim/spice/gono/verify.py
python3 sim/spice/gono/verify_macro.py
python3 sim/spice/gono/verify_dualarm.py
python3 sim/spice/gono/verify_provenance.py
python3 sim/spice/mc/analyze_mc.py sim/spice/mc/mc_out.txt
```

Each verifier exits nonzero on failure. A PASS proves consistency with the
checked-in raw text/CSV files; it does not validate fabricated silicon or
extend the modeled physical scope. The provenance check binds the archived
source and evidence blobs to a reachable historical commit but cannot recover
the unrecorded flow/PDK environment. Figure and paper regeneration install the
pinned dependencies in `requirements-analysis.txt`:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-analysis.txt
python3 sim/spice/gono/analyze.py
python3 docs/figures/make_block_diagram.py
python3 sim/spice/gono/make_figures.py
python3 sim/spice/gono/make_dualarm_figure.py
python3 docs/build_paper.py
python3 docs/verify_paper.py
```

The analysis scripts are deterministic for their checked-in seeds. PNG bytes
can still differ across operating systems because fonts and renderer libraries
are not fully locked; compare the derived numbers as well as the images.

## SPICE deck generation and execution

Set `PDK_ROOT` to the directory containing the PDK and `PDK` to its directory
name (default `sky130A`). The repository does **not** record the historical
SKY130 PDK commit, so record `git rev-parse HEAD` (or the package identifier) of
your installed PDK with any reproduced result.

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
include paths in a temporary deck. It does not mutate the tracked deck. The
deck generators use the same environment variables and fail when the required
model files are missing. `gen_dualarm_decks.py` also requires all Arm A ring
nets in the SPEF and placement centroids for all 16 oscillators in the matching
DEF. Its checked-in default inputs are an intentionally rejected mixed-stage
snapshot. Use `--spef`, `--def`, and `--output-dir` with a coherent final run;
the output directory keeps regenerated decks and CSV data separate from the
archived evidence. Inspect `git diff` before accepting any regenerated data.

The go/no-go verifiers accept `--ctrl`, `--par`, `--log-5p`, `--log-1p`,
`--csv`, `--spef`, and related path options shown by `--help`, so a fresh run
can be checked without replacing the archived logs.

The archived go/no-go decks use nominal TT models at 1.8 V and transfer only
SPEF `*D_NET` total capacitance as lumped capacitors. Distributed resistance,
coupling topology, mismatch, PVT sweeps, supply noise, and measured-die effects
are out of scope. The Monte Carlo sqrt(31) scaling is a first-order sensitivity
approximation; its virtual 50% uniqueness follows from symmetric IID sampling
and is not empirical validation.

## Recorded development environment

The devcontainer now includes ngspice and pins the revisions that are actually
known:

- base distribution: Ubuntu 24.04 devcontainer image tag;
- TinyTapeout support tools:
  `d65690eeb1d4afd26aef795c805a23d9d9daf9d1`;
- LibreLane: `2.4.2`;
- Verible: `v0.0-4023-gc1271a00`;
- cocotb: `2.0.1`; pytest: `8.4.2`; matplotlib: `3.10.8`.

Ubuntu APT packages, the base-image digest, transitive Python dependencies, the
SKY130 PDK, and the `ttsky26c` GitHub Action tag are not immutably locked by the
historical repository. Record `python --version`, `ngspice --version`,
`iverilog -V`, `verilator --version`, `pip freeze`, container image digest, PDK
commit, source commit, and resolved action SHAs for a publishable rerun.

The post-start helper now links `./tt` to the exact image checkout. It never
performs an implicit `git pull` and preserves an existing non-symlink `tt`
directory unchanged.

## Physical evidence

See `SIGNOFF.md`. The macro and standalone-array directories contain broad
final bundles, while `dualarm/build_debug/` is a partial mixed-stage snapshot.
Do not use the latter to claim a complete final GDS or KLayout signoff.
