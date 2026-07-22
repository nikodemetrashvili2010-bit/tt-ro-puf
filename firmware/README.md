# Fabricated-device measurement kit

These scripts were written before silicon was available. They implement the
planned measurement protocol and the analysis needed to test the pre-silicon
prediction. The pin protocol was checked against
`dualarm/src/tt_um_ro_puf.v`; board and SDK behavior still needs to be checked
with the returned hardware.

## Files

- `measure_puf.py` runs on a TinyTapeout demo board using MicroPython and the
  TT SDK v3 interface. It measures all 32 oscillators, five samples each, and
  prints CSV.
- `analyze_counts.py` runs on a PC using only the Python standard library. It
  keeps chip identity and measurement condition separate, reports descriptive
  per-arm statistics, and computes comparison metrics only when the input set
  supports them.

The pre-silicon hypothesis is that the centred Arm A frequency pattern will be
more correlated across chips than the Arm B pattern. That is a prediction, not
an assumption built into the analyzer.

## Label convention

Set `LABEL` in `measure_puf.py` to `chip_id_condition`. The first underscore
separates the stable chip identifier from the condition. The rest of the label
may contain underscores:

    chip03_room_1v8
    chip03_freeze_1v8
    chip04_room_1v8

The first two files are two conditions for one chip. The first and third are
two chips at the same condition. Do not change the chip identifier between
runs on the same physical device.

## Taking a measurement

1. Install `mpremote` on the PC:

       pip install mpremote

2. Connect the demo board and edit `LABEL` in `measure_puf.py`.
3. Run the script and capture its output:

       mpremote run measure_puf.py > chip03_room_1v8.csv

4. Repeat the run for each chip and condition. Record actual temperature and
   supply voltage separately in the experiment log; labels such as `freeze`
   and `hairdryer` are only shorthand.
5. Analyze the files together:

       python3 analyze_counts.py chip01_room_1v8.csv chip02_room_1v8.csv

## What the analyzer will and will not report

- Per-chip summaries can use partial data, but the output states how many of
  the 16 oscillators were present.
- Cross-chip pattern correlation requires complete measurements from at least
  two distinct chips at the same condition and matching clock/window metadata.
- Inter-chip uniqueness uses eight fixed adjacent oscillator pairs and is
  reported only when at least two complete chip responses exist and no pair is
  tied at the available count resolution.
- Cross-condition response comparison requires one chip measured completely
  under at least two conditions. It compares responses formed from the mean
  count at each condition; it is not a repeat-level bit-error estimate.
- If those requirements are not met, the analyzer prints `insufficient data`
  instead of interpreting files from different chips or conditions as a PUF
  population.

These descriptive metrics do not establish entropy or security by themselves.
A credible result also needs enough chips, repeat runs, uncertainty estimates,
and a measurement protocol fixed before looking at the outcome. Pairwise
comparisons share chips and therefore are not independent observations; the
analyzer does not calculate confidence intervals.

## Protocol notes

- The counter is 16 bit and the window is fixed at 1000 reference-clock
  cycles. At a 25 MHz reference clock the nominal overflow ceiling is about
  1.6 GHz. Do not use a substantially lower reference clock without checking
  the fastest expected corner.
- A count of `-1` is a timeout marker. The analyzer skips it and reports the
  number of skipped samples.
- The SDK calls match the TT SDK v3 interface available when this script was
  written in July 2026. Check the SDK release notes before the first hardware
  run.
- The expected shuttle project name is
  `tt_um_nikodemetrashvili20_ro_puf`; the script also searches for `ro_puf` as
  a fallback.
