#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The ring-stop boundary through all 48 selector paths, screened at ff.

Until 26 October the boundary had been swept through one path of the
release build's 48, B13, the slowest rise, on grids down to 0.2 ps at ff
and 5 ps at tt and ss. The other 47 carried every edge in the steady
sweep and had never had a ring stopped in front of them. That was the last
item on the selector, and OPEN_ITEMS.md category E is the same gap on the
two-arm build.

What makes a screen of the other 47 cheap is in the decks themselves. The
first eighty lines of every one of the 48 selector decks are the same
bytes: the same macro ring, the same enable source, the same tap. Only the
chain after the tap changes. So at a given enable phase every deck hands
its chain nearly the same last pulse, and the question for each path is
which of those pulses it passes on.

Nearly, not exactly. The chain's first cell loads the tap, and the solver
picks its steps around a different circuit in every deck, so the same
phase gives a slightly wider or narrower pulse from path to path: 3.9 ps
apart across the 48 at the 32 ps phase, 1.4 ps at most at the others.
S06 measures that instead of assuming it away.

The screen holds four phases and moves the path. They are B13's own: the
enable falls at 30.080, 30.090, 30.100 and 30.110 ns, where the last high
at the tap is 32, 54, 68 and 82 ps. The 5 ps sweep through B13 puts its
step between 75 and 82, and the 1 ps one between 75 and 77, so B13 passes
only the fourth. Its two phases at 30.100 and 30.110 are also rows of the
archived 5 ps sweep, which makes it the control: S05 wants those rows back
field for field.

For each path this reports which of the four pulses reached the flop, so
where its step sits against B13's, the narrowest high that arrived at
sel_ro, and whether every phase left the flop on a rail with the count
moving by one edge at most. A path that passes all four has its step
below 32 ps and one that passes none has it above 82. Neither is a
failure; both are said.

Checks:
  S01  every path has its four phases, each with a steady delay measured
  S02  every phase leaves the flop on a rail
  S03  no two adjacent phases differ by more than one edge
  S04  a pulse that reaches the flop is never followed by a wider one
       that does not, and the count never steps down
  S05  B13's phases at 30.100 and 30.110 ns are the archived 5 ps rows
  S06  the last pulse at the tap agrees across the paths at each phase,
       within 5 ps, which is the shared-ring argument checked on the data.
       5 is a third of the 14 ps between the screened widths

What it cannot do. Four phases on a 10 ps grid say where a step is to
within a pulse width or two, and nothing about the pulse that sits exactly
on it. B13's own grids showed the narrowest pulse at sel_ro shrinking with
every finer grid, so that number belongs to the grid. The screen is the
cheap pass that says whether any path deserves the fine treatment B13 got.
It is ff only.

Run:
    python3 boundary_screen.py bnd3/screen_ff \\
        --control boundary_validation_B13_3arm_5ps.csv \\
        --csv boundary_screen_ff.csv
    python3 boundary_screen.py --selftest
"""

import argparse
import csv
import glob
import io
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import analyze_boundary_sweep as abs_   # noqa: E402

VDD = 1.95
TAIL_NS = 2.0
N_PHASE = 4
TAP_TOL_PS = 5.0
CONTROL_TAG = "B13"
CONTROL_FALLS = ("30.100", "30.110")
TAG_RE = re.compile(r"^[ABC]\d\d$")

CSV_HEAD = ["osc", "cells", "rise_ps", "fall_ps", "asymmetry_ps",
            "tap_ps", "arrived", "swallowed_up_to_ps", "arrived_from_ps",
            "narrowest_sel_ps", "flop_edges", "settled"]


def chain_of(directory):
    """The chain the generator wrote into the first deck's comment."""
    for path in sorted(glob.glob(os.path.join(directory, "bnd_*.spice"))):
        for line in open(path, encoding="utf-8", errors="replace"):
            m = re.match(r"\*\s*chain:\s*(.+?)\s*$", line)
            if m:
                return m.group(1)
    return ""


