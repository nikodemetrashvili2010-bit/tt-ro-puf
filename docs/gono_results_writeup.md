# Fake entropy from automated layout in an RO-PUF (pre-silicon evidence)

Results notes, SILICON project. First written 2026-06-20 from the routed
TinyTapeout/sky130 build, updated 2026-07-09. Everything is reproducible from
`sim/spice/gono/`.

## Summary

I ran extracted-parasitic SPICE on the auto-placed ring-oscillator array. The
open-source layout flow gives 32 logically identical oscillators a
deterministic frequency spread of **8.8% peak-to-peak** (about 1.9% std), and
per-oscillator routing capacitance explains the spread almost completely
(r = -0.997). The effect is fixed by the mask and the transistors are nominal,
so every fabricated die carries the same pattern. That is deterministic,
shared, fake entropy. An attacker characterizes it once and predicts it
everywhere. A matched hardened-macro layout (Arm B) removes it: 16
bit-identical copies of one hardened oscillator share identical internal
parasitics, so the spread is zero by construction. As of 2026-07-09 the Arm B
macro is built, its 16-copy array is fully signed off (DRC, LVS, antenna,
power connectivity), the matched frequency is measured at 569.5 MHz (within
0.35% of the Arm A mean), and the complete two-arm chip builds green on a
TinyTapeout 2x2 tile.

## Design under test

Top module `tt_um_nikodemetrashvili20_ro_puf`: 32 ring oscillators in two
16-oscillator arms, read by one shared serial counter. Each oscillator is an
enable NAND plus 30 inverters in a loop, with an output buffer tapped at the
mid-chain node, all sky130 standard cells (`sky130_fd_sc_hd__nand2_1`,
`__inv_1`, `__buf_1`). In the baseline build studied here, all 32 oscillators
are auto-placed by the flow, so the array measures the automated-layout
behaviour. I call that Arm A.

## Method

**Parasitics from the real layout.** I used the OpenLane build's routed
gate-level netlist (`final/nl/...nl.v`) and OpenROAD RC extraction
(`final/spef/nom/...spef`) directly. This is the same data the flow uses for
timing sign-off; nothing is re-extracted. The netlist keeps all 32 oscillators
with their internal ring nodes (`...g_ro_bank[i].u_ro.n[0..30]`) and the SPEF
has a capacitance for every net.

**Per-oscillator SPICE decks.** A generator (`gen_decks.py`) emits each
oscillator exactly as routed and hangs each ring net's total SPEF capacitance
(ground plus coupling, pre-summed on the `*D_NET` line) as a lumped capacitor
to ground. Two decks come out: a control with no parasitics and a parasitic
deck with the extracted capacitance.

**Modelling choices, and why.** (i) Only one oscillator runs at a time on the
chip, so a measured oscillator's neighbours are static and their coupling
capacitance behaves as a fixed grounded load. The lumped total models exactly
that. (ii) Series wire resistance (~30 ohm) changes a stage delay by under
0.1%, so I dropped it. (iii) Transistors sit at the nominal corner on purpose.
That leaves layout parasitics as the only difference between oscillators,
which is the isolation the experiment needs; random device mismatch is the
separate Monte Carlo study. (iv) Each oscillator is enable-started (enable
held low, then released) to guarantee the fundamental mode. This mirrors how
the chip enables an oscillator. A tie-high-and-kick start had excited
higher-order ring modes that read as impossibly high frequencies, which is how
I found out it matters.

## Results

**Control (no parasitics).** All 32 oscillators read an identical 633.64 MHz,
one distinct value to 7 significant figures, matching the standalone
single-oscillator SPICE baseline (633.6 MHz). So the 32 instances are truly
identical, and any spread in the parasitic deck comes from parasitics alone.

**With extracted parasitics.** The mean frequency is 567.6 MHz (10.4%
below the control, from the loading), with a standard deviation of 10.9 MHz
(1.93% of the mean). The slowest oscillator is RO10 at 539.1 MHz, the
fastest is RO4 at 589.2 MHz, so the peak-to-peak spread is 50.2 MHz, which
is **8.8% of the mean**. The extracted ring capacitances go from 7.4 to
17.8 fF with a mean of 11.6.

**Mechanism.** Frequency tracks extracted ring capacitance at r = -0.997,
slope -4.93 MHz/fF. The highest-capacitance oscillator is the slowest, the
lowest-capacitance one is the fastest, and everything between lines up
monotonically. The router simply wired each nominally identical oscillator
with different metal.

**Spatial structure.** Frequency barely correlates with placement centroid
(|r| < 0.27 for x, y, and radius). The bias is a per-instance routing
fingerprint, not a smooth die gradient, which fits a global placer scattering
each oscillator's cells. It stays just as deterministic and just as shared. In
the planned `frequency ~ C(chip_id)*C(ro_position)` ANOVA it will show up as a
large per-position term that repeats across chips.

![mechanism and spatial map](../sim/spice/gono/ro_gono.png)

![Arm A against matched Arm B](../sim/spice/gono/armB_prediction.png)

## Interpretation

The automated flow injects a large, deterministic, position-locked frequency
pattern into identical oscillators. It is set by the mask with nominal
devices, so every fabricated chip carries the same pattern. A PUF built on it
exposes fake entropy: its inter-oscillator responses are shared across chips
and predictable from a single characterized device instead of being unique per
chip. This is the failure mode the project predicted for naive automated PUF
layout, and it is now confirmed in silicon-accurate simulation before
committing to a one-shot fabrication.

## Arm B, the matched macro

