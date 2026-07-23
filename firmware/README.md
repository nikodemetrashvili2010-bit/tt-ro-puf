# Fabricated-device measurement kit

These scripts were written before silicon was available. They implement the
planned measurement protocol and the analysis needed to test the pre-silicon
prediction. The pin protocol was checked against `dualarm/src/tt_um_ro_puf.v`;
board and SDK behavior still needs checking with the returned hardware.

## Files

- `measure_puf.py` runs on a TinyTapeout demo board (MicroPython, TT SDK v3).
  It measures all 32 oscillators in randomized rounds and prints a metadata
  header plus one CSV row per sample.
- `analyze_counts.py` runs on a PC (Python standard library only). It keeps
  chip, condition, and run separate, treats the physical die as the
  experimental unit, and reports descriptive metrics with a bootstrap-by-chip
  interval.

The pre-silicon hypothesis is that the centred Arm A frequency pattern will be
more correlated across chips than the Arm B pattern. That is a prediction, not
an assumption built into the analyzer.

## Why the acquisition is randomized

A plain arm-by-arm, oscillator-by-oscillator sweep confounds slow drift (board
warm-up, USB supply sag, reference-clock drift) with arm and oscillator index:
whatever is measured later carries the drift. `measure_puf.py` instead measures
all 32 selections once per round in a fresh random order, and repeats that for
`ROUNDS` rounds, recording the random seed, the per-sample timestamp, and the
acquisition order. Drift is then spread across oscillators and visible in the
data rather than baked into a position. Take many rounds (the default is 60;
50-100 is reasonable) so within-oscillator noise, within-chip drift, and
between-position differences can be separated.

## Set the CONFIG block, and measure rather than label

Edit the CONFIG block at the top of `measure_puf.py` for each run. A label like
`room_1v8` is a nominal setting, not a measurement, so fill in what you
actually measured:

- `CHIP_ID` and `CONDITION` (kept out of one human label; they are separate
  CSV columns and metadata fields);
- `MEAS_VDD_V`, the measured core supply, not the nominal one;
- `MEAS_CLK_HZ`, the measured project clock if you can measure it (the reported
  count scales with `f_osc / f_reference`, so two boards whose clocks differ by
  0.2% give a 0.2% absolute-frequency difference on identical silicon);
- `TEMP_METHOD` and `MEAS_TEMP_C` from a sensor near the package, not the name
  on a freeze-spray can. Package temperature is still not die temperature; say
  what you measured.

The script emits a `# META {json}` line with a run UUID, seed, requested and
measured clock, measured supply, temperature, board revision, and site, so
community-submitted CSVs stay interpretable.

## Taking a measurement

1. `pip install mpremote` on the PC.
2. Connect the board, edit the CONFIG block.
3. Capture the output:

       mpremote run measure_puf.py > chip03_room_1v8.csv

4. Repeat per chip and condition. Analyze together:

       python3 analyze_counts.py chip01_room_1v8.csv chip02_room_1v8.csv
       python3 analyze_counts.py *.csv --positions ../dualarm/build_current/dualarm_positions.csv

   `--positions` adds a geometry-based oscillator pairing alongside the logical
   one; both pairings are fixed before the frequencies are seen.

## What the analyzer reports

- Per chip and condition: mean, peak-to-peak, standard deviation, median and
  MAD (peak-to-peak alone is outlier-sensitive), and the within-oscillator
  repeat noise.
- Across chips at one condition: the centred pattern correlation as a point
  estimate with a 95% interval bootstrapped over whole chips, the shared
  per-position variance fraction, and inter-chip uniqueness for each predeclared
  pairing. The physical die is the unit; the chip-pair count is dependent, so
  read the bootstrap interval as the sample size, not the pair count.
- Bit reliability within a chip: per-pair bit-error rate across rounds and a
  count of fragile bits (near-tied oscillators or bits that flip across
  repeats). A bit that is 51/49 over repeats is unreliable even if its pooled
  means order it.
- The analyzer refuses to compare files with incompatible clock/window settings
  (across chips and across conditions), rejects a duplicate file or a repeated
  run UUID, and keeps raw files unmodified.

## Limits to keep in mind

- Descriptive metrics only. Hamming distance and uniformity are not entropy;
  with a handful of dies do not make a quantitative min-entropy claim.
- Sixteen oscillators give only eight disjoint adjacent-pair bits, so Hamming
  distance moves in 12.5-point steps. The stronger dataset is the 16 frequencies
  per arm across dies and repeats; response bits are a secondary interpretation.
- If every chip is measured on one board at one site, chip effect and
  board/site effect are confounded. Measure some chips on a shared board if you
  can, and record board and site either way.
- Fix the analysis before looking at silicon: tag a commit with the primary
  hypothesis, the metric, the pairings, exclusion and outlier rules, and the
  minimum chip and completeness counts. Exploratory analysis afterwards is fine
  if it is labeled exploratory.

## Protocol notes

- The counter is 16 bit; the window is fixed at 1000 reference-clock cycles. At
  25 MHz the overflow ceiling is about 1.6 GHz. Confirm the fastest process
  corner cannot overflow before trusting a run; a silent 16-bit wrap returns a
  plausible-looking lower count, not an error.
- A count of `-1` is a timeout marker; the analyzer skips it and reports the
  count. The script also flags counts near the ceiling and zero counts.
- The script fails hard if the exact project `tt_um_nikodemetrashvili20_ro_puf`
  is not on the shuttle. It does not fall back to the first project matching
  `ro_puf`, which could select the wrong die.
- The SDK calls match TT SDK v3 as of July 2026. Check the SDK release notes
  before the first hardware run.
