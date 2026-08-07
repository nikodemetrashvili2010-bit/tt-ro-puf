#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Check the archived selector-sweep run records against `mux_validation.csv`.

Item 2 ran 32 decks plus 32 blocked controls and kept only the derived CSV.
`sim/spice/gono/mux/` now holds, for each of the 64, its ngspice console log,
its deck, and its waveform reduced by `reduce_raw.py`. That is 4.5 MB standing
in for 180 MB, and the reduction is lossless for this analysis rather than
approximately so: every field the analyzer returns is identical from the reduced
file and the full one, deck by deck, which `reduce_raw.py --verify` checks
against the real analyzer.

So the sweep is now re-derivable the way the supply run and the per-instance run
are. CI regenerates `mux_validation.csv` from this folder and diffs it against
the archived copy, and the two are byte-identical.

This script is the bookkeeping half. It re-derives nothing itself, since
duplicating the analyzer would only test whether I can copy code, and CI already
runs the analyzer for real. What it checks is what archiving can get wrong: a
CSV row with no run behind it, a log filed under the wrong oscillator, a
truncated or failed run, a missing blocked control, a missing waveform, decks
that did not all run the same transient, and a stray file belonging to something
else.

The rerun that produced this archive found a two-picosecond error, and not in
the CSV. All 256 values came back identical. What was wrong was a sentence in
`docs/hardware_todo.md` that quoted B15's tap levels from the boundary decks in
a paragraph about the mux decks.

The first version of this script failed on a perfectly good archive, and the
reason is worth keeping. `gen_mux_sweep.py` writes `mux_ctlA00_out.txt` for a
blocked control, and I had guessed at `ctrl`. So every control file was counted
as an open log, and because `mux_ctlA00_out.txt` contains the string `A00` it
also matched A00 as a second hit, and 64 correct files read as 32 duplicates and
zero controls. The selftest passed throughout, because its fixture used the
filenames I had imagined rather than the ones the generator emits. Names now
come from FILENAMES below, which mirrors the generator, and the fixture uses the
real pattern.

Usage:
    python3 verify_mux_archive.py
    python3 verify_mux_archive.py --dir mux
    python3 verify_mux_archive.py --selftest
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Exactly what gen_mux_sweep.py writes, from its own lines:
#     atomic_write_text(... "mux_%s.spice" % tag)
#     atomic_write_text(... "mux_ctl%s.spice" % tag)
# and run_ngspice.py appends _out.txt. Matching by substring instead of by these
# two patterns is what broke the first version of this script, because a control
# filename contains its oscillator's name.
FILENAMES = {
    "open": "mux_{osc}_out.txt",
    "control": "mux_ctl{osc}_out.txt",
}

# The waveforms beside them, reduced by reduce_raw.py. These are what
# analyze_mux_sweep.py actually reads, and CI regenerates the CSV from them and
# diffs it against the archived one, so their presence is not cosmetic.
WAVEFORMS = {
    "open": "mux_{osc}.raw.txt",
    "control": "mux_ctl{osc}.raw.txt",
}


class ArchiveError(Exception):
    pass


def scan_log(path: str) -> dict:
    """What one deck's log says about itself.

    A run that died still leaves a file, and an empty or truncated log has to
    read as a failure rather than as a quiet zero.
    """
    txt = open(path).read()
    if len(txt) < 200:
        raise ArchiveError(f"{os.path.basename(path)}: {len(txt)} bytes, "
                           f"too short to be a finished run")
    rows = re.search(r"No\. of Data Rows\s*:\s*(\d+)", txt)
    if not rows:
        raise ArchiveError(f"{os.path.basename(path)}: no data-row count, so "
                           f"the transient did not finish")
    fatal = re.search(r"^\s*(fatal|Fatal|error|Error)\b.*$", txt, re.M)
    return dict(rows=int(rows.group(1)),
                fatal=fatal.group(0).strip() if fatal else None,
                bytes=len(txt))


def verify(directory: str, csv_path: str) -> dict:
    if not os.path.isdir(directory):
        raise ArchiveError(f"no archive directory {directory}")
    rows = list(csv.DictReader(open(csv_path)))
    if not rows:
        raise ArchiveError(f"{csv_path} is empty")

    present = set(f for f in os.listdir(directory) if f.endswith("_out.txt"))

    found, missing, bad, ctrl = {}, [], [], {}
    for r in rows:
        osc = r["osc"]
        for kind, pattern in FILENAMES.items():
            name = pattern.format(osc=osc)
            if name not in present:
                missing.append((osc, kind, name))
                continue
            try:
                rec = scan_log(os.path.join(directory, name))
                rec["file"] = name
                (found if kind == "open" else ctrl)[osc] = rec
            except ArchiveError as exc:
                bad.append(str(exc))

    # The waveforms the analyzer reads. Their absence would leave a folder that
    # looks archived and re-derives nothing.
    all_files = set(os.listdir(directory))
    waves_missing = [w.format(osc=r["osc"]) for r in rows
                     for w in WAVEFORMS.values()
                     if w.format(osc=r["osc"]) not in all_files]

    expected = {p.format(osc=r["osc"]) for r in rows for p in FILENAMES.values()}
    lens = {v["rows"] for v in found.values()}
    return dict(csv_rows=len(rows), open_logs=len(found), ctrl_logs=len(ctrl),
                matched=len(found), missing=missing, bad=bad,
                waves_missing=waves_missing,
                unexpected=sorted(present - expected),
                transient_lengths=sorted(lens),
                fatals=[f"{k}: {v['fatal']}" for k, v in found.items() if v["fatal"]])


