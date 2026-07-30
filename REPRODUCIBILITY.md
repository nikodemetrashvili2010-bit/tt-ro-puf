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
python3 sim/spice/gono/verify_predictability.py
python3 sim/spice/gono/analyze_noise.py --selftest
python3 sim/spice/gono/analyze_noise.py
python3 sim/spice/mc/analyze_mc.py sim/spice/mc/mc_out.txt
```

Each verifier exits nonzero on failure. A pass means the headline numbers
match the checked-in raw logs and CSV files; independent replication still
needs a fresh SPICE run against your own PDK install. The provenance check
binds the archived source and evidence blobs to a reachable historical
commit. The bundle check is narrower and asks one question: did the DEF,
netlist, SPEF and metrics in an archived build folder come from the same flow
run. It says nothing about whether that run was any good.

Figures regenerate with the pinned packages in `requirements-analysis.txt`:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-analysis.txt
python3 sim/spice/gono/analyze.py
python3 docs/figures/make_block_diagram.py
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
deck. The generators use the same environment variables and fail when the
model files are missing. `gen_dualarm_decks.py` needs all Arm A ring nets in
the SPEF and placement centroids for all 16 oscillators in a matching DEF
from the same final run. Its defaults point at the coherent
`dualarm/build_current/` bundle; the older `dualarm/build_debug/` snapshot is
a mixed-stage checkpoint that the generator rejects if given. Keep regenerated
files outside the evidence directories and inspect `git diff` before accepting
any regenerated data.

The verifiers accept `--ctrl`, `--par`, `--log-5p`, `--log-1p`, `--csv`,
`--spef`, and related path options (see `--help`), so a fresh run can be
checked without touching the archived logs.

The distributed-RC comparison behind Section 5.5 of the paper and item 7 of
`docs/hardware_todo.md` has no archived logs, so it is regenerated like this:

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

The archived decks use nominal TT models at 1.8 V and transfer only SPEF
`*D_NET` total capacitance as lumped loads. Distributed resistance, coupling
topology, mismatch, PVT sweeps, and supply noise are out of scope here; the
paper's limitations section says what that means for the claims.

## Recorded development environment

The devcontainer includes ngspice and pins the revisions that are actually
known:

- base distribution: Ubuntu 24.04 devcontainer image tag;
- TinyTapeout support tools: `d65690eeb1d4afd26aef795c805a23d9d9daf9d1`;
- LibreLane: `2.4.2`;
- Verible: `v0.0-4023-gc1271a00`;
- cocotb: `2.0.1`; pytest: `8.4.2`; matplotlib: `3.10.8`.

APT packages, the base-image digest, transitive Python dependencies, the
SKY130 PDK, and the `ttsky26c` GitHub Action tag are not immutably locked by
the historical repository. For a publishable rerun, record `python
--version`, `ngspice --version`, `iverilog -V`, the container image digest,
the PDK commit, the source commit, and the resolved action SHAs.

The post-start helper links `./tt` to the exact image checkout. It never
performs an implicit `git pull` and leaves an existing non-symlink `tt`
directory unchanged.

## Which file is which

The repository keeps failed and superseded builds as provenance, so here is
the short answer to "which one is current":

- Tapeout candidate GDS and its checks: `dualarm/build_current/` (the coherent
  build from the current RTL). This is what the headline 5.53% comes from, via
  its `.nom.spef` and the go/no-go logs in `sim/spice/gono/`. The nine-build
  dispersion band around it lives in `dualarm/placement_sweep/`.
- Figures 2 and 3 come from the earlier 32-oscillator build under
  `sim/spice/gono/first_build/`; Figure 4 comes from `dualarm/build_current/`.
- Everything under `dualarm/build_debug/`, `array/`, and
  `macro/romacro_final/` is historical or component evidence, not the tapeout
  chip. `build_debug` in particular is an older, incomplete snapshot kept only
  for contrast.

## Freezing the final release

Provenance today binds the archived analysis bundle, not a locked tapeout
release. See the note in `sim/spice/gono/verify_provenance.py` for what that
check does and does not cover. Before I order silicon I will cut one tagged
release where everything lines up: source commit, TinyTapeout config, the macro
and top GDS, the DEF and SPEF, the metrics, the DRC/LVS/XOR reports, the deck
generators, the raw logs, and the paper numbers. The same tag records the parts
that can still move today. That means the resolved SHAs behind
`actions/checkout` and `TinyTapeout/tt-gds-action`, the SKY130 PDK commit, the
LibreLane and OpenROAD revisions, the container image digest, `pip freeze`, and
the tool versions listed above. After that the tag is the artifact, not a
branch that keeps moving.

## Physical evidence

See [SIGNOFF.md](SIGNOFF.md) for the per-artifact status.