def read_path(directory):
    rows = []
    for path in sorted(glob.glob(os.path.join(directory, "bnd_*.raw.txt"))):
        rows.append(abs_.read_phase(directory, path, VDD, TAIL_NS))
    return sorted(rows, key=lambda r: r["t_fall"])


def ps(x):
    return int(round(x * 1e12))


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def summarise(tag, rows, chain):
    arrived = [r for r in rows if r["measured"] and r["arrived"]]
    gone = [r for r in rows if r["measured"] and not r["arrived"]]
    rise = [r["rise_d"] for r in rows if r["rise_d"]]
    fall = [r["fall_d"] for r in rows if r["fall_d"]]
    cells = len(chain.split()) if chain else 0
    return {
        "osc": tag,
        "cells": cells,
        "rise_ps": ps(median(rise)) if rise else "",
        "fall_ps": ps(median(fall)) if fall else "",
        "asymmetry_ps": ps(median(fall) - median(rise)) if rise and fall
        else "",
        "tap_ps": " ".join(str(ps(r["tap_hi"])) for r in rows),
        "arrived": "".join("1" if r["arrived"] else "0" for r in rows),
        "swallowed_up_to_ps": max(ps(r["tap_hi"]) for r in gone)
        if gone else "",
        "arrived_from_ps": min(ps(r["tap_hi"]) for r in arrived)
        if arrived else "",
        "narrowest_sel_ps": min(ps(r["sel_hi"]) for r in arrived)
        if arrived else "",
        "flop_edges": " ".join(str(r["toggles"]) for r in rows),
        "settled": "yes" if rows and all(r["settled"] for r in rows)
        else "no",
    }