def verdicts(v: dict) -> list[tuple[bool, str]]:
    out = []
    out.append((not v["missing"],
                f"every one of the {v['csv_rows']} CSV rows has both its logs "
                f"under the generator's own names (missing: {v['missing'][:3]})"))
    out.append((v["matched"] == v["csv_rows"],
                f"{v['matched']} open-path logs against {v['csv_rows']} CSV rows"))
    out.append((v["ctrl_logs"] == v["csv_rows"],
                f"{v['ctrl_logs']} blocked-control logs against "
                f"{v['csv_rows']} paths"))
    out.append((not v["unexpected"],
                f"no log in the folder belongs to something else "
                f"({v['unexpected'][:3]})"))
    out.append((not v["waves_missing"],
                f"the reduced waveform is present for all {2*v['csv_rows']} "
                f"decks, so the CSV can be regenerated "
                f"(missing: {v['waves_missing'][:3]})"))
    out.append((not v["bad"],
                f"no truncated or unfinished log ({len(v['bad'])} found)"))
    out.append((not v["fatals"],
                f"no log reports a fatal ({len(v['fatals'])} found)"))
    out.append((len(v["transient_lengths"]) == 1,
                f"every deck ran the same transient length: "
                f"{v['transient_lengths']}"))
    return out


def selftest() -> int:
    import tempfile

    GOOD = ("ngspice output\n" + "x" * 300 +
            "\nNo. of Data Rows : 30014\nrun complete\n")

    def make(n_open=3, n_ctrl=3, corrupt=None, rows="30014", extra=None):
        # The fixture uses the generator's real names. The version that used
        # names I had guessed at passed while the real archive failed.
        d = tempfile.mkdtemp()
        oscs = ["A00", "A01", "B15"][:n_open]
        for o in oscs:
            body = GOOD.replace("30014", rows) if o == "B15" else GOOD
            if corrupt == o:
                body = "too short"
            open(os.path.join(d, FILENAMES["open"].format(osc=o)), "w").write(body)
            open(os.path.join(d, WAVEFORMS["open"].format(osc=o)), "w").write("t v\n")
        for o in ["A00", "A01", "B15"][:n_ctrl]:
            open(os.path.join(d, FILENAMES["control"].format(osc=o)),
                 "w").write(GOOD)
            open(os.path.join(d, WAVEFORMS["control"].format(osc=o)),
                 "w").write("t v\n")
        if extra:
            open(os.path.join(d, extra), "w").write(GOOD)
        c = os.path.join(d, "mux.csv")
        with open(c, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["osc"])
            for o in oscs:
                w.writerow([o])
        return d, c

    cases = []

    def clean():
        d, c = make()
        return all(ok for ok, _ in verdicts(verify(d, c)))
    cases.append(("a complete archive passes", clean, True))

    def one_missing():
        d, c = make()
        os.remove(os.path.join(d, "mux_A01_out.txt"))
        return not verdicts(verify(d, c))[0][0]
    cases.append(("a CSV row with no log fails", one_missing, True))

    def truncated():
        d, c = make(corrupt="A01")
        return not verdicts(verify(d, c))[5][0]
    cases.append(("a truncated log fails", truncated, True))

    def missing_controls():
        d, c = make(n_ctrl=1)
        return not verdicts(verify(d, c))[2][0]
    cases.append(("a missing blocked control fails", missing_controls, True))

    def uneven():
        d, c = make(rows="10014")
        return not verdicts(verify(d, c))[7][0]
    cases.append(("decks that ran different transient lengths fail",
                  uneven, True))

    # The failure this script actually hit: a control filename contains its
    # oscillator's name, so substring matching sees it as a second open log.
    def control_not_counted_as_open():
        d, c = make()
        v = verify(d, c)
        return (v["open_logs"] == 3 and v["ctrl_logs"] == 3
                and all(ok for ok, _ in verdicts(v)))
    cases.append(("a control named mux_ctlA00 is not counted as A00's open log",
                  control_not_counted_as_open, True))

    def stray_file():
        d, c = make(extra="mux_Z99_out.txt")
        return not verdicts(verify(d, c))[3][0]
    cases.append(("a log belonging to no CSV row is reported", stray_file, True))

    def no_dir():
        try:
            verify(tempfile.mkdtemp() + "/nope", "x")
            return False
        except ArchiveError as e:
            return "no archive directory" in str(e)
    cases.append(("an absent archive directory is caught", no_dir, True))

    print("selftest")
    bad = 0
    for name, fn, want in cases:
        try:
            got = fn()
        except Exception as exc:                       # noqa: BLE001
            got, name = False, f"{name}  [raised {exc!r}]"
        ok = got == want
        bad += not ok
        print(f"  {'pass' if ok else 'FAIL'}  {name}")
    print(f"{len(cases) - bad} of {len(cases)} selftests pass")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.join(HERE, "mux"))
    ap.add_argument("--csv", default=os.path.join(HERE, "mux_validation.csv"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    v = verify(args.dir, args.csv)
    for ok, line in verdicts(v):
        print(f"  {'ok  ' if ok else 'FAIL'}  {line}")
    failed = sum(not ok for ok, _ in verdicts(v))
    print(f"\n{len(verdicts(v)) - failed} of {len(verdicts(v))} checks pass")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArchiveError as exc:
        print(f"verify_mux_archive: {exc}", file=sys.stderr)
        raise SystemExit(2)