Arm B is built. One oscillator was hardened into a fixed 60x40 um macro
(`ro_macro_hard`) with LibreLane locally on 2026-06-22: DRC, LVS ("circuits
match uniquely") and antenna all clean, ring intact (30 inverters, the NAND,
the output buffer). Sixteen bit-identical copies place on a uniform 4x4 grid
(`ro_array`), and the full array run is signed off as of 2026-07-09: Magic and
KLayout DRC, LVS, antenna, and power-grid connectivity (PSM) all clean
(`array/pdnfix4_final/`, met4-only variant in `array/met4only_debug/`). The
complete two-arm chip, both arms plus the measurement core on a TinyTapeout
2x2 tile, also builds green through the same flow (branch `armb-dualarm`).

Every copy is the same GDS, so the internal ring nets carry identical
parasitics and the layout-induced spread is zero by construction, against Arm
A's 8.8%. The only per-copy wiring is `en` and `out`, which sit outside the
oscillation loop and do not set the frequency. The control experiment
(identical parasitics gave all 32 oscillators the same frequency) already
confirmed this identity argument empirically. Whatever spread remains on Arm B
in silicon is transistor mismatch, the real per-chip entropy.

### Matched frequency (measured 2026-07-09)

The hardened macro's own routed build supplies its extracted parasitics
(nom-corner SPEF). All 16 Arm B copies are the same GDS, so one simulation of
that macro is every Arm B oscillator. `gen_macro_deck.py` builds the deck with
the same methodology as the Arm A go/no-go (same models and corner,
enable-pulse startup, lumped SPEF caps, 20-period measurement) and puts a
no-parasitic control instance in the same run. The control instance reads
633.15 MHz, which agrees with the Arm A control (633.640) within 0.08%. The
matched Arm B frequency is **569.5 MHz**, 10.1% below the control. The
macro's ring capacitance is 11.01 fF, inside the Arm A range of 7.4 to
17.8 fF, and Arm A's own capacitance regression predicts 570.2 MHz for that
load, only 0.12% away from the simulated value. The numerical (timestep)
uncertainty is about 0.2% (5 ps against 1 ps `.tran`).

The matched frequency lands within 0.35% of the Arm A mean (567.6 MHz). In
other words the macro behaves like a typical Arm A routing, except all sixteen
copies share it, so the 8.8% inter-oscillator spread collapses to zero and the
operating point (counter design, measurement window) stays put. The agreement
with Arm A's own capacitance regression (predicted 570.2, simulated 569.5) is
an independent check that the extraction-to-frequency model holds across two
different builds. Every number above is re-derived from the raw files by
`verify_macro.py`, 15 checks out of 15.

### Both arms from the one submitted chip (measured 2026-07-11)

The two-arm TinyTapeout build (2x2 tile, precheck-passed) gives the whole
experiment in one layout. `gen_dualarm_decks.py` rebuilds the Arm A decks
from that build's own netlist and SPEF, same method as everything above.
Results: control puts all 16 at exactly 633.64 MHz again; with extracted
parasitics the auto-placed arm spreads 534.8 to 564.5 MHz (29.7 MHz = 5.4%
p-p, std 1.34%, mean 551.7), tracking ring capacitance at r = -0.999 within
this build. The matched arm is 569.5 MHz sixteen times over. The top-level
SPEF contains zero nets from inside the macro copies; the extractor cannot
tell the sixteen rings apart, which is the matching argument stated by the
tool itself. Cross-build check: the ORIGINAL build's cap regression predicts
this build's mean within 0.10%, and the cap spread predicts the p-p within
3%. Note the fingerprint changed between builds (5.4% here vs 8.8% before):
each run of the flow creates a new pattern and then freezes it into every
die. `verify_dualarm.py` re-derives all of it from raw files, 9/9 checks.

![both arms from the one submitted chip](../sim/spice/gono/dualarm_gono.png)

### Mismatch Monte Carlo (the real entropy, 2026-07-11)

`sim/spice/mc/` measures what remains on the matched arm. sky130 mismatch
parameters are global per run (confirmed in the PDK source; a 16-oscillator
deck gave 16 identical frequencies, which is itself the proof), so the v2
method measures the common-draw sigma of one matched oscillator over 40 runs
(0.345%, mean 568.9 MHz, within 0.11% of nominal) and divides by sqrt(31)
for independent devices: per-ring mismatch sigma 0.062%. Virtual chips from
that sigma give 50.7% key uniqueness (ideal 50). Fake-to-real ratio: Arm A's
layout spread is 21.6x the mismatch sigma by std, 87x by peak-to-peak.
Details, assumptions and the v1 postmortem are in `sim/spice/mc/README.md`.

## Limitations

- Lumped-capacitance model (argued above). Absolute MHz are good to a few
  percent; the relative spread and the r = -0.997 mechanism are the solid part.
- Nominal transistors, nominal corner only, on purpose. Mismatch and corners
  are separate studies, and min/max SPEF corners exist to bracket things later.
- The per-oscillator centroid is a coarse "position" when the placer scatters
  cells.
- Pre-silicon. This is silicon-accurate simulation, to be checked on the real
  chips once they exist.

## Reproducibility

`sim/spice/gono/` has it all: `gen_decks.py` (builds decks from netlist plus
SPEF), the decks themselves, `analyze.py` (stats, correlations),
`make_figures.py`, `verify.py` and `verify_macro.py` (independent
re-derivation of every number from the raw ngspice logs and the SPEF; all
checks pass), `predict_armB.py`, `ro_positions.csv`, `gono_results.csv`, and
the figures. Frequencies were measured in ngspice (`-b`, KLU solver) over 20
oscillation periods after enable.