def analyser_rows(rows):
    """The archived sweep's csv rows for these phases, written by the
    analyser's own writer so the comparison is like for like."""
    tmp = tempfile.mkdtemp(prefix="screen_ctl.")
    try:
        out = os.path.join(tmp, "rows.csv")
        keep, sys.stdout = sys.stdout, io.StringIO()
        try:
            abs_.report(rows, abs_.compare_models(rows), csv_path=out)
        finally:
            sys.stdout = keep
        with open(out, encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_checks(paths, control_csv, control_falls=CONTROL_FALLS):
    res = []

    def add(cid, name, ok, detail):
        res.append((cid, name, bool(ok), detail))

    short = ["%s has %d" % (t, len(p["rows"]))
             for t, p in sorted(paths.items())
             if len(p["rows"]) != N_PHASE
             or not all(r["measured"] for r in p["rows"])]
    add("S01", "every path has its four phases, each measured", not short,
        "; ".join(short[:6]) or "%d paths, %d phases"
        % (len(paths), sum(len(p["rows"]) for p in paths.values())))

    loose = ["%s %.3f ns" % (t, r["t_fall"] * 1e9)
             for t, p in sorted(paths.items()) for r in p["rows"]
             if not r["settled"]]
    add("S02", "every phase leaves the flop on a rail", not loose,
        "; ".join(loose[:6]) or "none off a rail")

    jumps, downs = [], []
    for t, p in sorted(paths.items()):
        c = [r["toggles"] for r in p["rows"]]
        for a, b in zip(c, c[1:]):
            if abs(b - a) > 1:
                jumps.append("%s %d to %d" % (t, a, b))
    add("S03", "no two adjacent phases differ by more than one edge",
        not jumps, "; ".join(jumps[:6]) or "none")

    for t, p in sorted(paths.items()):
        got = [r["arrived"] for r in p["rows"] if r["measured"]]
        c = [r["toggles"] for r in p["rows"]]
        back = any(got[i] and not got[i + 1] for i in range(len(got) - 1))
        if back or any(b < a for a, b in zip(c, c[1:])):
            downs.append(t)
    add("S04", "no wider pulse is lost after a narrower one arrived, and "
               "the count never steps down", not downs,
        ", ".join(downs) or "none")

    bad = []
    ctl = paths.get(CONTROL_TAG)
    if ctl is None:
        bad.append("no %s in the screen" % CONTROL_TAG)
    elif not control_csv or not os.path.exists(control_csv):
        bad.append("no archived sweep to hold it to")
    else:
        with open(control_csv, encoding="utf-8") as fh:
            ref = dict((r["en_fall_ns"], r) for r in csv.DictReader(fh))
        mine = dict((r["en_fall_ns"], r) for r in analyser_rows(ctl["rows"]))
        for fall in control_falls:
            if fall not in ref or fall not in mine:
                bad.append("%s ns missing" % fall)
                continue
            diff = [k for k in ref[fall] if k != "phase"
                    and ref[fall][k] != mine[fall].get(k)]
            if diff:
                bad.append("%s ns differs in %s" % (fall, ", ".join(diff)))
    add("S05", "%s's shared phases are the archived 5 ps rows" % CONTROL_TAG,
        not bad, "; ".join(bad) or "%d rows, every field"
        % len(control_falls))

    spread, widest = [], 0.0
    full = [p for p in paths.values() if len(p["rows"]) == N_PHASE]
    for k in range(N_PHASE):
        taps = [p["rows"][k]["tap_hi"] * 1e12 for p in full]
        if not taps:
            continue
        span = max(taps) - min(taps)
        widest = max(widest, span)
        if span > TAP_TOL_PS:
            spread.append("phase %d spans %.2f ps" % (k, span))
    add("S06", "the last pulse at the tap agrees across the paths",
        not spread, "; ".join(spread) or "widest spread %.3f ps" % widest)
    return res


def load(directory):
    paths = {}
    for d in sorted(glob.glob(os.path.join(directory, "*"))):
        tag = os.path.basename(d)
        if os.path.isdir(d) and TAG_RE.match(tag):
            rows = read_path(d)
            paths[tag] = {"rows": rows, "chain": chain_of(d)}
    return paths


def write_csv(summaries, path):
    with open(path, "w", newline="\n", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_HEAD, lineterminator="\n")
        w.writeheader()
        for s in summaries:
            w.writerow(s)


def report(paths, control_csv, csv_path=None, control_falls=CONTROL_FALLS):
    summaries = [summarise(t, p["rows"], p["chain"])
                 for t, p in sorted(paths.items())]
    order = sorted(summaries, key=lambda s: (s["arrived"], s["osc"]))
    print("ring-stop boundary through every selector path")
    print()
    print("  path  cells  rise  asym  arrived  step at the tap      "
          "narrowest at sel_ro  edges")
    for s in order:
        lo, hi = s["swallowed_up_to_ps"], s["arrived_from_ps"]
        if hi == "":
            step = "above %s ps" % lo
        elif lo == "":
            step = "below %s ps" % hi
        else:
            step = "%s to %s ps" % (lo, hi)
        print("  %s  %5s  %4s  %4s  %7s  %-19s  %19s  %s"
              % (s["osc"], s["cells"], s["rise_ps"], s["asymmetry_ps"],
                 s["arrived"], step,
                 ("%s ps" % s["narrowest_sel_ps"])
                 if s["narrowest_sel_ps"] != "" else "none",
                 s["flop_edges"]))
    print()
    groups = {}
    for s in summaries:
        groups.setdefault(s["arrived"], []).append(s["osc"])
    for pattern in sorted(groups):
        print("  %s  %2d paths" % (pattern, len(groups[pattern])))
    print()
    res = run_checks(paths, control_csv, control_falls)
    for cid, name, ok, detail in res:
        print("  %s %s  %s" % ("ok  " if ok else "FAIL", cid, name))
        print("            %s" % detail)
    if csv_path:
        write_csv(summaries, csv_path)
        print()
        print("wrote %s" % csv_path)
    bad = [cid for cid, _, ok, _ in res if not ok]
    print()
    print("FAIL: %s" % ", ".join(bad) if bad else
          "PASS: every phase on every path left the flop on a rail, the count "
          "moved by one edge at most, and no wider pulse was lost after a "
          "narrower one")
    return 1 if bad else 0


# -------------------------------------------------------------- selftest

# A synthetic ring that rises at 15.56 ns stops at these four falls, so its
# last high is 32, 54, 68 and 82 ps wide, the widths the real screen uses.
S_PERIOD = 1.13e-9
S_FALLS = (15.592e-9, 15.614e-9, 15.628e-9, 15.642e-9)
S_CONTROL = ("15.628", "15.642")
S_RISE, S_FALL = 0.350e-9, 0.521e-9


def make_path(root, tag, min_width, period=S_PERIOD, hang=None, extra=None,
              lost=None, missing=None):
    d = os.path.join(root, tag)
    os.makedirs(d)
    for k, t_fall in enumerate(S_FALLS):
        width = 90e-12 if k == lost else min_width
        abs_._synth(d, k, VDD, period, t_fall, S_RISE, S_FALL, width,
                    hang=(k == hang), extra_edges=1 if k == extra else 0)
        with open(os.path.join(d, "bnd_%02d.spice" % k), "a",
                  encoding="utf-8") as fh:
            fh.write("* chain: a22o_2.A1 a211o_2.A2\n")
    if missing is not None:
        os.remove(os.path.join(d, "bnd_%02d.raw.txt" % missing))


def make_tree(root, **faults):
    os.makedirs(root)
    make_path(root, "A00", 40e-12, **faults.get("A00", {}))
    make_path(root, "B13", 75e-12, **faults.get("B13", {}))
    make_path(root, "C00", 60e-12, **faults.get("C00", {}))
    ctl = os.path.join(root, "control.csv")
    rows = analyser_rows(read_path(os.path.join(root, "B13")))
    with open(ctl, "w", newline="\n", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return ctl


def selftest():
    print("self-test of boundary_screen")
    ok = True
    tmp = tempfile.mkdtemp(prefix="screen_selftest.")
    try:
        cases = [
            ("a clean screen passes", {}, None, []),
            ("a phase with no waveform", {"A00": {"missing": 1}}, None,
             ["S01"]),
            ("a flop left at mid-rail", {"C00": {"hang": 3}}, None, ["S02"]),
            ("a count that jumps two edges", {"A00": {"extra": 3}}, None,
             ["S03"]),
            ("a wider pulse lost after a narrower one arrived",
             {"C00": {"lost": 3}}, None, ["S04"]),
            ("the control no longer the archived rows", {}, "sel_high_ps",
             ["S05"]),
            ("one path handed a different pulse",
             {"C00": {"period": S_PERIOD + 1.0e-12}}, None, ["S06"]),
        ]
        for i, (label, faults, poison, expect) in enumerate(cases):
            root = os.path.join(tmp, "t%d" % i)
            ctl = make_tree(root, **faults)
            if poison:
                with open(ctl, encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
                for r in rows:
                    if r["en_fall_ns"] == S_CONTROL[1]:
                        r[poison] = str(int(r[poison]) + 1)
                with open(ctl, "w", newline="\n", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0]),
                                       lineterminator="\n")
                    w.writeheader()
                    w.writerows(rows)
            paths = load(root)
            got = [cid for cid, _, good, _ in
                   run_checks(paths, ctl, S_CONTROL) if not good]
            good = got == expect
            if i == 0:
                arrived = dict((t, summarise(t, p["rows"], p["chain"])
                                ["arrived"]) for t, p in paths.items())
                good = good and arrived == {"A00": "0111", "B13": "0001",
                                            "C00": "0011"}
            ok = ok and good
            print("  %-52s %s" % (label, ("ok" if not expect else
                                          "trips %s" % expect[0])
                                  if good else "MISSED, tripped %s" % got))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("self-test %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("directory", nargs="?")
    ap.add_argument("--control", help="the archived sweep B13 is held to")
    ap.add_argument("--csv", help="write the per-path record here")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.directory:
        ap.error("give the screen directory, or --selftest")
    paths = load(args.directory)
    if not paths:
        raise SystemExit("no path directories in %s" % args.directory)
    return report(paths, args.control, args.csv)


if __name__ == "__main__":
    sys.exit(main())
